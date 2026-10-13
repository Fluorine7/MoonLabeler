# SPDX-License-Identifier: GPL-3.0-or-later
"""An invisible hemisphere outside the frame is not a clipped bright limb."""
import cv2
import numpy as np
import pytest

from moonlabeler import atlas, eyepiece
from moonlabeler.geometry import Geometry
from moonlabeler.identification import IdentificationError
from moonlabeler.registration import MatchResult, transform_points


@pytest.mark.parametrize('mirror', [1, -1])
def test_atlas_measures_in_frame_bright_arc_when_dark_hemisphere_is_outside(monkeypatch, mirror):
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                        np.array([0., 0., 1.]), np.array([.2, 0., -np.sqrt(.96)]),
                        384400., '2023-05-27T11:51:00+00:00')
    reference, projection = atlas.render_atlas(geometry, 600)
    camera = np.array([[380.*mirror, 0., 600.], [0., 380., 330.]])
    # The complete mathematical circle reaches y=-50, but its bright outer
    # arc is in the photograph. No SIFT success rate is inferred from this test.
    mapping = (np.vstack((camera, [0., 0., 1.]))
               @ np.linalg.inv(np.vstack((projection, [0., 0., 1.]))))[:2]
    photograph = cv2.warpAffine(reference, mapping, (1600, 900))
    x, y = np.meshgrid(np.linspace(-.35, .35, 11), np.linspace(.2, .7, 11))
    model = np.column_stack((x.ravel(), y.ravel()))
    source = transform_points(projection, model)
    target = transform_points(camera, model)
    coverage = cv2.contourArea(cv2.convexHull(target.astype(np.float32)))/(900*1600)
    assert coverage < .04
    match = MatchResult(mapping, len(model), len(model), 0., coverage,
                        mirror == -1, source, target, source, target)
    monkeypatch.setattr(atlas, 'render_atlas', lambda g: (reference, projection))
    monkeypatch.setattr(atlas, 'auto_register', lambda *args: match)
    result = atlas.identify_from_atlas(photograph, geometry)
    assert np.allclose(result.matrix, camera)
    limb = atlas._photographed_limb(photograph, camera, geometry)
    assert limb is not None
    assert np.linalg.norm(limb[0]-camera[:, 2]) < 4
    assert abs(limb[1]-380) < 3


@pytest.mark.parametrize('sun', [[.2, 0., np.sqrt(.96)], [1., 0., 0.]])
def test_clipped_illuminated_arc_is_not_licensed_by_an_unseen_circle(monkeypatch, sun):
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                        np.array([0., 0., 1.]), np.array(sun),
                        384400., '2023-05-27T11:51:00+00:00')
    camera = np.array([[380., 0., 600.], [0., 380., 200.]])
    def unexpected_fit(image):
        pytest.fail('A substantially clipped illuminated arc was sent for measurement')
    monkeypatch.setattr('moonlabeler.limb.fit_lunar_limb', unexpected_fit)
    assert atlas._photographed_limb(np.zeros((900, 1600, 3), np.uint8), camera, geometry) is None


def test_eyepiece_rejection_preserves_the_independent_validation_reason(monkeypatch):
    def reject(*args, **kwargs):
        raise IdentificationError('目镜校正的分区预测不稳定。')
    monkeypatch.setattr(eyepiece, 'identify_eyepiece', reject)
    with pytest.raises(IdentificationError, match='分区预测不稳定'):
        atlas._eyepiece_or_raise(None, None, None, None, '纹理配准与照片月缘不一致。')
