# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Projected typography, legacy styles, and the scene/export contract."""
import json
import os
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry, MOON_RADIUS_KM
from moonlabeler.project import Project, export_svg


def project_and_features():
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400., '2026-10-10T15:00:00+00:00')
    # At the disk center, one physical kilometer projects to about one pixel.
    project = Project(geometry=geometry, matrix=np.array([[MOON_RADIUS_KM, 0, 1000.],
                                                        [0, MOON_RADIUS_KM, 1000.]]),
                      min_diameter=0, crater_outlines=False, illuminated_only=False)
    features = [dict(id=name, name=name, diameter=diameter, lat=0., lon=longitude,
                     kind='Crater, craters') for name, diameter, longitude in
                (('Large', 100., -15.), ('Medium', 25., 0.), ('Small', 8., 15.))]
    return project, features


def test_projected_three_tiers_survive_resize_rotation_and_mirror():
    project, features = project_and_features()
    project.update_font_size((2000, 2000, 3))
    assert project.label_font_sizes(features, (2000, 2000, 3)) == dict(Large=36, Medium=30, Small=24)
    assert project.label_font_sizes(features[1:], (2000, 2000, 3)) == dict(Medium=30, Small=24)
    # Rotate and reflect the camera, then resize the same photo by two.
    project.matrix[:, :2] = 2*np.array([[0., -1.], [-1., 0.]]) @ project.matrix[:, :2]
    project.matrix[:, 2] *= 2
    project.update_font_size((4000, 4000, 3))
    assert project.label_font_sizes(features, (4000, 4000, 3)) == dict(Large=72, Medium=60, Small=48)


def test_equal_physical_craters_use_smaller_text_at_the_limb():
    project, _ = project_and_features()
    features = [dict(id=str(lon), name=str(lon), diameter=50., lat=0., lon=lon)
                for lon in (0., 80., 89.4)]
    project.update_font_size((2000, 2000, 3))
    assert list(project.label_font_sizes(features, (2000, 2000, 3)).values()) == [36, 30, 24]


def test_tiers_persist_and_pre_tier_projects_remain_uniform(tmp_path):
    project, features = project_and_features()
    project.image_path = str(tmp_path/'photo.png')
    project.update_font_size((2000, 2000, 3))
    path = tmp_path/'photo.moonlabel'
    project.save(path)
    loaded = Project.load(path)
    assert loaded.font_percent == 1.8 and loaded.font_step_percent == .3
    assert loaded.label_font_sizes(features, (2000, 2000, 3)) == dict(Large=36, Medium=30, Small=24)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data['style']['font_step_percent']
    path.write_text(json.dumps(data), encoding="utf-8")
    legacy = Project.load(path)
    assert legacy.font_step_percent == 0
    assert set(legacy.label_font_sizes(features, (2000, 2000, 3)).values()) == {36}


def test_large_decrement_retains_readable_positive_fonts():
    project, features = project_and_features()
    project.font_percent = .6
    project.font_step_percent = 1.
    project.update_font_size((2000, 2000, 3))
    assert project.label_font_sizes(features, (2000, 2000, 3)) == dict(Large=12, Medium=6, Small=6)


def test_scene_collision_bounds_and_png_svg_share_each_tier(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.project, features = project_and_features()
        window.catalog = features
        window.catalog_by_id = {f['id']: f for f in features}
        window.set_image(np.zeros((2000, 2000, 3), np.uint8))
        window.sync_controls()
        items = {item.feature['id']: item for item in window.annotation_items}
        assert {key: item.font.pixelSize() for key, item in items.items()} == dict(Large=36, Medium=30, Small=24)
        bounds = [item.sceneBoundingRect() for item in items.values()]
        assert all(not a.intersects(b) for i, a in enumerate(bounds) for b in bounds[i+1:])
        png = tmp_path/'tiers.png'
        window.render_png(png)
        with Image.open(png) as image:
            assert image.size == (2000, 2000)
            for item in items.values():
                rect = item.sceneBoundingRect()
                crop = np.asarray(image.crop((int(rect.left()), int(rect.top()),
                                              int(np.ceil(rect.right())), int(np.ceil(rect.bottom())))))
                assert np.any(np.all(crop[:, :, :3] > 220, axis=2)), 'PNG lost a tier caption'
        svg = tmp_path/'tiers.svg'
        export_svg(svg, window.image, window.annotation_entries(), window.project, window.annotation_leaders())
        text_nodes = ET.parse(svg).findall('.//{http://www.w3.org/2000/svg}text')
        for node in text_nodes:
            item = items[node.text]
            assert int(node.attrib['font-size']) == item.font.pixelSize()
            assert abs(float(node.attrib['y'])-item.pos().y()-item.font_size) < .001
        assert len(text_nodes) == 3
    finally:
        window.dirty = False
        window.close()
