# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Multi-type filters, legacy projects and explicit checkbox interaction."""
from copy import deepcopy
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry
from moonlabeler.project import Project


CATALOG = [dict(id=key, name=key, lat=0., lon=longitude, diameter=50., kind=kind)
           for key, longitude, kind in [('crater', -8., 'Crater, craters'),
                                        ('mare', 0., 'Mare, maria'), ('rima', 8., 'Rima, rimae')]]


def project(**kwargs):
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400., 'test')
    return Project(geometry=geometry, matrix=np.array([[1000., 0, 320], [0, -1000., 240]]),
                   min_diameter=0., illuminated_only=False, optimize_layout=False, font_percent=.8, **kwargs)


@pytest.mark.parametrize('selected,expected', [
    ('全部', {'crater', 'mare', 'rima'}), ('Crater, craters', {'crater'}),
    (['Crater, craters', 'Mare, maria'], {'crater', 'mare'}), ([], set()),
])
def test_multiple_types_and_legacy_filters_roundtrip(tmp_path, selected, expected):
    p = project(kind=selected, labels={'crater': {'text': '保留名称', 'position': [30., 60.]}})
    before = deepcopy(p.labels)
    output = tmp_path/'多选地形.moonlabel'
    p.save(output)
    restored = Project.load(output)
    assert restored.kind == selected
    assert {f['id'] for f, _ in restored.visible_features(CATALOG, (480, 640, 3))} == expected
    assert restored.labels == before
    assert restored.geometry.to_dict() == p.geometry.to_dict()
    assert np.array_equal(restored.matrix, p.matrix)


def test_empty_type_selection_keeps_the_separate_landing_layer():
    p = project(kind=[], show_landing_sites=True)
    selected = [f for f, _ in p.visible_features(CATALOG, (480, 640, 3))]
    assert selected and all(f['id'].startswith('landing:') for f in selected)


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.error = lambda exc: (_ for _ in ()).throw(AssertionError(str(exc)))
    image = np.full((480, 640, 3), 120, np.uint8)
    photo = tmp_path/'照片.png'
    Image.fromarray(image).save(photo)
    win.project = project(image_path=str(photo), labels={'crater': {'text': '保留名称', 'position': [30., 60.]}})
    win.catalog, win.catalog_by_id = CATALOG, {f['id']: f for f in CATALOG}
    win.set_image(image)
    win.sync_controls()
    win.refresh_annotations()
    win.workspace_tabs.setCurrentIndex(1)
    win.show()
    application.processEvents()
    yield win, application
    win.canvas._text_timer.stop()
    if win.canvas._text_cancel is not None:
        win.canvas._text_cancel.set()
    win.dirty = False
    win.close()


def test_collapsed_checkbox_filter_stages_multiple_types_and_preserves_edits(window, tmp_path, monkeypatch):
    win, application = window
    selector = win.kind
    assert not selector.toggle.isChecked() and selector.panel.isHidden()
    assert selector.all_checkbox.isChecked()
    assert all(not checkbox.isEnabled() for checkbox in selector.checks.values())
    items, labels = list(win.annotation_items), deepcopy(win.project.labels)
    QTest.mouseClick(selector.toggle, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert selector.panel.isVisible() and not win.style_pending
    with monkeypatch.context() as patch:
        patch.setattr(win, 'refresh_annotations', lambda: pytest.fail('Choosing types must leave the applied scene intact'))
        QTest.mouseClick(selector.all_checkbox, Qt.MouseButton.LeftButton,
                         pos=QPoint(8, selector.all_checkbox.height()//2))
        assert selector.selection() == []
        assert all(checkbox.isEnabled() for checkbox in selector.checks.values())
        for kind in ('Crater, craters', 'Mare, maria'):
            checkbox = selector.checks[kind]
            QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=QPoint(8, checkbox.height()//2))
        assert selector.selection() == ['Crater, craters', 'Mare, maria']
        assert win.style_pending and win.project.kind == '全部'
        assert win.annotation_items == items
        QTest.mouseClick(selector.toggle, Qt.MouseButton.LeftButton)
        assert selector.panel.isHidden() and '2' in selector.toggle.text()
    win.generate_labels_button.click()
    assert win.project.kind == ['Crater, craters', 'Mare, maria'] and not win.style_pending
    assert {item.feature['id'] for item in win.annotation_items} == {'crater', 'mare'}
    assert win.project.labels == labels
    assert next(item for item in win.annotation_items if item.feature['id'] == 'crater').pos().toTuple() == (30., 60.)
    path = tmp_path/'types.moonlabel'
    win.project.save(path)
    win.dirty = False
    win.open_project(path)
    assert selector.selection() == ['Crater, craters', 'Mare, maria']
    assert not selector.toggle.isChecked() and not win.style_pending
    assert win.project.labels == labels
    selector.all_checkbox.setChecked(True)
    assert selector.selection() == '全部'
    assert all(not checkbox.isEnabled() for checkbox in selector.checks.values())
    selector.all_checkbox.setChecked(False)
    assert selector.selection() == ['Crater, craters', 'Mare, maria']
    selector.checks['Crater, craters'].setChecked(False)
    selector.checks['Mare, maria'].setChecked(False)
    win.generate_labels_button.click()
    assert win.project.kind == [] and not win.annotation_items


@pytest.mark.parametrize('stored', ['全部', 'Crater, craters', 'Future type', ['Mare, maria', 'Crater, craters']])
def test_sync_preserves_legacy_and_unknown_filters_without_staging_changes(window, stored):
    win, _ = window
    win.project.kind = stored
    win.sync_controls()
    assert not win.style_pending
    assert win.annotation_settings()['kind'] == stored
    if isinstance(stored, str) and stored != '全部':
        assert win.kind.checks[stored].isChecked()
