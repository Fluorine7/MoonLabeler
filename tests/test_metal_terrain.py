# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""CPU fallback and independent numerical checks for the optional Metal path."""
import numpy as np
import pytest

from moonlabeler.geometry import Geometry
from moonlabeler.terrain import ElevationMap
from moonlabeler.terrain import shade_atlas_points
from moonlabeler import terrain_identification as terrain
from moonlabeler import terrain_metal


def fixture():
    y, x = np.mgrid[:180, :360]
    heights = (2*np.sin(x*.12)*np.cos(y*.08)).astype(np.float32)
    dem = ElevationMap(heights, 90, 0, 1)
    view = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                    np.array([.3, np.sqrt(.91), 0]), 384400, '2026-01-01T00:00:00+00:00')
    return dem, view


def test_forced_cpu_does_not_initialize_metal(monkeypatch):
    monkeypatch.setenv('MOONLABELER_COMPUTE', 'cpu')
    def forbidden(*args):
        pytest.fail('CPU mode must not initialize Metal')
    monkeypatch.setattr(terrain_metal, '_render', forbidden)
    dem, view = fixture()
    image, projection = terrain.render_terrain_atlas(dem, view, 80)
    expected, matrix = terrain._render_terrain_atlas_cpu(dem, view, 80)
    np.testing.assert_array_equal(image, expected)
    np.testing.assert_array_equal(projection, matrix)


def test_gpu_failure_falls_back_to_cpu(monkeypatch):
    monkeypatch.setenv('MOONLABELER_COMPUTE', 'auto')
    monkeypatch.setattr(terrain_metal, '_eligible', lambda dem, size: True)
    monkeypatch.setattr(terrain_metal, '_disabled', False)
    def failed(*args):
        raise RuntimeError('Metal unavailable')
    monkeypatch.setattr(terrain_metal, '_render', failed)
    dem, view = fixture()
    image, _ = terrain.render_terrain_atlas(dem, view, 80)
    expected, _ = terrain._render_terrain_atlas_cpu(dem, view, 80)
    np.testing.assert_array_equal(image, expected)
    assert terrain_metal._disabled


@pytest.mark.parametrize('in_worker', [False, True])
def test_real_metal_shading_agrees_with_cpu(in_worker):
    try:
        mx = terrain_metal._load_mlx()
    except ImportError:
        pytest.skip('MLX / Metal unavailable')
    if not mx.metal.is_available():
        pytest.skip('Metal unavailable')
    dem, view = fixture()
    if in_worker:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as worker:
            actual, matrix = worker.submit(terrain_metal._render, dem, view, 256).result()
    else:
        actual, matrix = terrain_metal._render(dem, view, 256)
    expected, projection = terrain._render_terrain_atlas_cpu(dem, view, 256)
    np.testing.assert_array_equal(matrix, projection)
    delta = np.abs(actual.astype(float)-expected)
    assert delta.mean() < .1
    assert np.mean(delta > 2) < .001


def test_metal_preserves_dem_subpixel_positions():
    """Large DEM indices must not swallow the fractional sample position."""
    try:
        mx = terrain_metal._load_mlx()
    except ImportError:
        pytest.skip('MLX / Metal unavailable')
    if not mx.metal.is_available():
        pytest.skip('Metal unavailable')
    # Integer elevation samples and 16 pixels/degree, like the coarse LOLA map.
    y = np.arange(2880, dtype=np.float32)[:, None]
    x = np.arange(5760, dtype=np.float32)[None, :]
    heights = (2000*np.sin(x*.13)*np.cos(y*.11)).astype(np.int16)
    dem = ElevationMap(heights, 90, 0, 16, .0005)
    _, view = fixture()
    rng = np.random.default_rng(64)
    lat, lon = rng.uniform(-80, 80, 4096), rng.uniform(-80, 80, 4096)
    # One strip of independent probe rays exercises the production kernel.
    view.unproject = lambda points: (lat, lon, np.ones(len(lat), bool))
    actual, _ = terrain_metal._render(dem, view, 64)
    expected = shade_atlas_points(dem, view, lat, lon).reshape(64, 64)
    np.testing.assert_array_equal(actual, expected)
