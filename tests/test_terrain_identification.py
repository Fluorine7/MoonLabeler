# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from moonlabeler.registration import transform_points
from moonlabeler.identification import IdentificationError
from moonlabeler.terrain_identification import identify_from_terrain, terrain_agreement


@pytest.mark.parametrize('mirrored', [False, True])
def test_rgb_terrain_search_recovers_crop_pose(monkeypatch, tmp_path, mirrored):
    """Real SIFT, validation and coordinate composition; only DEM I/O is replaced."""
    import moonlabeler.terrain_identification as terrain
    rng = np.random.default_rng(18)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (400, 400), dtype=np.uint8), (0, 0), .8)
    photograph = reference[80:320, 80:320].copy()
    if mirrored:
        photograph = cv2.flip(photograph, 1)
    photograph = np.repeat(photograph[:, :, None], 3, axis=2)
    projection = np.array([[188., 0., 199.5], [0., 188., 199.5]])
    monkeypatch.setattr(terrain, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(terrain.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(terrain, 'render_terrain_atlas', lambda *args: (reference, projection))
    result = identify_from_terrain(photograph, None, tmp_path, atlas_size=400, tile_size=400, refine=False)
    probes = np.array([[-.2, -.3], [.3, .2], [0., 0.]])
    expected = transform_points(projection, probes)-[80, 80]
    if mirrored:
        expected[:, 0] = 239-expected[:, 0]
    assert np.max(np.linalg.norm(transform_points(result.matrix, probes)-expected, axis=1)) < 1
    assert result.image_inliers >= 24 and result.coverage > .06
    assert result.texture_correlation > .9
    assert not result.matches  # Map correspondences are not named crater detections.


def test_terrain_agreement_rejects_unrelated_texture():
    rng = np.random.default_rng(12)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (256, 256), dtype=np.uint8), (0, 0), 1)
    unrelated = cv2.GaussianBlur(rng.integers(0, 256, (256, 256), dtype=np.uint8), (0, 0), 1)
    with pytest.raises(IdentificationError, match='不一致'):
        terrain_agreement(reference, unrelated, np.array([[1., 0., 0.], [0., 1., 0.]]))


def test_terrain_agreement_rejects_smooth_phase_without_detail():
    y, x = np.mgrid[:256, :256]
    reference = np.uint8(30+180*x/255)
    with pytest.raises(IdentificationError, match='地形细节'):
        terrain_agreement(reference, reference.copy(), np.array([[1., 0., 0.], [0., 1., 0.]]))


def test_repeated_terrain_in_different_regions_is_ambiguous(monkeypatch, tmp_path):
    import moonlabeler.terrain_identification as terrain
    rng = np.random.default_rng(7)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (800, 800), dtype=np.uint8), (0, 0), .8)
    reference[300:500, 460:660] = reference[300:500, 140:340]
    photograph = np.repeat(reference[300:500, 140:340, None], 3, axis=2)
    projection = np.array([[376., 0., 399.5], [0., 376., 399.5]])
    monkeypatch.setattr(terrain, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(terrain.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(terrain, 'render_terrain_atlas', lambda *args: (reference, projection))
    with pytest.raises(IdentificationError, match='多个接近'):
        identify_from_terrain(photograph, None, tmp_path, atlas_size=800, tile_size=400, refine=False)
