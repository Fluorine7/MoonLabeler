# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""An interior texture fit must also place lunar-limb terrain on the Moon."""
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

from moonlabeler.atlas import identify_from_atlas
from moonlabeler.geometry import Geometry, compute_geometry
from moonlabeler.identification import IdentificationError
from moonlabeler.pose_refinement import shifted_geometry
from moonlabeler.registration import MatchResult, fit_similarity, transform_points
from moonlabeler.sources import load_catalog, read_image


@pytest.mark.parametrize('allow_eyepiece', [True, False])
def test_full_moon_texture_fit_keeps_southern_anchors_on_photograph(allow_eyepiece):
    root = Path(__file__).parents[1]
    path = root/'230603-2.jpg'
    if not path.exists() or not (root/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local photographer image and ephemerides required')
    image = read_image(path)
    geometry = compute_geometry(datetime(2023, 6, 3, 15, tzinfo=timezone.utc), root/'.cache/ephemeris')
    result = identify_from_atlas(image, geometry, allow_eyepiece=allow_eyepiece)
    geometry = result.projection_geometry or geometry
    names = {'Bailly', 'Boussingault', 'Curtius', 'Scheiner', 'Mutus'}
    features = [f for f in load_catalog(root/'.cache') if f['name'] in names]
    points, visible, _ = geometry.project([f['lat'] for f in features], [f['lon'] for f in features])
    pixels = np.rint(transform_points(result.matrix, points)).astype(int)
    # Independent visible disk contour, never derived from the fitted matrix.
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    contours, _ = cv2.findContours((gray > 20).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    mask = np.zeros_like(gray)
    cv2.drawContours(mask, [max(contours, key=cv2.contourArea)], -1, 1, -1)
    outside = cv2.distanceTransform(1-mask, cv2.DIST_L2, 5)
    errors = {f['name']: float(outside[y, x]) for f, (x, y), okay in zip(features, pixels, visible) if okay}
    assert errors and max(errors.values()) < 5, f'Southern anchors point into sky: {errors}'


@pytest.mark.parametrize('mirror', [1, -1])
def test_padded_disk_refines_view_using_distributed_points_and_independent_limb(monkeypatch, mirror):
    # Synthetic correspondences test the projection, not SIFT recognition rates.
    from moonlabeler import atlas
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                        np.array([0., 0., 1.]), np.array([1., 0., 0.]),
                        384400., '2023-06-03T15:00:00+00:00')
    actual = shifted_geometry(geometry, [.9, 2.1])
    x, y = np.meshgrid(np.linspace(-.85, .85, 17), np.linspace(-.85, .85, 17))
    disk = np.column_stack((x.ravel(), y.ravel()))
    disk = disk[np.linalg.norm(disk, axis=1) < .88]
    lat, lon, _ = geometry.unproject(disk)
    angle = np.radians(17)
    camera = 420*np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]) @ np.diag([mirror, 1])
    truth = np.column_stack((camera, [1500., 850.]))
    target = transform_points(truth, actual.project(lat, lon)[0])
    coarse, rms = fit_similarity(disk, target)
    projection = np.array([[752., 0., 799.5], [0., 752., 799.5]])
    source = transform_points(projection, disk)
    inverse = np.linalg.inv(np.vstack((projection, [0., 0., 1.])))
    mapping = (np.vstack((coarse, [0., 0., 1.])) @ inverse)[:2]
    monkeypatch.setattr(atlas, 'render_atlas', lambda g: (None, projection))
    monkeypatch.setattr(atlas, 'auto_register', lambda *args: MatchResult(
        mapping, len(disk), len(disk), rms, .08, mirror == -1, source, target))
    photograph = np.zeros((1800, 3000, 3), np.uint8)
    cv2.circle(photograph, (1500, 850), 420, (180, 180, 180), -1)
    result = identify_from_atlas(photograph, geometry)
    assert result.projection_geometry is not None
    assert result.refinement['validation_after_px'] < .2
    assert result.refinement['limb_after_px'] < result.refinement['limb_before_px']*.4
    probes = np.array([[.1, -.99], [-.5, -.85], [.5, -.85]])
    probe_lat, probe_lon, _ = geometry.unproject(probes)
    expected = transform_points(truth, actual.project(probe_lat, probe_lon)[0])
    corrected = transform_points(result.matrix, result.projection_geometry.project(probe_lat, probe_lon)[0])
    assert np.max(np.linalg.norm(corrected-expected, axis=1)) < .2
    # The same correspondences cannot certify a physically different silhouette.
    incompatible = np.roll(photograph, 40, axis=1)
    with pytest.raises(IdentificationError, match='月缘不一致'):
        identify_from_atlas(incompatible, geometry)
