# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""The displayed leader must use the same surface as the crater outline."""
from types import SimpleNamespace
import json
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest

from moonlabeler.geometry import Geometry
from moonlabeler.project import Project
from moonlabeler.annotation_relief import prepare_annotation_relief, catalogue_rim


def geometry():
    return Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                    np.array([0., 0., 1.]), np.array([1., 0., 0.]),
                    384400., '2025-09-14T15:05:59+00:00')


def feature(kind='Crater, craters', diameter=80., lon=60.):
    return dict(id='probe', name='Probe', lat=0., lon=lon, diameter=diameter, kind=kind)


def project(f):
    p = Project(geometry=geometry(), matrix=np.array([[3000., 0., 1000.], [0., 3000., 1800.]]),
                illuminated_only=False, min_diameter=0.)
    p.annotation_relief = {'source': 'Controlled DEM', 'resolution_km': 1.,
                           'points': {f['id']: [f['lat'], f['lon'], 3.]}, 'rims': {}}
    return p


@pytest.mark.parametrize('kind', ['Rupes, rupēs', 'Rima, rimae', 'Crater, craters'])
def test_displayed_point_uses_saved_height(kind):
    f = feature(kind, diameter=20.)
    p = project(f)
    before = p.photo_points(p.geometry.project([f['lat']], [f['lon']])[0])[0]
    expected = p.photo_points(p.geometry.project([f['lat']], [f['lon']], [3.])[0])[0]
    displayed = p.visible_features([f], (3600, 4200))[0][1]
    assert np.linalg.norm(expected-before) > 4.
    assert np.allclose(displayed, expected, atol=1e-8)


def test_large_crater_leader_meets_the_height_corrected_ellipse_centre():
    f = feature(diameter=180.)
    p = project(f)
    # Generate an independent, closed 3-D ring with a raised rim.
    alpha = np.radians(np.linspace(0., 360., 129))
    angular_radius = f['diameter']/(2*1737.4)
    c = np.array([.5, np.sqrt(3)/2, 0.])
    east, north = np.array([-np.sqrt(3)/2, .5, 0.]), np.array([0., 0., 1.])
    v = np.cos(angular_radius)*c + np.sin(angular_radius)*(np.cos(alpha)[:, None]*east + np.sin(alpha)[:, None]*north)
    coords = np.column_stack((np.degrees(np.arcsin(v[:, 2])),
                              np.degrees(np.arctan2(v[:, 1], v[:, 0])), np.full(len(v), 5.)))
    p.terrain_rims = {f['id']: {'coordinates': coords.tolist(), 'source': 'Controlled rim', 'resolution_km': 1.}}
    raw, visible = p._project_crater_rim(f)
    assert visible.all()
    expected = cv2.fitEllipse(raw[:-1].astype(np.float32))[0]
    displayed = p.visible_features([f], (3600, 4200))[0][1]
    assert np.linalg.norm(displayed-expected) < .002
    assert p.crater_outline(f, (3600, 4200))


def test_changed_catalogue_coordinate_does_not_reuse_old_height():
    f = feature(diameter=20.)
    p = project(f)
    f = f | {'lon': 50.}
    expected = p.photo_points(p.geometry.project([f['lat']], [f['lon']])[0])[0]
    assert np.allclose(p.visible_features([f], (3600, 4200))[0][1], expected)


def test_partial_limb_rim_does_not_recentre_marker_on_visible_fragment():
    f = feature(diameter=180., lon=88.)
    p = project(f)
    ring = catalogue_rim(f)
    p.terrain_rims = {f['id']: {'coordinates': np.column_stack((ring, np.full(len(ring), 5.))).tolist()}}
    assert not p._project_crater_rim(f)[1].all()
    expected = p.photo_points(p.geometry.project([0.], [88.], [3.])[0])[0]
    assert np.allclose(p.annotation_points([f])[0][0], expected)


@pytest.mark.parametrize('mirror', [False, True])
def test_height_correction_passes_through_camera_and_afocal_distortion(mirror):
    f = feature(diameter=20.)
    p = project(f)
    if mirror:
        p.matrix[0, 0] *= -1
        p.matrix[0, 2] = 4000.
    p.identification['lens_distortion'] = {'center': [2100., 1800.], 'scale': 4000., 'k': .05}
    expected = p.photo_points(p.geometry.project([0.], [60.], [3.])[0])[0]
    assert np.allclose(p.annotation_points([f])[0][0], expected)


def test_sampling_batches_local_dem_and_saves_heights_after_close(monkeypatch, tmp_path):
    from moonlabeler import annotation_relief as module
    path = tmp_path/'local.lbl'
    path.touch()
    calls = []
    def sample(lat, lon):
        calls.append(len(lat))
        return np.full(len(lat), 3.)
    dem = SimpleNamespace(sample=sample, resolution_km=1., name='Local test DEM', close=lambda: calls.append('closed'))
    monkeypatch.setattr(module.ElevationMap, 'load', lambda path: dem)
    f = feature(diameter=180.)
    p = project(f)
    relief = prepare_annotation_relief([f], p.geometry, p.matrix, (3600, 4200), tmp_path, dem_path=str(path))
    assert calls[-1] == 'closed' and len(calls) == 3
    assert relief['points'][f['id']] == [0., 60., 3.]
    assert len(relief['rims'][f['id']]['coordinates']) == 97
    p.annotation_relief = relief
    # Repeated display and SVG export operate on the snapshot, not the map.
    monkeypatch.setattr(module.ElevationMap, 'load', lambda path: pytest.fail('Reopened DEM while drawing'))
    before = p.annotation_points([f])[0]
    p.image_path = str(tmp_path/'photo.png')
    saved = tmp_path/'saved.moonlabel'
    p.save(saved)
    restored = Project.load(saved)
    assert restored.annotation_relief == relief
    assert np.allclose(restored.annotation_points([f])[0], before)
    assert np.allclose(restored._project_crater_rim(f)[0], p._project_crater_rim(f)[0])
    from moonlabeler.project import export_svg
    svg = tmp_path/'saved.svg'
    export_svg(svg, np.zeros((20, 20, 3), np.uint8), [(f, before[0], [10., 10.])], restored)
    tree = ET.parse(svg)
    leader = tree.find('.//{http://www.w3.org/2000/svg}path')
    assert leader is not None


def test_unavailable_or_invalid_dem_keeps_sphere_without_download(monkeypatch, tmp_path):
    from moonlabeler import annotation_relief as module
    f = feature()
    p = project(f)
    def invalid(path):
        raise ValueError('not a supported Moon map')
    monkeypatch.setattr(module.ElevationMap, 'load', invalid)
    local = tmp_path/'invalid.lbl'
    local.touch()
    assert prepare_annotation_relief([f], p.geometry, p.matrix, (3600, 4200), tmp_path, dem_path=str(local)) == {}


@pytest.mark.parametrize('height', [float('nan'), 16., '3', True])
def test_saved_invalid_height_is_rejected_before_display(tmp_path, height):
    f = feature()
    p = project(f)
    p.image_path = str(tmp_path/'photo.png')
    path = tmp_path/'bad.moonlabel'
    p.save(path)
    data = json.loads(path.read_text())
    data['annotation_relief']['points'][f['id']][2] = height
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='工程'):
        Project.load(path)


def test_legacy_project_without_snapshot_keeps_original_sphere(tmp_path):
    f = feature(diameter=20.)
    p = project(f)
    p.image_path = str(tmp_path/'photo.png')
    path = tmp_path/'legacy.moonlabel'
    p.save(path)
    data = json.loads(path.read_text())
    data.pop('annotation_relief')
    path.write_text(json.dumps(data))
    restored = Project.load(path)
    assert not restored.annotation_relief
    expected = restored.photo_points(restored.geometry.project([0.], [60.])[0])
    assert np.allclose(restored.annotation_points([f])[0], expected)


def test_gui_reuses_snapshot_for_regeneration_and_saved_project(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from PIL import Image
    from moonlabeler import app as module
    application = QApplication.instance() or QApplication([])
    window = module.MainWindow()
    f = feature(diameter=20., lon=15.)
    photo = tmp_path/'photo.png'
    Image.new('RGB', (400, 400)).save(photo)
    p = project(f)
    p.annotation_relief = {}
    p.matrix = np.array([[120., 0., 200.], [0., 120., 200.]])
    p.image_path = str(photo)
    calls = []
    relief = {'source': 'Saved local DEM', 'resolution_km': 1., 'points': {f['id']: [0., 15., 3.]}, 'rims': {}}
    def prepare(*args, **kwargs):
        calls.append('sample')
        return relief.copy()
    monkeypatch.setattr(module, 'prepare_annotation_relief', prepare)
    try:
        window.project, window.image = p, np.zeros((400, 400, 3), np.uint8)
        window.catalog = [f]
        window.catalog_by_id = {f['id']: f}
        window.refresh_annotations()
        window.refresh_annotations()
        assert calls == ['sample']
        saved = tmp_path/'photo.moonlabel'
        p.save(saved)
        window.open_project(str(saved))
        assert calls == ['sample']
        assert window.project.annotation_relief == relief
        assert np.allclose(window.project.matrix, p.matrix)
        # A fresh calibration may produce the exact same matrix; it must still
        # be allowed to rebuild a deliberately invalidated snapshot.
        window.project.annotation_relief.clear()
        window.refresh_annotations()
        assert calls == ['sample', 'sample']
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('mirror', [False, True])
def test_manual_fit_and_display_use_the_same_height_surface(monkeypatch, mirror):
    from PySide6.QtWidgets import QApplication
    from moonlabeler import app as module
    application = QApplication.instance() or QApplication([])
    window = module.MainWindow()
    catalog = [feature(diameter=20., lon=lon) | {'id': str(i), 'lat': lat}
               for i, (lat, lon) in enumerate([(0., 0.), (10., 15.), (-10., 15.)])]
    relief = {'source': 'Controlled DEM', 'resolution_km': 1.,
              'points': {f['id']: [f['lat'], f['lon'], 3.] for f in catalog}, 'rims': {}}
    g = geometry()
    actual_matrix = np.array([[1000., 0., 400.], [0., 1000., 400.]])
    if mirror:
        actual_matrix[0, 0] *= -1
    observed = g.project([f['lat'] for f in catalog], [f['lon'] for f in catalog], [3.]*3)[0]
    observed = observed @ actual_matrix[:, :2].T+actual_matrix[:, 2]
    monkeypatch.setattr(module, 'prepare_annotation_relief', lambda *args, **kwargs: relief.copy())
    errors = []
    window.error = errors.append
    try:
        window.image = np.zeros((800, 800, 3), np.uint8)
        window.catalog, window.catalog_by_id = catalog, {f['id']: f for f in catalog}
        window.project = Project(geometry=g, anchors=[{'id': f['id'], 'pixel': pixel.tolist()}
                                                    for f, pixel in zip(catalog, observed)])
        window.solve_manual()
        assert not errors
        assert np.max(np.linalg.norm(window.project.annotation_points(catalog)[0]-observed, axis=1)) < .01
        assert np.allclose(window.project.matrix, actual_matrix, atol=.01)
        assert max(float(window.anchor_table.item(i, 2).text()) for i in range(3)) < .01
    finally:
        window.dirty = False
        window.close()
