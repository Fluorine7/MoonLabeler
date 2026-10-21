# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional geographic layer: visibility, persistence, and screen/export parity."""
import json
import os
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QGraphicsLineItem
from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry
from moonlabeler.landing_sites import landing_sites, is_landing_site, DEFAULT_LANDING_COLOR
from moonlabeler.project import Project, export_svg

SHAPE = (2000, 2000, 3)
NEAR_IDS = {f'landing:apollo-{n}' for n in (11, 12, 14, 15, 16, 17)} | {'landing:change-3', 'landing:change-5'}


def calibrated():
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400., '2026-10-10T15:00:00+00:00')
    return Project(geometry=geometry, matrix=np.array([[700., 0, 1000.], [0, 700., 1000.]]),
                   min_diameter=3000, kind='Crater, craters', illuminated_only=False)


def test_opt_in_layer_ignores_terrain_filters_but_respects_projection():
    project = calibrated()
    # The terrain catalogue remains independent of the optional layer.
    catalog = [dict(id='terrain', name='Crater', kind='Crater, craters', diameter=10., lat=0., lon=0.)]
    assert project.visible_features(catalog, SHAPE) == []
    project.show_landing_sites = True
    visible = project.visible_features(catalog, SHAPE)
    assert {f['id'] for f, xy in visible} == NEAR_IDS
    assert len(catalog) == 1
    assert all(project.crater_outline(f, SHAPE) == [] for f, xy in visible)
    # Reflections and camera offsets use the same registration as terrain.
    project.matrix[0, 0] *= -1
    reflected = {f['id']: xy for f, xy in project.visible_features(catalog, SHAPE)}
    for f, xy in visible:
        np.testing.assert_allclose(reflected[f['id']], [2000-xy[0], xy[1]])
    project.matrix[:, 2] += 4000
    assert not project.visible_features(catalog, SHAPE)
    assert not Project(show_landing_sites=True).visible_features(catalog, SHAPE)


def test_lighting_and_small_tier_apply_to_sites():
    project = calibrated()
    project.show_landing_sites = True
    project.illuminated_only = True
    dark = np.zeros(SHAPE, np.uint8)
    assert not project.visible_features([], SHAPE, image=dark)
    assert len(project.visible_features([], SHAPE, image=dark+160)) == 8
    project.update_font_size(SHAPE)
    assert set(project.label_font_sizes(landing_sites(), SHAPE).values()) == {24}
    project.font_step_percent = 0
    assert set(project.label_font_sizes(landing_sites(), SHAPE).values()) == {36}
    assert project.label_color(landing_sites()[0]) == DEFAULT_LANDING_COLOR != project.color
    assert project.label_color({'kind': 'Crater, craters'}) == project.color


def test_data_and_project_roundtrip_are_independent(tmp_path):
    sites = landing_sites()
    assert len(sites) == len({s['id'] for s in sites}) == 10
    assert all(-90 <= s['lat'] <= 90 and -180 <= s['lon'] <= 180 for s in sites)
    assert all(s['source'].startswith('https://nssdc.gsfc.nasa.gov/') for s in sites)
    sites[0]['lat'] = 80
    assert landing_sites()[0]['lat'] == .67416  # Callers cannot alter the shared data.
    project = calibrated()
    project.image_path = str(tmp_path/'photo.png')
    project.show_landing_sites = True
    project.landing_color = '#88ffee'
    project.labels['landing:apollo-11'] = {'hidden': True, 'position': [100, 200], 'text': 'Apollo'}
    path = tmp_path/'sites.moonlabel'
    project.save(path)
    loaded = Project.load(path)
    assert loaded.show_landing_sites and loaded.landing_color == '#88ffee'
    assert loaded.labels == project.labels
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ('show_landing_sites', 'landing_color'):
        del data['style'][key]
    path.write_text(json.dumps(data), encoding="utf-8")
    old = Project.load(path)
    assert not old.show_landing_sites and old.landing_color == DEFAULT_LANDING_COLOR
    for key, value in (('show_landing_sites', 'yes'), ('landing_color', 'not-a-color')):
        invalid = json.loads(json.dumps(data))
        invalid['style'][key] = value
        path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError, match=key):
            Project.load(path)


def test_deferred_gui_setting_and_png_svg_contract(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        # Settings are safe to apply even before the first photo.
        window.apply_label_settings()
        window.project = calibrated()
        window.catalog = []
        window.catalog_by_id = {}
        window.set_image(np.zeros(SHAPE, np.uint8))
        window.sync_controls()
        original_matrix = window.project.matrix.copy()
        assert not window.annotation_items and not window.landing_sites_toggle.isChecked()
        window.landing_sites_toggle.setChecked(True)
        assert window.style_pending and not window.project.show_landing_sites
        assert not window.annotation_items and window.landing_color_button.isEnabled()
        window.apply_label_settings()
        assert len(window.annotation_items) == 8
        for item in window.annotation_items:
            assert is_landing_site(item.feature) and item.font.pixelSize() == 24
            assert item.color == DEFAULT_LANDING_COLOR and not item.outline_segments
            assert len(item.line.childItems()) == 2
            assert all(isinstance(child, QGraphicsLineItem) for child in item.line.childItems())
        np.testing.assert_array_equal(window.project.matrix, original_matrix)
        png, svg = tmp_path/'sites.png', tmp_path/'sites.svg'
        window.render_png(png)
        pixels = np.asarray(Image.open(png))
        assert np.any(np.all(pixels[:, :, :3] == [121, 217, 239], axis=2)), 'PNG lost landing color'
        export_svg(svg, window.image, window.annotation_entries(), window.project, window.annotation_leaders())
        root = ET.parse(svg)
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        captions = root.findall('.//svg:text', ns)
        assert len(captions) == 8
        assert all(n.attrib['font-size'] == '24' and n.attrib['fill'] == DEFAULT_LANDING_COLOR for n in captions)
        assert len(root.findall('.//svg:path[@class="landing-marker"]', ns)) == 8
        assert not root.findall('.//svg:path[@class="crater-outline"]', ns)
        window.landing_sites_toggle.setChecked(False)
        assert len(window.annotation_items) == 8  # Export still reflects the applied state.
        window.apply_label_settings()
        assert not window.annotation_items
    finally:
        window.dirty = False
        window.close()
