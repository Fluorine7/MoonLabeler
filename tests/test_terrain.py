# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from pathlib import Path

import numpy as np
import pytest

from moonlabeler.geometry import Geometry, surface_vectors
from moonlabeler.terrain import ElevationMap, render_region, terrain_shadow


def geometry(sun=(.8, .6, 0)):
    return Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                    np.array(sun), 384400, "2026-01-01T00:00:00+00:00")


def test_finite_distance_projection_roundtrip_and_off_disk():
    view = geometry()
    lat = np.array([-65., 0, 32, 70])
    lon = np.array([-32., 0, 60, -40])
    points, visible, _ = view.project(lat, lon)
    restored_lat, restored_lon, valid = view.unproject(points)
    assert visible.all() and valid.all()
    assert np.allclose(restored_lat, lat, atol=1e-8)
    assert np.allclose(restored_lon, lon, atol=1e-8)
    bad_lat, bad_lon, valid = view.unproject([[2., 0]])
    assert not valid[0] and np.isnan(bad_lat[0]) and np.isnan(bad_lon[0])


def test_pds_lola_pixel_centers_height_units_and_truncation(tmp_path):
    # Same conventions as the official LDEM_16 label; small regional fixture.
    data = np.arange(8, dtype="<i2").reshape(2, 4)*100
    data.tofile(tmp_path/"test.img")
    label = '''INSTRUMENT_ID = LOLA
TARGET_NAME = MOON
MAP_PROJECTION_TYPE = "SIMPLE CYLINDRICAL"
POSITIVE_LONGITUDE_DIRECTION = "EAST"
MAP_PROJECTION_ROTATION = 0
COORDINATE_SYSTEM_NAME = "MEAN EARTH/POLAR AXIS OF DE421"
UNIT = METER
OFFSET = 1737400.
SAMPLE_BITS = 16
SAMPLE_TYPE = LSB_INTEGER
^IMAGE = "TEST.IMG"
LINES = 2
LINE_SAMPLES = 4
MAP_RESOLUTION = 2 <pix/deg>
MAXIMUM_LATITUDE = 1
MINIMUM_LATITUDE = 0
WESTERNMOST_LONGITUDE = 359
EASTERNMOST_LONGITUDE = 1
SCALING_FACTOR = 0.5
PRODUCT_ID = "REGIONAL_TEST"
'''
    path = tmp_path/"test.lbl"
    path.write_text(label)
    dem = ElevationMap.load(path)
    try:
        assert dem.sample([.75, .75], [-.75, -.25]) == pytest.approx([0, .05])
        assert dem.sample([.5], [-.5]) == pytest.approx([.125])
        assert np.isnan(dem.sample([2], [0]))[0]
    finally:
        dem.close()
    (tmp_path/"test.img").write_bytes(b"123")
    with pytest.raises(ValueError, match="长度"):
        ElevationMap.load(path)


def test_global_longitude_wrap_interpolates_seam():
    data = np.tile(np.arange(8, dtype=float), (4, 1))
    dem = ElevationMap(data, 90, 0, 8/360)
    assert dem.sample([0, 0], [0, 360]) == pytest.approx([3.5, 3.5])
    assert dem.sample([0, 0], [-22.5, 337.5]) == pytest.approx([7, 7])


@pytest.mark.parametrize("model", ["Lambert", "Lommel-Seeliger"])
def test_flat_surface_has_radial_normals_and_expected_photometry(model):
    dem = ElevationMap(np.zeros((512, 512)), 2, -2, 128)
    normals = dem.normals(np.array([0., 1.]), np.array([0., 1.]))
    assert np.allclose(normals, surface_vectors([0, 1], [0, 1]))
    result = render_region(dem, geometry(), 0, 0, width_km=80, size=128,
                           model=model, gamma=1, shadows=False)
    assert result.image.shape == (128, 128, 3)
    assert result.valid_fraction == 1
    assert int(result.image[64, 64, 0]) == pytest.approx(204, abs=2)
    center, _, _ = geometry().project([0], [0])
    assert np.allclose(center @ result.matrix[:, :2].T + result.matrix[:, 2], [[64., 64.]])
    dark = render_region(dem, geometry((-1., 0, 0)), 0, 0, 80, 128, shadows=False)
    assert not dark.image.any()


def test_terrain_casts_shadow_at_low_sun_and_clears_at_high_sun():
    ppd = 128
    longitude = -2+(np.arange(512)+.5)/ppd
    data = np.zeros((512, 512))
    data[:, (longitude > .3) & (longitude < .8)] = 2  # 2 km ridge, east of observer point
    dem = ElevationMap(data, 2, -2, ppd)
    radial = surface_vectors([0], [0])
    low = np.array([np.sin(np.radians(5)), np.cos(np.radians(5)), 0])
    high = np.array([np.sin(np.radians(45)), np.cos(np.radians(45)), 0])
    assert terrain_shadow(dem, radial, np.array([0.]), low, steps=96, maximum_km=40)[0]
    assert not terrain_shadow(dem, radial, np.array([0.]), high, steps=96, maximum_km=40)[0]


def test_outward_sun_rays_above_dem_bound_need_no_further_samples():
    from types import SimpleNamespace
    sampled = []
    def sample(lat, lon):
        sampled.append(len(lat))
        return np.zeros_like(lat)
    dem = SimpleNamespace(sample=sample, maximum_height_km=0., resolution_km=1.)
    assert not terrain_shadow(dem, np.array([[1., 0., 0.]]), np.array([0.]), np.array([1., 0., 0.]))[0]
    assert not sampled
    # A ray above the same bound but heading inward can still hit terrain.
    assert terrain_shadow(dem, np.array([[1., 0., 0.]]), np.array([5.]), np.array([-1., 0., 0.]))[0]
    assert sum(sampled) < 32


def test_renderer_rejects_missing_coverage_and_near_limb():
    dem = ElevationMap(np.zeros((512, 512)), 2, -2, 128)
    with pytest.raises(ValueError, match="不覆盖"):
        render_region(dem, geometry(), 10, 10)
    with pytest.raises(ValueError, match="月缘"):
        render_region(dem, geometry(), 0, 85)


def test_actual_cached_lola_data_is_usable():
    path = Path(__file__).parents[1]/".cache/terrain/LDEM_16.LBL"
    if not path.with_suffix(".IMG").exists():
        pytest.skip("Real LOLA DEM is optional; unit tests remain offline")
    dem = ElevationMap.load(path)
    try:
        assert dem.resolution_km == pytest.approx(1.8952, abs=.001)
        height = dem.sample([23.73, 0, -20], [-47.49, 0, 30])
        assert np.isfinite(height).all() and (np.abs(height) < 12).all()
        image = render_region(dem, geometry(), 0, -10, width_km=500, size=128, shadows=True)
        assert image.valid_fraction > .95 and image.image.max() > 100
    finally:
        dem.close()
