# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from pathlib import Path

import cv2
import numpy as np
import pytest

from moonlabeler.registration import auto_register, fit_similarity, transform_points, calibration_report, prepare_registration_photo
from moonlabeler.sources import read_image, detect_reference_disk


@pytest.mark.parametrize("mirrored", [False, True])
def test_manual_similarity_recovers_mirror_and_rotation(mirrored):
    source = np.array([[0.,0],[.2,.4],[-.6,.1],[.4,-.5]])
    angle = .7
    matrix = np.array([[150*np.cos(angle),-150*np.sin(angle),720],
                       [150*np.sin(angle),150*np.cos(angle),540]])
    if mirrored:
        matrix[:,0] *= -1
    target = transform_points(matrix,source)
    actual, rms = fit_similarity(source,target)
    assert rms < 1e-9
    assert np.allclose(actual,matrix)


def test_reject_degenerate_manual_anchors():
    with pytest.raises(ValueError):
        fit_similarity([[0,0],[0,0]],[[30,30],[40,40]])
    with pytest.raises(ValueError):
        fit_similarity([[0,0],[1,0],[2,0]],[[30,30],[40,40],[50,50]])


def test_calibration_flags_single_bad_click_without_discarding_it():
    source = np.array([[0., 0], [.2, .4], [-.6, .1], [.4, -.5], [-.4, -.5], [.1, -.3]])
    matrix = np.array([[-500., 30, 720], [30, 500., 540]])
    target = transform_points(matrix, source)
    target[2] += [35, -50]
    report = calibration_report(source, target)
    assert report.suspect_index == 2
    assert report.check_errors_px[2] > 60
    assert len(report.residuals_px) == 6
    # Its fit still uses the bad click. Explicitly disabling it restores truth.
    assert not np.allclose(report.matrix, matrix)
    keep = np.arange(6) != 2
    corrected = calibration_report(source[keep], target[keep])
    assert corrected.suspect_index is None and corrected.rms_px < 1e-9
    assert np.allclose(corrected.matrix, matrix)


def test_four_points_do_not_claim_unique_outlier_and_two_have_no_check():
    source = np.array([[0., 0], [1, 0], [0, 1], [.2, .4]])
    target = source*100
    target[0] += [20, 30]
    report = calibration_report(source, target)
    assert report.suspect_index is None
    assert np.isfinite(report.check_errors_px).all()
    two = calibration_report(source[:2], target[:2])
    assert np.isnan(two.check_errors_px).all()


@pytest.mark.parametrize("mirrored,cropped", [(False,False),(True,False),(False,True),(True,True)])
def test_auto_on_transformed_nasa_lunar_photograph(mirrored,cropped):
    # NASA Galileo PIA00405. This checks registration against a transformed
    # photograph; it is NOT a claim of matching independently captured images.
    path = Path(__file__).parents[1] / "examples/nasa-galileo.jpg"
    if not path.exists():
        pytest.skip("NASA photograph not bundled")
    reference = cv2.resize(read_image(path),(1200,1200))
    matrix = cv2.getRotationMatrix2D((600,600),33,.78)
    if mirrored:
        mirror = np.array([[-1.,0,1199],[0,1.,0],[0,0,1.]])
        matrix = (np.vstack((matrix,[0,0,1])) @ mirror)[:2]
    photo = cv2.warpAffine(reference,matrix,(1200,1200))
    if cropped:
        photo = photo[300:900,350:1000]
        matrix[:,2] -= [350,300]
    photo = cv2.GaussianBlur(photo,(3,3),.6)
    photo = np.uint8(np.clip(photo.astype(float)**.9 * 255**.1,0,255))
    result = auto_register(reference,photo)
    points = np.array([[500,500],[700,500],[500,700],[700,700]])
    error = np.linalg.norm(transform_points(result.matrix,points)-transform_points(matrix,points),axis=1)
    assert np.max(error) < 1.5
    assert result.mirrored == mirrored
    assert result.inliers >= 12


def test_auto_rejects_blank_image():
    image = np.zeros((400,400,3),dtype=np.uint8)
    with pytest.raises(ValueError):
        auto_register(image,image)


def test_prepared_photo_reuses_features_across_tiles_without_changing_pose():
    rng = np.random.default_rng(7)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (480, 640), dtype=np.uint8), (5, 5), 1.)
    photograph = reference[80:400, 120:540].copy()
    prepared = prepare_registration_photo(photograph)
    for x in (0, 80):
        tile = reference[:, x:x+550]
        fresh = auto_register(tile, photograph)
        reused = auto_register(tile, photograph, prepared_photo=prepared)
        assert np.allclose(reused.matrix, fresh.matrix)
        assert reused.inliers == fresh.inliers
        expected = np.array([[1., 0., x-120], [0., 1., -80]])
        assert np.allclose(reused.matrix, expected, atol=.1)
    with pytest.raises(ValueError, match='不一致'):
        auto_register(reference, photograph.copy(), prepared_photo=prepared)
    with pytest.raises(ValueError, match='不一致'):
        auto_register(reference, photograph, contrast_threshold=.01, prepared_photo=prepared)


@pytest.mark.parametrize('mirror', [1, -1])
def test_match_inliers_use_original_coordinates_after_resize_and_reflection(mirror):
    rng = np.random.default_rng(61)
    texture = rng.integers(0, 256, (600, 600), dtype=np.uint8)
    texture = cv2.GaussianBlur(texture, (5, 5), 1.)
    reference = cv2.resize(texture, (2400, 2400))
    expected = np.array([[.72*mirror, 0., 460. if mirror == 1 else 2187.28],
                         [0., .72, 320.]])
    photograph = cv2.warpAffine(reference, expected, (3000, 2600))
    match = auto_register(reference, photograph)
    assert match.mirrored == (mirror == -1)
    assert len(match.source_points) == len(match.target_points) == match.inliers
    error = np.linalg.norm(transform_points(expected, match.source_points)-match.target_points, axis=1)
    assert np.median(error) < 1.5
    actual = np.linalg.norm(transform_points(match.matrix, match.source_points)-match.target_points, axis=1)
    assert np.sqrt(np.mean(actual**2)) == pytest.approx(match.rms_px)


def test_reference_alpha_circle_rejects_rectangular_canvas():
    rgba = np.zeros((500,500,4),np.uint8)
    cv2.circle(rgba[:,:,3].copy(),(250,250),200,255,-1)
    alpha = np.zeros((500,500),np.uint8)
    cv2.circle(alpha,(250,250),200,255,-1)
    rgba[:,:,3] = alpha
    x,y,r = detect_reference_disk(rgba)
    assert (x,y) == pytest.approx((250,250),abs=.1)
    assert r == pytest.approx(200,abs=1)
    rgba[:,:,3] = 255
    with pytest.raises(ValueError):
        detect_reference_disk(rgba)
