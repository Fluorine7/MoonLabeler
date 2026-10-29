# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Shared live text opacity, project compatibility, and real PNG/SVG output."""
import json
import os
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow, Annotation
from moonlabeler.annotation_style import ART_STYLES
from moonlabeler.geometry import Geometry
from moonlabeler.project import Project, export_svg


@pytest.mark.parametrize('style', ART_STYLES)
def test_live_opacity_preserves_layout_and_exports(tmp_path, monkeypatch, style):
    app = QApplication.instance() or QApplication([])
    from moonlabeler import app as app_module
    monkeypatch.setattr(app_module, 'CACHE', tmp_path)
    win = MainWindow()
    p = win.project
    p.art_style, p.crater_outlines = style, False
    p.font_percent, p.font_step_percent = 6., 0.
    p.geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                          np.array([1., 0, 0]), 384400., '2025-05-03T11:36:00+00:00')
    p.matrix = np.array([[180., 0, 320.], [0, 180., 200.]])
    p.labels['test'] = {'text': 'LUNA', 'position': [280., 180.]}
    image = np.full((400, 640, 3), 80, np.uint8)
    win.set_image(image)
    win.sync_controls()
    feature = {'id': 'test', 'name': 'LUNA', 'kind': 'Mare, maria', 'diameter': 800., 'lat': 0., 'lon': 0.}
    label = Annotation(feature, [160., 240.], 'LUNA', p, win.move_label, win.edit_label, font_size=24)
    label.setParentItem(win.annotation_group)
    label.line.setParentItem(win.annotation_group)
    label.setPos(280., 180.)
    win.annotation_items = [label]
    try:
        pixels = {}
        for value in (100, 35, 0):
            revision, path, photo = label._text_revision, label.path, win.photo_item.pixmap().cacheKey()
            win.label_opacity.setValue(value)
            assert p.label_opacity == value/100 and label.opacity() == value/100
            assert label.line.opacity() == 1 and label._text_revision == revision and label.path == path
            assert win.photo_item.pixmap().cacheKey() == photo
            assert p.labels['test'] == {'text': 'LUNA', 'position': [280., 180.]}
            png, svg = tmp_path/f'{value}.png', tmp_path/f'{value}.svg'
            win.render_png(png)
            export_svg(svg, image, win.annotation_entries(), p, win.annotation_leaders())
            pixels[value] = np.asarray(Image.open(png).convert('RGB')).astype(float)
            root = ET.parse(svg)
            group = root.find('.//{http://www.w3.org/2000/svg}g[@class="caption"]')
            assert float(group.attrib['opacity']) == value/100
            assert root.find('.//{http://www.w3.org/2000/svg}text') is not None
        strength = lambda value: np.abs(pixels[value]-pixels[0]).sum()
        assert strength(100) > 1000
        assert .2 < strength(35)/strength(100) < .65
        win.label_opacity.setValue(35)
        saved = tmp_path/'opacity.moonlabel'
        p.save(saved)
        loaded = Project.load(saved)
        assert loaded.label_opacity == .35 and loaded.labels == p.labels
        loaded.art_style = 'standard' if style != 'standard' else 'manuscript'
        assert Annotation(feature, [160., 240.], 'LUNA', loaded, lambda *a: None, lambda *a: None).opacity() == .35
    finally:
        win.dirty = False
        win.close()


def test_old_projects_default_to_opaque_and_reject_invalid_opacity(tmp_path):
    path = tmp_path/'old.moonlabel'
    Project().save(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['style'].pop('label_opacity')
    path.write_text(json.dumps(data), encoding='utf-8')
    assert Project.load(path).label_opacity == 1.
    for invalid in (-.1, 1.1, '0.5', True, float('nan')):
        data['style']['label_opacity'] = invalid
        path.write_text(json.dumps(data), encoding='utf-8')
        with pytest.raises(ValueError, match='label_opacity'):
            Project.load(path)
