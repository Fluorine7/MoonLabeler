# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Independent geometric fixtures test centers, not real-photo accuracy."""
import cv2
import numpy as np
import pytest

from moonlabeler.craters import DetectionOptions, detect_craters, detect_crater_rims


def test_detects_circle_and_tilted_ellipse_without_names_or_mutating_image():
    image = np.full((360, 520), 72, np.uint8)
    cv2.circle(image, (110, 140), 35, 215, 3)
    cv2.ellipse(image, (350, 190), (60, 30), 35, 0, 360, 205, 3)
    original = image.copy()
    result = detect_craters(image, DetectionOptions(15, 80, 50, 30))
    assert np.array_equal(image, original)
    for center in ((110, 140), (350, 190)):
        nearby = [c for c in result.candidates if np.hypot(c.x-center[0], c.y-center[1]) < 5]
        assert len(nearby) == 1
    ellipse = min(result.candidates, key=lambda c: np.hypot(c.x-350, c.y-190))
    assert abs(ellipse.major-60) < 6 and abs(ellipse.minor-30) < 6
    assert abs(ellipse.angle-35) < 6
    assert all(0 <= c.support <= 1 for c in result.candidates)


def test_roi_and_downscaled_detection_keep_original_pixel_coordinates():
    image = np.full((720, 1200, 3), 85, np.uint8)
    cv2.circle(image, (900, 470), 55, (220, 220, 220), 5)
    cv2.circle(image, (200, 170), 40, (230, 230, 230), 5)
    result = detect_craters(image, DetectionOptions(25, 90, 50, 10, 300), (660, 260, 500, 430))
    assert result.scale < 1
    assert result.region == (660, 260, 500, 430)
    assert result.candidates
    nearest = min(result.candidates, key=lambda c: np.hypot(c.x-900, c.y-470))
    assert np.hypot(nearest.x-900, nearest.y-470) < 6
    assert abs((nearest.major+nearest.minor)/2-55) < 8
    assert not any(c.x < 660 for c in result.candidates)


def test_blank_image_has_no_candidates_and_invalid_parameters_fail_clearly():
    image = np.full((128, 128, 3), 72, np.uint8)
    assert detect_craters(image).candidates == []
    with pytest.raises(ValueError, match="最大半径"):
        detect_craters(image, DetectionOptions(50, 10))
    with pytest.raises(ValueError, match="区域太小"):
        detect_craters(image, region=(200, 200, 30, 30))


def test_partial_rim_arcs_are_grouped_into_one_original_image_center():
    image = np.full((480, 640), 72, np.uint8)
    cv2.ellipse(image, (380, 240), (100, 65), 25, 0, 150, 220, 3)
    cv2.ellipse(image, (380, 240), (100, 65), 25, 185, 290, 220, 3)
    original = image.copy()
    candidates = detect_crater_rims(image).candidates
    nearby = [c for c in candidates if np.hypot(c.x-380, c.y-240) < 5]
    assert len(nearby) == 1
    assert abs(nearby[0].major-100) < 5 and abs(nearby[0].minor-65) < 5
    assert np.array_equal(image, original)
    assert not detect_crater_rims(np.full((120, 160),72,np.uint8)).candidates


def test_large_broken_ellipse_is_not_cut_off_by_automatic_size_limit():
    image = np.full((600, 1000), 72, np.uint8)
    for start, end in ((5, 95), (110, 200), (220, 340)):
        cv2.ellipse(image, (480, 300), (280, 210), 8, start, end, 210, 5)
    for detect in (detect_crater_rims,
                   lambda image: detect_craters(image, DetectionOptions(190, 400, 100, 10))):
        candidates = detect(image).candidates
        nearby = [c for c in candidates if np.hypot(c.x-480, c.y-300) < 12]
        assert nearby, 'A crater occupying most of the image height is a valid candidate'
        assert abs(nearby[0].major-280) < 15


def test_large_crater_photo_candidate_when_local_fixture_available():
    # User's photograph is not redistributed. Bounds select the large central
    # crater, independently of the algorithm; they do not assert a place name.
    from pathlib import Path
    from moonlabeler.sources import read_image
    path = Path(__file__).resolve().parent.parent/'2026-08-31-2137_7-Moon_lapl3_ap311(1).tif'
    if not path.exists():
        pytest.skip('Local telescope photo unavailable')
    image = read_image(path)
    for detect in (detect_crater_rims,
                   lambda image: detect_craters(image, DetectionOptions(200, 1300, 100, 80))):
        candidates = detect(image).candidates
        assert any(1150 < c.x < 1450 and 450 < c.y < 680
                   and 500 < c.major < 750 and 350 < c.minor < 600 for c in candidates)
        assert not any(c.x > 2100 and c.y > 600 for c in candidates), \
            'The lower-right bright terrain is not a crater'


def test_large_rim_pass_rejects_lunar_limb_and_straight_terrain():
    from moonlabeler.craters import _large_rim_candidates
    moon = np.zeros((500, 700), np.uint8)
    cv2.circle(moon, (350, 250), 210, 160, -1)
    assert not _large_rim_candidates(moon)
    terrain = np.full((500, 700), 80, np.uint8)
    for i in range(-500, 700, 35):
        cv2.line(terrain, (i, 0), (i+300, 500), 200, 5)
    assert not _large_rim_candidates(terrain)


def test_large_detection_preserves_roi_coordinates_and_radius_filter():
    image = np.full((1000, 1800), 72, np.uint8)
    cv2.ellipse(image, (1140, 570), (270, 190), 12, 0, 360, 210, 5)
    result = detect_craters(image, DetectionOptions(170, 330, 100, 20), (600, 180, 950, 740))
    assert any(np.hypot(c.x-1140, c.y-570) < 10 for c in result.candidates)
    assert all(170 <= (c.major+c.minor)/2 <= 330 for c in result.candidates)
