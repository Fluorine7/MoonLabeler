# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from moonlabeler import terrain_metal, compute
from moonlabeler.ui.compute import ComputeDialog


@pytest.fixture
def preferences(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.delenv('MOONLABELER_COMPUTE', raising=False)
    monkeypatch.setattr(compute, '_mode', 'auto')
    monkeypatch.setattr(terrain_metal, '_disabled', False)
    monkeypatch.setattr(compute, 'status', lambda mode=None: '可用设备：Test GPU · Vulkan')
    yield QSettings(str(tmp_path/'preferences.ini'), QSettings.Format.IniFormat)


def test_save_cpu_survives_restart_and_bypasses_gpu(preferences, monkeypatch, tmp_path):
    dialog = ComputeDialog(preferences)
    dialog.mode.setCurrentIndex(dialog.mode.findData('cpu'))
    dialog.save()
    import moonlabeler.app as app
    monkeypatch.setattr(app, 'CACHE', tmp_path)
    compute.set_mode('auto')
    window = app.MainWindow()
    try:
        assert compute.configured_mode() == 'cpu'
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
    assert compute.configured_mode() == 'auto'
    assert not preferences.contains('compute/mode')


def test_environment_override_is_visible_and_does_not_replace_preference(preferences, monkeypatch):
    preferences.setValue('compute/mode', 'metal')
    compute.set_mode('metal')
    monkeypatch.setenv('MOONLABELER_COMPUTE', 'cpu')
    dialog = ComputeDialog(preferences)
    assert dialog.mode.currentData() == 'cpu'
    assert not dialog.mode.isEnabled()
    dialog.reject()
    assert preferences.value('compute/mode') == 'metal'


def test_auto_is_available_without_a_gpu(preferences, monkeypatch):
    monkeypatch.setattr(compute, 'status', lambda mode=None: '使用 CPU')
    dialog = ComputeDialog(preferences)
    assert dialog.mode.count() == 2
    assert dialog.mode.currentData() == 'auto'
    dialog.reject()


def test_legacy_metal_preference_migrates_to_auto(preferences):
    compute.set_mode('metal')
    dialog = ComputeDialog(preferences)
    assert dialog.mode.currentData() == 'auto'
    dialog.save()
    assert preferences.value('compute/mode') == 'auto'


def test_cpu_status_never_probes_gpu(monkeypatch):
    from moonlabeler import terrain_wgpu
    monkeypatch.setattr(terrain_wgpu, 'support', lambda: pytest.fail('GPU must stay off'))
    assert 'CPU' in compute.status('cpu')


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
