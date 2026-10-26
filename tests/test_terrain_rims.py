# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from types import SimpleNamespace
from copy import deepcopy
import threading
import time
import xml.etree.ElementTree as ET
import cv2
import numpy as np
import pytest
from PIL import Image
from moonlabeler.geometry import Geometry, MOON_RADIUS_KM, surface_vectors
from moonlabeler.terrain_rims import trace_crater_rim
from moonlabeler.project import Project, export_svg


@pytest.mark.parametrize('broken', [False, True])
def test_unavailable_crests_show_reference_status_and_cache_the_failed_attempt(tmp_path, monkeypatch, broken):
    from PySide6.QtWidgets import QApplication
    from moonlabeler import app as module
    application = QApplication.instance() or QApplication([])
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400., 'test')
    feature = dict(id='flat', name='Flat', lat=0., lon=0., diameter=80., kind='Crater, craters')
    source = tmp_path/'flat.npz'
    if broken:
        source.write_bytes(b'not a DEM')
    else:
        np.savez(source, height_km=np.zeros((180, 360), np.float32), north=90., west=-180., pixels_per_degree=1.)
    window = module.MainWindow()
    window.project = Project(geometry=geometry, matrix=np.array([[5000., 0, 300], [0, -5000., 300]]),
                             min_diameter=0, font_percent=.5, illuminated_only=False, optimize_layout=False)
    window.catalog, window.catalog_by_id = [feature], {'flat': feature}
    window.set_image(np.full((600, 600, 3), 70, np.uint8))
    window.dem_path = str(source)
    window.sync_controls()
    calls, original = [], module.prepare_project_rims
    def prepare(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(module, 'prepare_project_rims', prepare)
    try:
        window.crater_outline_shape.setCurrentIndex(window.crater_outline_shape.findData('terrain'))
        window.apply_label_settings()
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            application.processEvents()
            if not window.busy and not window._outlines_pending and '参考圈' in window.outline_status.text():
                break
            time.sleep(.005)
        assert not window.busy and not window.project.terrain_rims
        assert not window.outline_status.isHidden() and '参考圈' in window.outline_status.text()
        assert len(calls) == 1
        for _ in range(3):
            window.refresh_annotations()
        window.font_size.setValue(.65)
        window.apply_label_settings()
        assert len(calls) == 1 and not window.busy
    finally:
        window.dirty = False
        window.close()


def test_selecting_hand_drawn_outlines_traces_missing_rims_in_the_background(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from moonlabeler import app as module
    from moonlabeler import terrain_rims
    application = QApplication.instance() or QApplication([])
    north, west, ppd = 4., -4., 40.
    lat, lon = np.meshgrid(north-(np.arange(320)+.5)/ppd,
                          west+(np.arange(320)+.5)/ppd, indexing='ij')
    vectors = surface_vectors(lat.ravel(), lon.ravel())
    distance = np.arccos(np.clip(vectors[:, 0], -1, 1))*MOON_RADIUS_KM
    angle = np.arctan2(vectors[:, 1], vectors[:, 2])
    ridge = 40*(1+.08*np.cos(3*angle))
    heights = 2*np.exp(-((distance-ridge)/3)**2)-2/(1+np.exp(np.clip((distance-ridge+5)/2, -100, 100)))
    source = tmp_path/'不规则坑缘.npz'
    np.savez(source, height_km=heights.reshape(lat.shape).astype(np.float32),
             north=north, west=west, pixels_per_degree=ppd)
    feature = dict(id='crest', name='Crest', lat=0., lon=0., diameter=80., kind='Crater, craters')
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400., 'test')
    photo = tmp_path/'月面照片.png'
    rgb = np.full((600, 600, 3), 70, np.uint8)
    Image.fromarray(rgb).save(photo)
    window = module.MainWindow()
    window.error = lambda exc: (_ for _ in ()).throw(AssertionError(str(exc)))
    window.project = Project(image_path=str(photo), geometry=geometry, matrix=np.array([[5000., 0, 300], [0, -5000., 300]]),
                             min_diameter=0, font_percent=.5, illuminated_only=False, optimize_layout=False,
                             labels={'crest': {'text': '保留改名', 'position': [440., 480.]}})
    window.catalog, window.catalog_by_id = [feature], {'crest': feature}
    window.set_image(rgb)
    window.dem_path = str(source)
    window.sync_controls()
    window.refresh_annotations()
    baseline = {'matrix': window.project.matrix.copy(), 'geometry': window.project.geometry.to_dict(),
                'labels': deepcopy(window.project.labels)}
    before = np.array(window.project.crater_outline(feature, window.image.shape)[0])
    original_items = list(window.annotation_items)
    original_positions = [item.pos() for item in original_items]
    original_ring = original_items[0].outline_item
    threads, original = [], terrain_rims.trace_crater_rim
    def trace(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(terrain_rims, 'trace_crater_rim', trace)
    try:
        window.crater_outline_shape.setCurrentIndex(window.crater_outline_shape.findData('terrain'))
        window.apply_label_settings()
        assert window.annotation_items == original_items, 'A shape-only change must reuse the existing text and layout'
        assert window.busy, 'Selecting a contour must schedule missing DEM rim extraction'
        assert window.canvas.isEnabled(), 'Rim extraction must leave pan and zoom usable'
        with pytest.raises(ValueError, match='坑缘轮廓'):
            window.render_png(tmp_path/'pending.png')
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            application.processEvents()
            if not window.busy and window.project.terrain_rims:
                break
            time.sleep(.005)
        assert not window._outlines_pending
        assert window.annotation_items == original_items
        assert [item.pos() for item in original_items] == original_positions
        raw = np.asarray(window.project.crater_outline(feature, window.image.shape)[0])
        assert original_items[0].outline_item is original_ring
        path = original_ring.path()
        assert np.allclose([(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())], raw)
        assert len(before) == 97 and len(raw) == 129
        assert len(threads) == 1 and threads[0] != threading.get_ident()
        assert np.ptp(np.linalg.norm(raw-[300, 300], axis=1)) > 8
        assert np.array_equal(window.project.matrix, np.asarray(baseline['matrix']))
        assert window.project.geometry.to_dict() == baseline['geometry']
        assert window.project.labels == baseline['labels']
        assert not np.asarray(window.project.terrain_rims['crest']['coordinates'])[:, 2].any()
        window.crater_outline_shape.setCurrentIndex(window.crater_outline_shape.findData('ellipse'))
        window.apply_label_settings()
        assert not window.busy
        assert window.annotation_items == original_items
        smooth = np.asarray(window.project.crater_outline(feature, window.image.shape)[0])
        assert np.max(np.linalg.norm(raw-smooth, axis=1)) > 5
        window.crater_outline_shape.setCurrentIndex(window.crater_outline_shape.findData('terrain'))
        window.apply_label_settings()
        assert len(threads) == 1 and not window.busy
        assert window.annotation_items == original_items
        assert np.array_equal(window.project.crater_outline(feature, window.image.shape)[0], raw)
        saved = tmp_path/'手绘坑缘.moonlabel'
        window.project.save(saved)
        source.unlink()
        monkeypatch.setattr(module, 'prepare_project_rims', lambda *args: pytest.fail('Saved rims must redraw offline'))
        window.dirty = False
        window.open_project(saved)
        assert not window.busy and window.project.labels == baseline['labels']
        assert np.array_equal(window.project.crater_outline(feature, window.image.shape)[0], raw)
        window.render_png(tmp_path/'saved.png')
        output = tmp_path/'saved.svg'
        export_svg(output, window.image, window.annotation_entries(), window.project, window.annotation_leaders())
        outline = ET.parse(output).find('.//{http://www.w3.org/2000/svg}path[@class="crater-outline"]')
        points = np.array([[float(value) for value in pair.split(',')]
                           for pair in outline.get('d').replace('M ', '').split(' L ')])
        assert np.allclose(points, raw, atol=.00051)
        window.project.terrain_rims.clear()
        monkeypatch.setattr(window, 'crater_rim_source', lambda: '')
        window.refresh_annotations()
        assert not window.busy and not window.outline_status.isHidden()
        assert '参考圈' in window.outline_status.text()
        assert np.array_equal(window.image, rgb)
    finally:
        deadline = time.monotonic()+10
        while window.busy and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(.005)
        window.dirty = False
        window.close()


def test_terrain_trace_recovers_a_non_circular_crest_and_saved_relief(tmp_path):
    radius = 40.
    def height(lat, lon):
        vectors = surface_vectors(np.asarray(lat), np.asarray(lon))
        distance = np.arccos(np.clip(vectors[:, 0], -1, 1))*MOON_RADIUS_KM
        angle = np.arctan2(vectors[:, 1], vectors[:, 2])
        ridge = radius*(1+.08*np.cos(3*angle))
        return 2*np.exp(-((distance-ridge)/3)**2) - 2/(1+np.exp(np.clip((distance-ridge+5)/2, -100, 100)))
    dem = SimpleNamespace(sample=height, resolution_km=.5, name='Independent synthetic crest')
    feature = dict(id='crest', name='Crest', lat=0., lon=0., diameter=2*radius, kind='Crater, craters')
    rim = trace_crater_rim(dem, feature)
    assert rim is not None and rim['source'] == dem.name
    coordinates = np.asarray(rim['coordinates'])
    vectors = surface_vectors(coordinates[:, 0], coordinates[:, 1])
    distance = np.arccos(np.clip(vectors[:, 0], -1, 1))*MOON_RADIUS_KM
    angle = np.arctan2(vectors[:, 1], vectors[:, 2])
    assert np.max(abs(distance-radius*(1+.08*np.cos(3*angle)))) < 1.2
    assert np.ptp(distance) > 5 and np.allclose(coordinates[0], coordinates[-1])
    g = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]),
                 np.array([1., 0., 0.]), 384400., 'test')
    p = Project(image_path=str(tmp_path/'photo.png'), geometry=g,
                matrix=np.array([[5000., 0., 200.], [0., 5000., 200.]]), terrain_rims={'crest': rim}, font_size=10)
    outline = p.crater_outline(feature, (400, 400))
    assert len(outline[0]) == 129
    # An independently non-circular crest must become a smooth ellipse by
    # default, while the optional contour retains the actual projected shape.
    def conic_error(points):
        points = np.asarray(points)
        center, axes, degrees = cv2.fitEllipse(points[:-1].astype(np.float32))
        angle = np.radians(degrees)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        normalized = ((points-center) @ rotation)/(np.asarray(axes)/2)
        return np.max(abs(np.sum(normalized**2, axis=1)-1))
    assert p.crater_outline_shape == 'ellipse' and conic_error(outline[0]) < 1e-6
    p.crater_outline_shape = 'terrain'
    raw = p.crater_outline(feature, (400, 400))
    assert conic_error(raw[0]) > .05
    assert np.allclose(raw[0], p._project_crater_rim(feature)[0])
    p.save(tmp_path/'contour.moonlabel')
    contour = Project.load(tmp_path/'contour.moonlabel')
    assert contour.crater_outline_shape == 'terrain'
    assert np.allclose(contour.crater_outline(feature, (400, 400)), raw)
    p.crater_outline_shape = 'ellipse'
    p.save(tmp_path/'crest.moonlabel')
    restored = Project.load(tmp_path/'crest.moonlabel')
    assert restored.terrain_rims == p.terrain_rims
    assert np.allclose(restored.crater_outline(feature, (400, 400)), outline)
    export_svg(tmp_path/'crest.svg', np.zeros((400, 400, 3), np.uint8),
               [(feature, [200, 200], [340, 300])], restored)
    tree = ET.parse(tmp_path/'crest.svg')
    path = tree.find('.//{http://www.w3.org/2000/svg}path[@class="crater-outline"]')
    svg_points = np.array([[float(v) for v in pair.split(',')]
                           for pair in path.attrib['d'].replace('M ', '').split(' L ')])
    assert np.allclose(svg_points, outline[0], atol=.00051)


def test_smoothed_ellipse_retains_occulted_limb_arc():
    from moonlabeler.project import _ellipse_outline
    g = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]),
                 np.array([1., 0., 0.]), 384400., 'test')
    # Explicit legacy pixel sizing isolates arc clipping from the modern
    # percentage-font rule that intentionally hides very narrow outlines.
    p = Project(geometry=g, matrix=np.array([[15000., 0., 200.], [0., 15000., 200.]]),
                font_size=1, font_percent=None)
    feature = dict(id='limb', lat=0., lon=89.8, diameter=200., kind='Crater, craters')
    pixels, visible = p._project_crater_rim(feature)
    assert visible.any() and not visible.all()
    smooth = _ellipse_outline(pixels)
    # Shape smoothing must not render the back of a crater across the lunar limb.
    outline = p.crater_outline(feature, (400, 400))
    assert outline and sum(map(len, outline)) == visible.sum()
    assert np.allclose(np.concatenate(outline), smooth[visible])


def test_flat_or_unresolved_terrain_does_not_invent_a_rim():
    dem = SimpleNamespace(sample=lambda lat, lon: np.zeros(np.asarray(lat).shape), resolution_km=2., name='Flat')
    assert trace_crater_rim(dem, dict(lat=0., lon=0., diameter=80.)) is None
    assert trace_crater_rim(dem, dict(lat=0., lon=0., diameter=8.)) is None


def test_physical_small_crater_keeps_short_leader_even_in_a_close_up():
    g = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]),
                 np.array([1., 0., 0.]), 384400., 'test')
    p = Project(geometry=g, matrix=np.array([[14000., 0., 300.], [0., 14000., 300.]]), font_size=10)
    # Large on screen, but only 23 km across: the user's arrowed satellite crater.
    small = dict(id='small', lat=0., lon=0., diameter=23., kind='Satellite Feature')
    large = small | dict(id='large', diameter=50., kind='Crater, craters')
    assert not p.crater_outline(small, (600, 600))
    assert p.crater_outline(large, (600, 600))


def test_optional_dem_download_failure_keeps_verified_crater_registration(monkeypatch, tmp_path):
    from moonlabeler.identification import IdentificationResult
    from moonlabeler.terrain_refinement import refine_crater_identification
    matrix = np.array([[2000., 0., 300.], [0., 2000., 300.]])
    result = IdentificationResult(matrix, [object() for _ in range(7)], 3., 10., 0, coverage=.2)
    def unavailable(cache):
        raise OSError('offline')
    monkeypatch.setattr('moonlabeler.terrain.download_basic_dem', unavailable)
    assert refine_crater_identification(result, np.zeros((600, 600, 3), np.uint8), None, tmp_path, []) is result
