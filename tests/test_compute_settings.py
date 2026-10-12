# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from moonlabeler import terrain_metal
from moonlabeler.ui.compute import ComputeDialog


@pytest.fixture
def preferences(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.delenv('MOONLABELER_COMPUTE', raising=False)
    monkeypatch.setattr(terrain_metal, '_mode', 'auto')
    monkeypatch.setattr(terrain_metal, '_disabled', False)
    monkeypatch.setattr(terrain_metal, 'metal_support', lambda: (True, 'Apple GPU 可用'))
    yield QSettings(str(tmp_path/'preferences.ini'), QSettings.Format.IniFormat)


def test_save_cpu_survives_restart_and_bypasses_gpu(preferences, monkeypatch, tmp_path):
    dialog = ComputeDialog(preferences)
    dialog.mode.setCurrentIndex(dialog.mode.findData('cpu'))
    dialog.save()
    import moonlabeler.app as app
    monkeypatch.setattr(app, 'CACHE', tmp_path)
    terrain_metal.set_mode('auto')
    window = app.MainWindow()
    try:
        assert terrain_metal.configured_mode() == 'cpu'
        monkeypatch.setattr(terrain_metal, '_render', lambda *a: pytest.fail('GPU must stay off'))
        assert terrain_metal.try_render(None, None, 4000) is None
        assert any(a.text() == '计算设置' for a in window.actions)
    finally:
        window.dirty = False
        window.close()


def test_cancel_does_not_apply_or_save(preferences):
    dialog = ComputeDialog(preferences)
    dialog.mode.setCurrentIndex(1)
    dialog.reject()
    assert terrain_metal.configured_mode() == 'auto'
    assert not preferences.contains('compute/mode')


def test_environment_override_is_visible_and_does_not_replace_preference(preferences, monkeypatch):
    preferences.setValue('compute/mode', 'metal')
    terrain_metal.set_mode('metal')
    monkeypatch.setenv('MOONLABELER_COMPUTE', 'cpu')
    dialog = ComputeDialog(preferences)
    assert dialog.mode.currentData() == 'cpu'
    assert not dialog.mode.isEnabled()
    dialog.reject()
    assert preferences.value('compute/mode') == 'metal'


def test_unavailable_gpu_option_is_disabled(preferences, monkeypatch):
    monkeypatch.setattr(terrain_metal, 'metal_support', lambda: (False, '当前电脑使用 CPU'))
    dialog = ComputeDialog(preferences)
    assert not dialog.mode.model().item(2).isEnabled()
    assert dialog.mode.currentData() == 'auto'
    dialog.reject()


@pytest.mark.parametrize('system,machine', [('Windows','AMD64'),('Linux','x86_64'),('Darwin','x86_64')])
def test_other_platforms_use_cpu_without_mlx(system, machine, monkeypatch):
    monkeypatch.delenv('MOONLABELER_COMPUTE', raising=False)
    monkeypatch.setattr(terrain_metal, '_mode', 'metal')
    monkeypatch.setattr(terrain_metal.platform, 'system', lambda: system)
    monkeypatch.setattr(terrain_metal.platform, 'machine', lambda: machine)
    monkeypatch.setattr(terrain_metal, '_render', lambda *a: pytest.fail('Unsupported GPU called'))
    supported, reason = terrain_metal.metal_support()
    assert not supported and 'CPU' in reason
    assert terrain_metal.try_render(None, None, 4000) is None


def test_failed_native_import_is_not_retried(monkeypatch):
    import builtins
    original = builtins.__import__
    attempts = []
    def unavailable(name, *args, **kwargs):
        if name == 'mlx.core':
            attempts.append(name)
            raise ImportError('No Metal device')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', unavailable)
    monkeypatch.setattr(terrain_metal, '_mlx', None)
    monkeypatch.setattr(terrain_metal, '_mlx_error', None)
    for _ in range(2):
        with pytest.raises(ImportError, match='No Metal device'):
            terrain_metal._load_mlx()
    assert len(attempts) == 1
