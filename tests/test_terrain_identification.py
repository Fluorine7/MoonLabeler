# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from moonlabeler.registration import transform_points
from moonlabeler.identification import IdentificationError
from moonlabeler.terrain_identification import identify_from_terrain, terrain_agreement, terrain_consensus


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


def test_borderline_light_needs_stronger_detail_count_and_distribution():
    assert terrain_consensus(.5987, .303, 33, .179)
    assert terrain_consensus(.65, .27, 24, .07)
    assert not terrain_consensus(.5987, .303, 31, .179)
    assert not terrain_consensus(.5987, .29, 33, .179)
    assert not terrain_consensus(.5987, .303, 33, .10)
    assert not terrain_consensus(.58, .5, 60, .5)
    assert not terrain_consensus(np.nan, .5, 60, .5)


@pytest.mark.parametrize('coarse', [False, True])
def test_repeated_terrain_in_different_regions_is_ambiguous(monkeypatch, tmp_path, coarse):
    import moonlabeler.terrain_identification as terrain
    rng = np.random.default_rng(7)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (800, 800), dtype=np.uint8), (0, 0), .8)
    reference[300:500, 460:660] = reference[300:500, 140:340]
    photograph = np.repeat(reference[300:500, 140:340, None], 3, axis=2)
    projection = np.array([[376., 0., 399.5], [0., 376., 399.5]])
    monkeypatch.setattr(terrain, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(terrain.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(terrain, 'render_terrain_atlas', lambda *args: (reference, projection))
    if coarse:
        import moonlabeler.terrain_refinement as refinement
        monkeypatch.setattr(terrain, 'terrain_agreement', lambda *args, **kwargs: (.53, .35))
        def correct(image, geometry, matrix, dem, **kwargs):
            return SimpleNamespace(matrix=matrix, geometry=object(), rms_px=1.,
                                   details={'points': 100, 'coverage': .4,
                                            'light_before_after': [.53, .72],
                                            'detail_before_after': [.35, .5]})
        monkeypatch.setattr(refinement, 'refine_terrain_pose', correct)
    with pytest.raises(IdentificationError, match='多个接近'):
        identify_from_terrain(photograph, None, tmp_path, atlas_size=800, tile_size=400, refine=coarse)


@pytest.mark.parametrize('fresh_light,accepted', [(.72, True), (.58, False)])
def test_distributed_coarse_pose_needs_relief_refinement_and_fresh_validation(monkeypatch, tmp_path, fresh_light, accepted):
    """A real SIFT retrieval can precede a failed coarse sphere/light check.

    The physical refinement is isolated here; its fresh evidence must pass the
    original dense thresholds, even when it reports many correspondences.
    """
    import moonlabeler.terrain_identification as terrain
    import moonlabeler.terrain_refinement as refinement
    rng = np.random.default_rng(18)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (400, 400), dtype=np.uint8), (0, 0), .8)
    photograph = reference[80:320, 80:320].copy()
    projection = np.array([[188., 0., 199.5], [0., 188., 199.5]])
    monkeypatch.setattr(terrain, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(terrain.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(terrain, 'render_terrain_atlas', lambda *args: (reference, projection))
    monkeypatch.setattr(terrain, 'terrain_agreement', lambda *args, **kwargs: (.53, .35))
    calls = []
    corrected_geometry = object()
    def correct(image, geometry, matrix, dem, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(matrix=matrix, geometry=corrected_geometry, rms_px=1.,
                               details={'points': 100, 'coverage': .4,
                                        'light_before_after': [.53, fresh_light],
                                        'detail_before_after': [.35, .5]})
    monkeypatch.setattr(refinement, 'refine_terrain_pose', correct)
    if accepted:
        result = identify_from_terrain(photograph, None, tmp_path, atlas_size=400, tile_size=400)
        assert result.projection_geometry is corrected_geometry
        assert result.image_inliers == 100 and result.texture_correlation == fresh_light
        assert np.linalg.norm(transform_points(result.matrix, [[0., 0.]])[0]-[119.5,119.5]) < 1
    else:
        with pytest.raises(IdentificationError):
            identify_from_terrain(photograph, None, tmp_path, atlas_size=400, tile_size=400)
    assert len(calls) == 1 and calls[0]['relief_aware']


@pytest.mark.parametrize('competitive', [True, False])
def test_pending_competing_region_is_not_hidden_by_one_coarse_accepted_pose(monkeypatch, tmp_path, competitive):
    """Mixed accepted/deferred regions must share the final ambiguity check."""
    import moonlabeler.terrain_identification as terrain
    import moonlabeler.terrain_refinement as refinement
    from moonlabeler.registration import MatchResult
    rng = np.random.default_rng(12)
    reference = rng.integers(0, 255, (800, 800), np.uint8)
    projection = np.array([[376., 0., 399.5], [0., 376., 399.5]])
    photograph = np.full((100, 100), 50, np.uint8)
    monkeypatch.setattr(terrain, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(terrain.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(terrain, 'render_terrain_atlas', lambda *args: (reference, projection))
    retrievals, checks, relief_calls = [], [], []
    def retrieve(*args, **kwargs):
        retrievals.append(None)
        if len(retrievals) > 2:
            raise ValueError('No other match')
        count = 100 if competitive and len(retrievals) == 2 else 40
        return MatchResult(np.array([[1., 0., -300.], [0., 1., -300.]]), count, count+5, 1., .5, False)
    def agreement(*args, **kwargs):
        checks.append(None)
        return (.62, .31) if len(checks) == 1 else ((.54, .35) if competitive else (.4, .25))
    def correct(image, geometry, matrix, dem, **kwargs):
        if not kwargs.get('relief_aware'):
            return None
        relief_calls.append(matrix)
        return SimpleNamespace(matrix=matrix, geometry=object(), rms_px=1.,
                               details={'points': 40, 'coverage': .4,
                                        'light_before_after': [.54, .65],
                                        'detail_before_after': [.35, .3]})
    monkeypatch.setattr(terrain, 'auto_register', retrieve)
    monkeypatch.setattr(terrain, 'terrain_agreement', agreement)
    monkeypatch.setattr(refinement, 'refine_terrain_pose', correct)
    if competitive:
        with pytest.raises(IdentificationError, match='多个接近'):
            identify_from_terrain(photograph, None, tmp_path, atlas_size=800, tile_size=400)
        assert len(relief_calls) == 1
    else:
        result = identify_from_terrain(photograph, None, tmp_path, atlas_size=800, tile_size=400)
        assert result.image_inliers == 40 and not relief_calls
