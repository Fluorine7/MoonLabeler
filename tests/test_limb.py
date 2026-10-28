# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Pose recovery and rejection tests; synthetic cases do not prove real accuracy."""
import cv2
import numpy as np
import pytest

from moonlabeler.atlas import render_atlas
from moonlabeler.geometry import Geometry
from moonlabeler.identification import IdentificationError
from moonlabeler.limb import identify_from_limb, fit_lunar_limb
from moonlabeler.registration import transform_points


def view():
    return Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                    np.array([-.5, np.sqrt(.75), 0]), 384400., '2026-08-17T15:00:00+00:00')


@pytest.mark.parametrize('mirror', [1, -1])
def test_rotated_crescent_pose_and_mirror_recovered_from_limb_and_texture(mirror, monkeypatch, tmp_path):
    geometry = view()
    reference, projection = render_atlas(geometry, 600)
    theta = np.radians(37.)
    linear = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]) @ np.diag([mirror, 1])
    expected = np.column_stack((linear*520., [600., 630.]))
    inverse = np.linalg.inv(np.vstack((projection, [0., 0., 1.])))
    warp = (np.vstack((expected, [0., 0., 1.])) @ inverse)[:2]
    # Keep the bright outer arc in frame for either rotation / reflection.
    photograph = cv2.warpAffine(reference, warp, (1200, 1200))
    def unnecessary(*args, **kwargs):
        pytest.fail('An accepted albedo/limb pose must not run the terrain fallback')
    monkeypatch.setattr('moonlabeler.limb_refinement.identify_limb_terrain', unnecessary)
    result = identify_from_limb(photograph, geometry, cache=tmp_path)
    probes = np.array([[.4, .1], [.6, -.3], [.85, .2]])
    error = np.linalg.norm(transform_points(result.matrix, probes)-transform_points(expected, probes), axis=1)
    assert error.max() < 8
    assert result.limb_inliers >= 60 and result.texture_correlation >= .5
    assert result.image_inliers == 0 and not result.matches


def test_blank_and_untextured_phase_shape_cannot_identify_place_names():
    geometry = view()
    with pytest.raises(IdentificationError):
        identify_from_limb(np.zeros((600, 900, 3), np.uint8), geometry)
    yy, xx = np.mgrid[:950, :1200]
    disk = (xx-600)**2+(yy-630)**2 < 520**2
    # A bright crescent with no lunar albedo information. A circular limb and
    # phase alone cannot resolve lunar rotation or handedness.
    shape = np.zeros((950, 1200, 3), np.uint8)
    shape[disk & (xx > 720)] = 180
    with pytest.raises(IdentificationError):
        identify_from_limb(shape, geometry)


def test_short_limb_arc_rejects_polar_crop():
    yy, xx = np.mgrid[:360, :640]
    image = np.zeros((360, 640, 3), np.uint8)
    image[(xx-320)**2+(yy-1750)**2 < 1600**2] = 140
    with pytest.raises(IdentificationError):
        fit_lunar_limb(image)
