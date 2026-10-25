# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned annotation actions and coherent staged/live settings."""
from copy import deepcopy
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, QThreadPool
from PySide6.QtWidgets import QApplication, QPushButton

from moonlabeler.app import MainWindow


@pytest.fixture
def window():
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.error = lambda exc: (_ for _ in ()).throw(AssertionError(str(exc)))
    win.open_project(str(Path(__file__).parents[1]/'examples/demo.moonlabel'))
    win.workspace_tabs.setCurrentIndex(1)
    win.show()
    application.processEvents()
    yield win, application
    win.canvas._text_timer.stop()
    if win.canvas._text_cancel is not None:
        win.canvas._text_cancel.set()
    assert QThreadPool.globalInstance().waitForDone(10000)
    application.processEvents()
    win.canvas._text_timer.stop()
    win.dirty = False
    win.close()


def test_regenerate_stays_above_the_scroll_area_and_applies_from_the_bottom(window):
    win, application = window
    win.resize(1100, 720)
    win.map_styles_toggle.setChecked(True)
    application.processEvents()
    button = win.generate_labels_button
    scroll = win.annotation_scroll
    assert win.workspace_tabs.widget(1).isAncestorOf(button)
    assert not scroll.widget().isAncestorOf(button)
    assert win.apply_map_styles_button is button
    assert len([b for b in win.sidebar.findChildren(QPushButton) if b.text() == button.text()]) == 1
    assert button.mapToGlobal(QPoint()).y()+button.height() <= win.overview_group.mapToGlobal(QPoint()).y()
    item = win.annotation_items[0]
    win.project.labels[item.feature['id']] = {'text': '手工地名', 'position': [120., 140.]}
    edits = deepcopy(win.project.labels)
    win.maximum.setValue(180)
    assert win.style_pending
    application.processEvents()
    top = button.mapToGlobal(QPoint())
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    application.processEvents()
    assert scroll.verticalScrollBar().value() > 0
    assert button.isVisible() and button.mapToGlobal(QPoint()) == top
    button.click()
    assert win.project.max_labels == 180 and not win.style_pending
    assert win.project.labels == edits


def test_reverting_pending_controls_preserves_precise_project_values(window):
    win, _ = window
    win.project.font_percent = 1.812345
    win.project.font_step_percent = .312345
    win.project.grid_opacity = .454321
    win.sync_controls()
    font = win.font_size.value()
    win.font_size.setValue(2.4)
    assert win.style_pending
    win.font_size.setValue(font)
    assert not win.style_pending
    win.apply_label_settings()
    assert win.project.font_percent == 1.812345
    assert win.project.font_step_percent == .312345
    assert win.project.grid_opacity == .454321


@pytest.mark.parametrize('change', ['style', 'grid'])
def test_pending_map_configuration_does_not_live_edit_the_applied_map(window, monkeypatch, change):
    win, _ = window
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(15))
    win.apply_label_settings()
    items, labels = list(win.map_items), list(win.annotation_items)
    opacity = win.project.grid_opacity
    coverage = win.project.map_light_mask
    if change == 'style':
        win.art_style.setCurrentIndex(win.art_style.findData('redalert'))
    else:
        win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(30))
    monkeypatch.setattr(win, 'refresh_annotations', lambda: pytest.fail('Pending controls must leave the applied scene intact'))
    monkeypatch.setattr(win, 'refresh_map_coverage', lambda: pytest.fail('Pending maps must not alter applied coverage'))
    win.grid_opacity.setValue(81)
    win.map_light_toggle.setChecked(not coverage)
    win.map_light_threshold.setValue(51)
    assert win.project.grid_opacity == opacity and win.project.map_light_mask == coverage
    assert win.map_items == items and win.annotation_items == labels
    assert win.style_pending


def test_inapplicable_controls_are_disabled_and_restore_their_values(window):
    win, _ = window
    step, outlines = win.ui_font_step.value(), win.crater_outlines.isChecked()
    assert win.generate_labels_button.isEnabled()
    assert not win.map_light_toggle.isEnabled() and not win.map_light_threshold.isEnabled()
    win.art_style.setCurrentIndex(win.art_style.findData('manuscript'))
    for control in (win.ui_font_step, win.font_weight, win.color_button,
                    win.crater_outlines, win.crater_outline_shape):
        assert not control.isEnabled()
    assert win.font_pixels_hint.isHidden() and win.map_light_threshold.isEnabled()
    win.art_style.setCurrentIndex(win.art_style.findData('standard'))
    assert win.ui_font_step.isEnabled() and win.crater_outlines.isEnabled()
    assert win.ui_font_step.value() == step and win.crater_outlines.isChecked() == outlines
    assert not win.font_pixels_hint.isHidden()
    win.crater_outlines.setChecked(False)
    assert not win.crater_outline_shape.isEnabled()
    matrix = win.project.matrix
    win.project.matrix = None
    win.refresh_photo_overview()
    assert not win.generate_labels_button.isEnabled()
    win.project.matrix = matrix
    win.refresh_photo_overview()
    assert win.generate_labels_button.isEnabled()


def test_reflow_does_not_apply_staged_settings_or_clear_other_manual_edits(window):
    win, _ = window
    feature_id = win.annotation_items[0].feature['id']
    win.project.labels[feature_id] = {'text': '保留名称', 'position': [120., 140.], 'hidden': True}
    font, count = win.project.font_percent, win.project.max_labels
    win.font_size.setValue(2.4)
    win.maximum.setValue(180)
    win.reflow_labels()
    assert win.project.labels[feature_id] == {'text': '保留名称', 'hidden': True}
    assert win.project.font_percent == font and win.project.max_labels == count
    assert win.style_pending and win.settings_status.isVisible() and win.dirty
