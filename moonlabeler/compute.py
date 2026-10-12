# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Local compute policy and optional backends. Importing this needs no GPU SDK."""
import logging
import os
import threading

MODES = ('auto', 'cpu')
_mode = 'auto'
_lock = threading.RLock()
_wgpu_disabled = False
_last_backend = None
_LOG = logging.getLogger(__name__)


def normalize_mode(mode):
    # 0.6.5 preferences/environment used "metal"; migrate it to Auto.
    return 'auto' if mode == 'metal' else mode


def environment_override():
    return normalize_mode(os.environ.get('MOONLABELER_COMPUTE', '').lower()) in MODES


def configured_mode():
    override = normalize_mode(os.environ.get('MOONLABELER_COMPUTE', '').lower())
    return override if override in MODES else _mode


def set_mode(mode):
    global _mode
    mode = normalize_mode(mode)
    if mode not in MODES:
        raise ValueError(f'Unknown compute mode: {mode}')
    with _lock:
        _mode = mode


def status(mode=None):
    """Probe on demand; CPU-only never initializes a GPU, even in the dialog."""
    if (mode or configured_mode()) == 'cpu':
        return 'CPU · GPU 加速已关闭'
    from . import terrain_wgpu, terrain_metal
    with _lock:
        if not _wgpu_disabled:
            available, detail = terrain_wgpu.support()
            if available:
                return f'可用设备：{detail}\n加速高程与阴影参考；其余步骤使用 CPU。'
        if not terrain_metal._disabled:
            available, _ = terrain_metal.metal_support()
            if available:
                return '可用设备：Apple GPU · MLX\n加速高程与阴影参考；其余步骤使用 CPU。'
    return '使用 CPU。未找到可用 GPU 或未安装 GPU 组件，安装方法见 README。'


def try_render(dem, geometry, size):
    global _wgpu_disabled, _last_backend
    if configured_mode() == 'cpu':
        _last_backend = 'CPU'
        return None
    from . import terrain_wgpu, terrain_metal
    with _lock:
        if not _wgpu_disabled and terrain_wgpu.eligible(dem, size):
            try:
                result = terrain_wgpu.render(dem, geometry, size)
                _last_backend = terrain_wgpu.support()[1]
                return result
            except Exception as exc:
                _wgpu_disabled = True
                _LOG.warning('WebGPU terrain unavailable; trying compatible backend: %s', exc)
        # Preserve the optional MLX install used by 0.6.4/0.6.5 users.
        result = terrain_metal.try_render(dem, geometry, size)
        _last_backend = 'Apple GPU · MLX' if result is not None else 'CPU'
        return result
