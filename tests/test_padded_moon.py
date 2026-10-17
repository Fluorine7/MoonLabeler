# SPDX-License-Identifier: GPL-3.0-or-later
"""Sky padding must not invalidate an otherwise detailed, whole lunar disk."""
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest
import cv2


def padded_disk():
    image = np.zeros((1000, 1800, 3), np.uint8)
    cv2.circle(image, (1000, 550), 150, (170, 170, 170), -1)
    return image


def test_compact_field_preserves_pixels_and_rejects_unsafe_crops():
    from moonlabeler.atlas import _compact_lunar_field
    image = padded_disk()
    field, (x, y) = _compact_lunar_field(image)
    assert field.shape[0] < 450 and field.shape[1] < 450
    assert np.array_equal(field, image[y:y+field.shape[0], x:x+field.shape[1]])
    assert _compact_lunar_field(field) is None  # Normal lunar framing.
    assert _compact_lunar_field(np.zeros_like(image)) is None
    multiple = image.copy()
    cv2.circle(multiple, (350, 550), 150, (170, 170, 170), -1)
    assert _compact_lunar_field(multiple) is None
    clipped = np.zeros_like(image)
    cv2.circle(clipped, (10, 550), 150, (170, 170, 170), -1)
    assert _compact_lunar_field(clipped) is None


def test_compact_field_restores_radial_projection_coordinates(monkeypatch):
    from moonlabeler import atlas
    from moonlabeler.eyepiece import distort_points
    from moonlabeler.identification import IdentificationResult
    image = padded_disk()
    _, origin = atlas._compact_lunar_field(image)
    matrix = np.array([[150., 0., 190.], [0., 150., 190.]])
    distortion = {'center': [195., 185.], 'scale': 210., 'k': .1}
    result = IdentificationResult(matrix.copy(), [], 1., 100., 0,
                                  lens_distortion=distortion)
    monkeypatch.setattr(atlas, '_identify_atlas_field', lambda *args, **kwargs: result)
    actual = atlas.identify_from_atlas(image, None)
    points = np.array([[150., 150.], [230., 240.]])
    assert np.allclose(actual.matrix[:, 2], matrix[:, 2]+origin)
    assert np.allclose(distort_points(points+origin, actual.lens_distortion),
                       distort_points(points, distortion)+origin)


@pytest.mark.parametrize('allow_eyepiece', [False, True])
def test_failed_compact_search_falls_back_to_full_frame(monkeypatch, allow_eyepiece):
    from moonlabeler import atlas
    from moonlabeler.identification import IdentificationError
    image = padded_disk()
    calls = []
    def identify(field, geometry, **options):
        calls.append((field.shape, options['allow_eyepiece']))
        if field is not image:
            raise IdentificationError('No validated match')
        return 'full-frame result'
    monkeypatch.setattr(atlas, '_identify_atlas_field', identify)
    assert atlas.identify_from_atlas(image, None, allow_eyepiece=allow_eyepiece) == 'full-frame result'
    assert len(calls) == 2 and calls[-1][0] == image.shape
    assert all(enabled == allow_eyepiece for _, enabled in calls)


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('rotation', [0, 1])
def test_border_caption_does_not_hide_compact_moon(top, rotation):
    from moonlabeler.atlas import _compact_lunar_field
    image = padded_disk()
    captioned = image.copy()
    cv2.putText(captioned, 'DWARF Moon 2025', (80, 80 if top else 950),
                cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)
    image = np.rot90(image, rotation).copy()
    captioned = np.rot90(captioned, rotation).copy()
    expected, origin = _compact_lunar_field(image)
    result = _compact_lunar_field(captioned)
    assert result is not None
    assert np.array_equal(result[0], expected)
    assert np.array_equal(result[1], origin)


def test_border_caption_does_not_license_discarding_another_moon():
    from moonlabeler.atlas import _compact_lunar_field
    image = padded_disk()
    cv2.circle(image, (200, 100), 65, (170, 170, 170), -1)
    cv2.putText(image, 'DWARF Moon 2025', (80, 950),
                cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)
    assert _compact_lunar_field(image) is None


def test_interior_caption_is_not_silently_discarded():
    from moonlabeler.atlas import _compact_lunar_field
    image = padded_disk()
    cv2.putText(image, 'DWARF Moon 2025', (80, 350),
                cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)
    assert _compact_lunar_field(image) is None


def test_large_isolated_border_logo_is_not_assumed_to_be_text():
    from moonlabeler.atlas import _compact_lunar_field
    image = padded_disk()
    cv2.rectangle(image, (80, 50), (200, 100), (255, 255, 255), -1)
    assert _compact_lunar_field(image) is None


@pytest.mark.parametrize('caption', [False, True])
def test_dwarf_small_moon_registers_in_original_canvas_coordinates(caption):
    from moonlabeler.atlas import identify_from_atlas
    from moonlabeler.geometry import compute_geometry
    from moonlabeler.sources import read_image
    root = Path(__file__).parents[1]
    path = root/'DWARF_RAW_TELE_Moon_EXP_0.005_GAIN_0_2025-01-12-00-38-40-435_lapl2_ap65_pi.tif'
    if not path.exists() or not (root/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local photographer image and ephemerides required')
    # Photographer confirms filename uses Beijing time; UTC crosses midnight.
    geometry = compute_geometry(datetime(2025, 1, 11, 16, 38, 40, 435000, tzinfo=timezone.utc), root/'.cache/ephemeris')
    image = read_image(path)
    if caption:
        cv2.putText(image, 'DWARF Moon 2025', (100, image.shape[0]-100),
                    cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 6)
    result = identify_from_atlas(image, geometry)
    assert result.image_inliers > 300
    assert result.rms_px < 1.5
    assert np.linalg.norm(result.matrix[:, 2]-[1813, 1090]) < 4
    assert np.linalg.norm(result.matrix[:, 0]) == pytest.approx(348, abs=4)
    assert result.lens_distortion is None
