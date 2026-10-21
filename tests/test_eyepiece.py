# SPDX-License-Identifier: GPL-3.0-or-later
"""Eyepiece poses must explain the original photo, including an independent limb."""
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest


def test_phone_photo_identifies_without_moving_pixels():
    from moonlabeler.atlas import identify_from_atlas
    from moonlabeler.geometry import compute_geometry
    from moonlabeler.sources import read_image
    root = Path(__file__).parents[1]
    if not (root/'2507041216.jpg').exists() or not (root/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local photographer image and ephemerides required')
    image = read_image(root/'2507041216.jpg')
    original = image.copy()
    geometry = compute_geometry(datetime(2025, 7, 4, 12, 16, tzinfo=timezone.utc), root/'.cache/ephemeris')
    result = identify_from_atlas(image, geometry)
    assert result.lens_distortion is not None
    assert result.image_inliers >= 150
    assert result.refinement['limb_p95_px'] < 7
    assert len(result.refinement['validation_folds']) >= 4
    assert np.array_equal(image, original)


def test_phone_crescent_with_sky_padding_identifies_and_checks_separate_regions():
    from moonlabeler.atlas import identify_from_atlas
    from moonlabeler.geometry import compute_geometry
    from moonlabeler.sources import read_image
    root = Path(__file__).parents[1]
    path = root/'2502041049.jpg'
    if not path.exists() or not (root/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local photographer image and ephemerides required')
    image = read_image(path)
    original = image.copy()
    geometry = compute_geometry(datetime(2025, 2, 4, 10, 49, tzinfo=timezone.utc), root/'.cache/ephemeris')
    result = identify_from_atlas(image, geometry)
    assert result.lens_distortion is not None
    assert result.image_inliers >= 140
    assert result.rms_px < 2
    assert result.refinement['limb_arc_deg'] >= 120
    assert len(result.refinement['validation_folds']) >= 4
    assert all(fold['within_4px'] >= .8 for fold in result.refinement['validation_folds'])
    assert np.array_equal(image, original)


def synthetic_photo(mirror):
    import cv2
    from moonlabeler.geometry import Geometry
    from moonlabeler.pose_refinement import shifted_geometry
    from moonlabeler.registration import fit_similarity, MatchResult, transform_points
    g = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                 np.array([1., 0, 0]), 384400., '2025-07-04T12:16:00+00:00')
    actual = shifted_geometry(g, [.4, .5])
    projection = np.array([[470., 0, 499.5], [0, 470., 499.5]])
    camera = np.array([[280.*mirror, -50., 500.], [50.*mirror, 280., 400.]])
    def truth(points):
        ideal = transform_points(camera, points)
        delta = (ideal-[510, 385])/500
        return ideal+.18*delta*np.sum(delta**2, axis=1, keepdims=True)*500
    x, y = np.meshgrid(np.linspace(-.92, .92, 23), np.linspace(-.92, .92, 23))
    model = np.column_stack((x.ravel(), y.ravel()))
    model = model[np.linalg.norm(model, axis=1) < .94]
    lat, lon, _ = g.unproject(model)
    target = truth(actual.project(lat, lon)[0])
    target += np.random.default_rng(52).normal(0, .15, target.shape)
    source = transform_points(projection, model)
    coarse, rms = fit_similarity(source, target)
    match = MatchResult(coarse, 100, len(source), rms, .2, mirror == -1,
                        source, target, source, target)
    a = np.linspace(0, 2*np.pi, 1000)
    rim = truth(np.column_stack((np.cos(a), np.sin(a))))
    photo = np.zeros((800, 1000, 3), np.uint8)
    cv2.fillPoly(photo, [np.rint(rim).astype(np.int32)], (180, 180, 180))
    return g, projection, match, photo, actual, truth


@pytest.mark.parametrize('mirror', [1, -1])
def test_sky_padding_does_not_replace_lunar_area_or_hide_an_incompatible_limb(mirror):
    from dataclasses import replace
    from moonlabeler.eyepiece import identify_eyepiece, distort_points
    from moonlabeler.identification import IdentificationError
    from moonlabeler.registration import transform_points
    g, projection, match, photo, actual, truth = synthetic_photo(mirror)
    origin = np.array([800., 600.])
    padded = np.pad(photo, ((600, 600), (800, 800), (0, 0)))
    camera = match.matrix.copy()
    camera[:, 2] += origin
    shifted = replace(match, matrix=camera, target_points=match.target_points+origin,
                      target_matches=match.target_matches+origin,
                      coverage=match.coverage*photo.shape[0]*photo.shape[1]/(padded.shape[0]*padded.shape[1]))
    result = identify_eyepiece(padded, g, projection, shifted)
    probes = np.array([[-.71, .45], [.52, -.65], [.82, .1], [-.42, -.68]])
    lat, lon, _ = g.unproject(probes)
    predicted = distort_points(transform_points(result.matrix, result.projection_geometry.project(lat, lon)[0]),
                               result.lens_distortion)
    assert np.max(np.linalg.norm(predicted-truth(actual.project(lat, lon)[0])-origin, axis=1)) < .6
    with pytest.raises(IdentificationError, match='月缘'):
        identify_eyepiece(np.roll(padded, 40, axis=1), g, projection, shifted)


@pytest.mark.parametrize('mirror', [1, -1])
def test_distortion_validates_unused_locations_and_rejects_false_silhouette(mirror):
    from moonlabeler.eyepiece import identify_eyepiece, distort_points
    from moonlabeler.identification import IdentificationError
    from moonlabeler.registration import transform_points
    g, projection, match, photo, actual, truth = synthetic_photo(mirror)
    result = identify_eyepiece(photo, g, projection, match)
    probes = np.array([[-.71, .45], [.52, -.65], [.82, .1], [-.42, -.68]])
    lat, lon, _ = g.unproject(probes)
    predicted = distort_points(transform_points(result.matrix, result.projection_geometry.project(lat, lon)[0]),
                               result.lens_distortion)
    assert np.max(np.linalg.norm(predicted-truth(actual.project(lat, lon)[0]), axis=1)) < .6
    with pytest.raises(IdentificationError, match='月缘'):
        identify_eyepiece(np.roll(photo, 25, axis=1), g, projection, match)
    # A lens must not explain arbitrary bad descriptor matches.
    match.target_matches = match.target_matches.copy()
    match.target_matches[::3] += [40, -60]
    with pytest.raises(IdentificationError):
        identify_eyepiece(photo, g, projection, match)


def test_aligned_retry_is_skipped_after_valid_optical_fit(monkeypatch):
    from moonlabeler import atlas, registration
    g, projection, match, photo, _, _ = synthetic_photo(1)
    def unexpected(*args):
        pytest.fail('A successful photo must not run the extra matching pass')
    monkeypatch.setattr(registration, 'realign_registration_matches', unexpected)
    result = atlas._eyepiece_or_raise(photo, g, projection, match, 'failed', reference=photo)
    assert result.lens_distortion is not None
    assert 'rematch' not in result.method


def test_aligned_retry_cannot_bypass_incompatible_observed_limb(monkeypatch):
    from moonlabeler import atlas, registration
    from moonlabeler.identification import IdentificationError
    g, projection, match, photo, _, _ = synthetic_photo(1)
    calls = []
    def rematch(*args, **kwargs):
        calls.append(True)
        return match
    monkeypatch.setattr(registration, 'realign_registration_matches', rematch)
    incompatible = np.roll(photo, 25, axis=1)
    with pytest.raises(IdentificationError, match='月缘'):
        atlas._eyepiece_or_raise(incompatible, g, projection, match, 'failed',
                                 limb=(np.array([500., 400.]), 300., 1., 300), reference=photo)
    assert len(calls) == 1


def test_project_round_trip_uses_lens_for_centers_rims_and_font_scale(tmp_path):
    from moonlabeler.eyepiece import distortion_jacobian
    from moonlabeler.project import Project
    g, _, _, _, _, _ = synthetic_photo(1)
    project = Project(geometry=g, matrix=np.array([[500., 0, 500.], [0, 500., 400.]]))
    project.identification['lens_distortion'] = dict(center=[500., 400.], scale=500., k=.2)
    # At ideal x=900: delta=.8, so radial displacement is .2*.8**3*500 = 51.2 px.
    assert project.photo_points([[.8, 0]])[0] == pytest.approx([951.2, 400.])
    feature = dict(id='test', name='Test', lat=0., lon=45., diameter=100., kind='Crater, craters')
    expected_rim = project._project_crater_rim(feature)[0]
    path = tmp_path/'lens.moonlabel'
    project.save(path)
    loaded = Project.load(path)
    assert loaded.photo_points([[.8, 0]])[0] == pytest.approx([951.2, 400.])
    assert np.array_equal(loaded._project_crater_rim(feature)[0], expected_rim)
    jacobian = distortion_jacobian(np.array([[900., 400.]]), project.identification['lens_distortion'])[0]
    assert np.diag(jacobian) == pytest.approx([1.384, 1.128])
    loaded.identification.clear()
    assert loaded.photo_points([[.8, 0]])[0] == pytest.approx([900, 400])


@pytest.mark.parametrize('value', [-1, float('nan'), '0.2', True])
def test_project_rejects_malformed_lens_metadata(tmp_path, value):
    import json
    from moonlabeler.project import Project
    p = Project()
    p.identification['lens_distortion'] = dict(center=[500., 400.], scale=500., k=.2)
    path = tmp_path/'lens.moonlabel'
    p.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data['automatic_recognition']['lens_distortion']['k'] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match='lens_distortion'):
        Project.load(path)


def test_gui_and_both_exports_use_corrected_original_pixels(tmp_path):
    import os
    import xml.etree.ElementTree as ET
    from PIL import Image
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from moonlabeler.app import MainWindow
    from moonlabeler.project import Project, export_svg
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    g, _, _, _, _, _ = synthetic_photo(1)
    window.project = Project(geometry=g, matrix=np.array([[500., 0, 500.], [0, 500., 400.]]),
                             min_diameter=0, illuminated_only=False, crater_outlines=False)
    window.project.identification['lens_distortion'] = dict(center=[500., 400.], scale=500., k=.2)
    lat, lon, _ = g.unproject([[.8, 0]])
    feature = dict(id='probe', name='Probe', lat=lat[0], lon=lon[0], diameter=10., kind='Crater, craters')
    window.catalog = [feature]
    window.catalog_by_id = {'probe': feature}
    try:
        window.set_image(np.zeros((800, 1100, 3), np.uint8))
        item = window.annotation_items[0]
        assert [item.anchor.x(), item.anchor.y()] == pytest.approx([951.2, 400.], abs=1e-6)
        png, svg = tmp_path/'photo.png', tmp_path/'photo.svg'
        window.render_png(png)
        export_svg(svg, window.image, window.annotation_entries(), window.project, window.annotation_leaders())
        raster = np.asarray(Image.open(png))
        assert raster[397:404, 948:955, :3].max() > 220
        assert not raster[397:404, 897:904, :3].any(), 'PNG drew the uncorrected center'
        marker = ET.parse(svg).find('.//{http://www.w3.org/2000/svg}circle')
        assert float(marker.get('cx')) == pytest.approx(951.2, abs=.001)
        assert float(marker.get('cy')) == pytest.approx(400., abs=.001)
    finally:
        window.dirty = False
        window.close()
