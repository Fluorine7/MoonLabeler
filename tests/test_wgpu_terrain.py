# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest

from moonlabeler import compute, terrain_wgpu, terrain_metal
from moonlabeler.terrain import ElevationMap, shade_atlas_points
from moonlabeler.terrain_identification import render_terrain_atlas, _render_terrain_atlas_cpu
from test_metal_terrain import fixture


@pytest.fixture
def gpu():
    supported, detail = terrain_wgpu.support()
    if not supported:
        if os.environ.get('MOONLABELER_TEST_GPU') == '1':
            pytest.fail(f'GPU required for this run: {terrain_wgpu._failure}')
        pytest.skip(detail)
    return terrain_wgpu


@pytest.mark.parametrize('worker', [False, True])
def test_real_wgpu_matches_cpu_with_partial_strip(gpu, worker):
    dem, view = fixture()
    if worker:
        with ThreadPoolExecutor(max_workers=1) as pool:
            actual, matrix = pool.submit(gpu.render, dem, view, 269).result()
    else:
        actual, matrix = gpu.render(dem, view, 269)
    expected, projection = _render_terrain_atlas_cpu(dem, view, 269)
    np.testing.assert_array_equal(matrix, projection)
    delta = np.abs(actual.astype(float)-expected)
    assert delta.mean() < .1
    assert np.mean(delta > 2) < .001


def test_wgpu_preserves_dem_subpixel_positions(gpu):
    y = np.arange(2880, dtype=np.float32)[:, None]
    x = np.arange(5760, dtype=np.float32)[None, :]
    dem = ElevationMap((2000*np.sin(x*.13)*np.cos(y*.11)).astype(np.int16), 90, 0, 16, .0005)
    _, view = fixture()
    rng = np.random.default_rng(64)
    lat, lon = rng.uniform(-80, 80, 4096), rng.uniform(-80, 80, 4096)
    view.unproject = lambda points: (lat, lon, np.ones(len(lat), bool))
    actual, _ = gpu.render(dem, view, 64)
    expected = shade_atlas_points(dem, view, lat, lon).reshape(64, 64)
    np.testing.assert_array_equal(actual, expected)


def test_cpu_mode_never_calls_backends(monkeypatch):
    monkeypatch.setenv('MOONLABELER_COMPUTE', 'cpu')
    for backend, name in [(terrain_wgpu, 'render'), (terrain_metal, 'try_render')]:
        monkeypatch.setattr(backend, name, lambda *a: pytest.fail('GPU must remain off'))
    dem, view = fixture()
    actual, _ = render_terrain_atlas(dem, view, 80)
    expected, _ = _render_terrain_atlas_cpu(dem, view, 80)
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('error', [ImportError('not installed'), RuntimeError('device lost'), MemoryError('GPU memory')])
def test_failure_falls_back_once_and_does_not_change_results(monkeypatch, error):
    monkeypatch.setenv('MOONLABELER_COMPUTE', 'auto')
    monkeypatch.setattr(compute, '_wgpu_disabled', False)
    monkeypatch.setattr(terrain_wgpu, 'eligible', lambda *a: True)
    monkeypatch.setattr(terrain_metal, 'try_render', lambda *a: None)
    calls = []
    def failed(*args):
        calls.append(1)
        raise error
    monkeypatch.setattr(terrain_wgpu, 'render', failed)
    dem, view = fixture()
    expected, _ = _render_terrain_atlas_cpu(dem, view, 80)
    for _ in range(2):
        actual, _ = render_terrain_atlas(dem, view, 80)
        np.testing.assert_array_equal(actual, expected)
    assert len(calls) == 1
    assert compute._last_backend == 'CPU'


@pytest.mark.parametrize('backend', ['Metal', 'Vulkan', 'D3D12'])
def test_policy_uses_available_gpu_without_platform_filter(monkeypatch, backend):
    monkeypatch.setenv('MOONLABELER_COMPUTE', 'auto')
    monkeypatch.setattr(compute, '_wgpu_disabled', False)
    monkeypatch.setattr(terrain_wgpu, 'eligible', lambda *a: True)
    expected = object()
    monkeypatch.setattr(terrain_wgpu, 'render', lambda *a: expected)
    monkeypatch.setattr(terrain_wgpu, 'support', lambda: (True, 'Test GPU · '+backend))
    monkeypatch.setattr(terrain_metal, 'try_render', lambda *a: pytest.fail('Legacy fallback should not run'))
    assert compute.try_render(None, None, 512) is expected
    assert backend in compute._last_backend


def test_software_adapter_is_not_mistaken_for_gpu(monkeypatch):
    import sys
    attempts = []
    def adapter(**kwargs):
        attempts.append(1)
        return SimpleNamespace(info={'adapter_type': 'CPU'})
    monkeypatch.setitem(sys.modules, 'wgpu', SimpleNamespace(gpu=SimpleNamespace(request_adapter_sync=adapter)))
    monkeypatch.setattr(terrain_wgpu, '_context', None)
    monkeypatch.setattr(terrain_wgpu, '_failure', None)
    for _ in range(2):
        assert terrain_wgpu.support()[0] is False
    assert len(attempts) == 1


def test_oversized_and_nonfinite_dem_stay_on_cpu():
    dem, _ = fixture()
    dem.data[0, 0] = np.nan
    assert not terrain_wgpu.eligible(dem, 4000)
    oversized = SimpleNamespace(global_longitude=True, data=SimpleNamespace(size=64*1024*1024))
    assert not terrain_wgpu.eligible(oversized, 4000)
