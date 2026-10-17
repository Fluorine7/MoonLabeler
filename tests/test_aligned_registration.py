# SPDX-License-Identifier: GPL-3.0-or-later
"""A rigid search reorientation must preserve original photo/map coordinates."""
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from moonlabeler import atlas, registration


@pytest.mark.parametrize('sign', [1, -1])
def test_aligned_matches_restore_original_coordinates_after_bounded_resize(sign):
    rng = np.random.default_rng(71)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (500, 600), np.uint8), (5, 5), 1.)
    camera = np.array([[2.4*sign, -.25, 500. if sign == 1 else 2100.],
                       [.25*sign, 2.4, 250.]])
    photograph = cv2.warpAffine(reference, camera, (2800, 2300))
    unchanged = photograph.copy()
    coarse = registration.MatchResult(camera.copy(), 100, 120, 1., .2, sign == -1)
    coarse.matrix[:, 2] += [2., -1.]
    result = registration.realign_registration_matches(reference, photograph, coarse)
    assert result.mirrored == (sign == -1)
    assert np.array_equal(photograph, unchanged)
    assert np.median(np.linalg.norm(
        registration.transform_points(camera, result.source_matches)-result.target_matches, axis=1)) < 1.5
    probes = np.array([[100, 100], [400, 100], [200, 350]])
    assert np.max(np.linalg.norm(registration.transform_points(camera, probes)-
                                 registration.transform_points(result.matrix, probes), axis=1)) < 1.


def test_phone_with_sparse_outer_matches_passes_original_optical_checks():
    from moonlabeler.geometry import compute_geometry
    from moonlabeler.sources import read_image
    root = Path(__file__).parents[1]
    if not (root/'2305271151.jpg').exists() or not (root/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Private afocal photograph and cached ephemerides required')
    photo = read_image(root/'2305271151.jpg')
    unchanged = photo.copy()
    geometry = compute_geometry(datetime.fromisoformat('2023-05-27T11:51:00+00:00'), root/'.cache/ephemeris')
    result = atlas.identify_from_atlas(photo, geometry)
    assert result.lens_distortion is not None
    assert 'rigid-aligned rematch' in result.method
    assert result.image_inliers >= 100 and result.rms_px < 2
    assert result.refinement['limb_arc_deg'] >= 120
    assert result.refinement['limb_p95_px'] < 5
    folds = result.refinement['validation_folds']
    assert len(folds) >= 4 and all(fold['within_4px'] >= .8 for fold in folds)
    assert np.array_equal(photo, unchanged)
