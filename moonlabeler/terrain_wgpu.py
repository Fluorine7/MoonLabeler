# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional native WebGPU compute on Metal, Vulkan and DirectX 12.

No display or browser is required. Only coarse DEM shading runs here;
projection and ambiguous pixels retain the CPU float64 implementation.
"""
from pathlib import Path
import threading

import numpy as np

from .geometry import MOON_RADIUS_KM
from .terrain import shade_atlas_points

_lock = threading.RLock()
_context = None
_failure = None


def _get_context():
    global _context, _failure
    with _lock:
        if _failure is not None:
            raise RuntimeError(_failure)
        if _context is None:
            try:
                import wgpu
                adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
                if adapter is None or adapter.info.get('adapter_type') not in ('IntegratedGPU', 'DiscreteGPU'):
                    raise RuntimeError('No hardware GPU available')
                device = adapter.request_device_sync(label='MoonLabeler terrain')
                shader = device.create_shader_module(code=(Path(__file__).parent/'data'/'terrain.wgsl').read_text())
                pipeline = device.create_compute_pipeline(layout='auto', compute={'module': shader, 'entry_point': 'main'})
                _context = (wgpu, adapter, device, pipeline)
            except Exception as exc:
                # Native imports/device creation must not be retried for every strip.
                _failure = str(exc)
                raise
        return _context


def support():
    try:
        _, adapter, _, _ = _get_context()
        info = adapter.info
        return True, f"{info.get('device') or info.get('description') or info.get('vendor') or 'GPU'} · {info.get('backend_type', 'WebGPU')}"
    except Exception:
        return False, '未找到可用 GPU，或未安装 GPU 组件。'


def eligible(dem, size):
    return (size >= 512 and getattr(dem, 'global_longitude', False)
            and dem.data.size*4 <= 64*1024*1024
            and np.isfinite(dem.maximum_height_km))


def render(dem, geometry, size):
    """Reuse fixed strip buffers; release all per-atlas GPU memory on failure too."""
    global _failure
    with _lock:
        try:
            return _render(dem, geometry, size)
        except Exception as exc:
            _failure = str(exc)
            raise


def _render(dem, geometry, size):
    wgpu, _, device, pipeline = _get_context()
    capacity = size*64
    byte_sizes = (dem.data.size*4, capacity*6*4, 27*4, capacity*4)
    limit = min(device.limits['max-storage-buffer-binding-size'], device.limits['max-buffer-size'])
    if max(byte_sizes) > limit or (capacity+255)//256 > device.limits['max-compute-workgroups-per-dimension']:
        raise RuntimeError('Terrain exceeds GPU buffer or dispatch limits')
    buffers = []
    try:
        for index, length in enumerate(byte_sizes):
            usage = wgpu.BufferUsage.STORAGE | (wgpu.BufferUsage.COPY_SRC if index == 3 else wgpu.BufferUsage.COPY_DST)
            buffers.append(device.create_buffer(size=length, usage=usage))
        group = device.create_bind_group(layout=pipeline.get_bind_group_layout(0), entries=[
            {'binding': i, 'resource': {'buffer': buffer, 'offset': 0, 'size': byte_sizes[i]}}
            for i, buffer in enumerate(buffers)])
        device.queue.write_buffer(buffers[0], 0, np.asarray(dem.data, dtype=np.float32))
        params = np.array([*dem.data.shape, dem.north, dem.west, dem.ppd, dem.scale,
                           MOON_RADIUS_KM, MOON_RADIUS_KM+dem.maximum_height_km,
                           *geometry.sun, *geometry.observer,
                           *np.geomspace(max(.01, dem.resolution_km*.75), 80., 12), 0], dtype=np.float32)
        scale, center = size*.47, (size-1)/2
        reference = np.zeros((size, size), np.uint8)
        probes = []
        for first in range(0, size, 64):
            x, y = np.meshgrid(np.arange(size), np.arange(first, min(size, first+64)))
            points = np.column_stack(((x.ravel()-center)/scale, (y.ravel()-center)/scale))
            lat, lon, disk = geometry.unproject(points)
            indices = np.flatnonzero(disk)
            if not len(indices):
                continue
            latitude, longitude = lat[indices], lon[indices]
            gx = ((longitude-dem.west) % 360)*dem.ppd-.5
            gy = (dem.north-latitude)*dem.ppd-.5
            ix, iy = np.floor(gx), np.floor(gy)
            coords = np.column_stack((latitude, longitude, ix, iy, gx-ix, gy-iy)).astype(np.float32)
            params[26] = len(indices)
            device.queue.write_buffer(buffers[1], 0, coords)
            device.queue.write_buffer(buffers[2], 0, params)
            encoder = device.create_command_encoder()
            compute = encoder.begin_compute_pass()
            compute.set_pipeline(pipeline)
            compute.set_bind_group(0, group)
            compute.dispatch_workgroups((len(indices)+255)//256)
            compute.end()
            device.queue.submit([encoder.finish()])
            output = np.frombuffer(device.queue.read_buffer(buffers[3], size=len(indices)*4), dtype=np.uint32)
            slab = reference[first:first+x.shape[0]].reshape(-1)
            slab[indices] = (output & 255).astype(np.uint8)
            uncertain = indices[(output & 256) != 0]
            if len(uncertain):
                slab[uncertain] = shade_atlas_points(dem, geometry, lat[uncertain], lon[uncertain])
            # Independent CPU checks across the disk catch unusable driver math.
            sample = indices[np.linspace(0, len(indices)-1, 4, dtype=int)]
            probes.append((lat[sample], lon[sample], slab[sample].copy()))
        if probes:
            latitude, longitude, actual = [np.concatenate(parts) for parts in zip(*probes)]
            expected = shade_atlas_points(dem, geometry, latitude, longitude)
            delta = np.abs(actual.astype(float)-expected)
            if delta.max() > 2 or delta.mean() > .1:
                raise RuntimeError('GPU shading disagrees with CPU verification')
        return reference, np.array([[scale, 0., center], [0., scale, center]])
    finally:
        for buffer in buffers:
            buffer.destroy()
