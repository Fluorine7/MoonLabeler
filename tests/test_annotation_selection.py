# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Selection regressions: visible formations, final quota and manual edits."""
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry
from moonlabeler.layout import LabelBox, arrange_labels, rect_intersects
from moonlabeler.project import Project
from moonlabeler.registration import transform_points
from moonlabeler.sources import read_image


def face_on_project(**kwargs):
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400, '2026-10-01T15:00:00+00:00')
    return Project(geometry=geometry, matrix=np.array([[1000., 0, 250.], [0, 1000., 350.]]),
                   min_diameter=0, **kwargs)


def crater(fid, name, lon, diameter, lat=0):
    return dict(id=fid, name=name, lat=lat, lon=lon, diameter=diameter, kind='Crater, craters')


def test_clear_moderate_crater_precedes_large_low_contrast_floor():
    project = face_on_project(max_labels=1)
    catalog = [crater('flat', 'Flooded', 0, 200), crater('clear', 'Distinct', 14, 40)]
    image = np.full((700, 700, 3), 100, np.uint8)
    points, _, _ = project.geometry.project([f['lat'] for f in catalog], [f['lon'] for f in catalog])
    center = tuple(np.rint(transform_points(project.matrix, points)[1]).astype(int))
    cv2.circle(image, center, 10, (25, 25, 25), -1)
    cv2.circle(image, center, 12, (210, 210, 210), 3)
    chosen = project.visible_features(catalog, image.shape, image=image)
    assert [f['id'] for f, xy in chosen] == ['clear']


def test_selection_uses_more_than_one_photo_region():
    project = face_on_project(max_labels=3, illuminated_only=False)
    catalog = [crater(str(i), f'Formation {i}', -7+i*.2, 100-i, lat=3) for i in range(7)]
    catalog.append(crater('other', 'Isolated', 20, 50, lat=-10))
    selected = project.visible_features(catalog, (700, 700, 3))
    assert 'other' in {f['id'] for f, xy in selected}


def test_named_terrain_precedes_satellites_but_explicit_selection_takes_priority():
    project = face_on_project(max_labels=2)
    satellite = crater('satellite', 'Formation A', 0, 200)
    main = crater('main', 'Formation', 8, 40)
    cliff = dict(crater('cliff', 'Rupes Example', 15, 20), kind='Rupes, rupēs')
    selected = project.visible_features([satellite, main, cliff], (700, 700, 3))
    assert {f['id'] for f, xy in selected} == {'main', 'cliff'}
    project.labels['satellite'] = {'force': True}
    selected = project.visible_features([satellite, main, cliff], (700, 700, 3))
    assert selected[0][0]['id'] == 'satellite'


def test_layout_refills_rejections_and_stops_at_rendered_limit():
    requests = [LabelBox('too-wide', (100, 60), 900, 24),
                LabelBox('one', (150, 100), 70, 24),
                LabelBox('two', (350, 250), 70, 24),
                LabelBox('reserve', (520, 350), 70, 24)]
    visited = []
    def candidates():
        for request in requests:
            visited.append(request.key)
            yield request
    placed, omitted = arrange_labels(candidates(), 700, 450, max_labels=2)
    assert set(placed) == {'one', 'two'}
    assert omitted == {'too-wide'}
    assert visited == ['too-wide', 'one', 'two'], 'Layout eagerly consumed unused reserve candidates'
    assert not rect_intersects(*placed.values())


def test_budget_preserves_pinned_caption_and_ignores_unused_reserve_center():
    pinned = LabelBox('manual', (100, 100), 80, 24, fixed=(130, 80))
    automatic = LabelBox('auto', (350, 250), 70, 24)
    unused = LabelBox('unused', (170, 90), 70, 24)
    placed, omitted = arrange_labels([pinned, automatic, unused], 600, 400, max_labels=2)
    assert set(placed) == {'manual', 'auto'} and not omitted
    assert placed['manual'] == (130, 80, 80, 24)


def test_hidden_labels_do_not_spend_display_quota(monkeypatch):
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.image = np.full((600, 800, 3), 100, np.uint8)
        window.project = face_on_project(max_labels=2, crater_outlines=False, font_size=18)
        window.project.labels = {'hidden': {'hidden': True}, 'pinned': {'position': [100., 100.], 'force': True}}
        features = [crater(fid, fid, 0, 30) for fid in ('hidden', 'pinned', 'auto', 'extra')]
        entries = list(zip(features, ((100., 100.), (200., 200.), (400., 400.), (650., 450.))))
        monkeypatch.setattr(window.project, 'visible_features', lambda *args, **kwargs: entries)
        window.refresh_annotations()
        assert {item.feature['id'] for item in window.annotation_items} == {'pinned', 'auto'}
        assert window.project.labels['pinned']['position'] == [100., 100.]
        assert window.names.count() == 3  # Hidden label remains available for re-enabling.
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('maximum,step', [(1.5, 0.), (1.8, .3)])
def test_full_moon_prominent_craters_survive_selection_and_layout(maximum, step):
    source = Path(__file__).parents[1]
    photo = source/'1001.jpg'
    if not photo.exists():
        pytest.skip("User's full-Moon photograph is unavailable")
    pose = json.loads((Path(__file__).parent/'fixtures/1001-registration.json').read_text())
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.image = read_image(photo)
        window.project = Project(geometry=Geometry.from_dict(pose['geometry']), matrix=np.array(pose['matrix']),
                                 min_diameter=6.65, max_labels=200, font_percent=maximum, font_step_percent=step)
        window.project.update_font_size(window.image.shape)
        window.refresh_annotations()
        rendered = {item.feature['name'] for item in window.annotation_items}
        assert {'Autolycus', 'Timocharis', 'Pytheas', 'Manilius'} <= rendered
        assert len(rendered) <= 200
    finally:
        window.dirty = False
        window.close()
