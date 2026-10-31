# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""A spawned process is not evidence that a replacement window is ready."""
import os
import sys
from time import monotonic
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from moonlabeler import app as app_module
from moonlabeler.restart import RestartHandoff


def test_failed_child_startup_keeps_the_old_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    # The interpreter starts successfully, then the application's import fails.
    package = tmp_path/'moonlabeler'
    package.mkdir()
    (package/'__init__.py').write_text('', encoding='utf-8')
    (package/'__main__.py').write_text('raise RuntimeError("simulated startup failure")\n', encoding='utf-8')
    monkeypatch.setattr(app_module, 'ROOT', tmp_path)
    monkeypatch.setattr(app_module, 'CACHE', tmp_path/'cache')
    monkeypatch.setenv('PYTHONPATH', str(tmp_path))
    window = app_module.MainWindow()
    errors = []
    window.error = errors.append
    window.show()
    app.processEvents()
    try:
        window.restart_requested = True
        window.close()
        deadline = monotonic()+3
        while not errors and monotonic() < deadline:
            QTest.qWait(10)
        assert window.isVisible(), 'A failed replacement must not leave the user with no window'
        assert errors and window.isEnabled()
        assert 'simulated startup failure' in (tmp_path/'cache/restart.log').read_text(encoding='utf-8')
    finally:
        window.dirty = False
        window.restart_requested = False
        window.close()


@pytest.mark.parametrize('mode', ['ready', 'wrong_language', 'stranger', 'timeout'])
def test_real_child_readiness_and_failure_handling(tmp_path, mode):
    app = QApplication.instance() or QApplication([])
    # sys.executable may be a Windows venv redirector whose child writes the marker.
    script = '''
import json, os, time
from pathlib import Path
from moonlabeler import i18n
language = i18n.initialize('en')
mode = {mode!r}
if mode != 'timeout':
    path = Path(os.environ['MOONLABELER_RESTART_READY'])
    temporary = path.with_suffix('.part')
    owner = {{'pid': 0, 'parent': 0}} if mode == 'stranger' else {{'pid': os.getpid(), 'parent': os.getppid()}}
    owner['language'] = 'zh-CN' if mode == 'wrong_language' else language
    temporary.write_text(json.dumps(owner), encoding='utf-8')
    temporary.replace(path)
time.sleep(10)
'''.format(mode=mode)
    handoff = RestartHandoff(sys.executable, ['-c', script], str(app_module.ROOT), tmp_path, 'en',
                             timeout=.15 if mode == 'timeout' else 3)
    ready, errors = [], []
    handoff.ready.connect(lambda: ready.append(True))
    handoff.failed.connect(errors.append)
    try:
        assert handoff.start()
        marker = handoff.marker
        deadline = monotonic()+4
        while not ready and not errors and monotonic() < deadline:
            QTest.qWait(10)
        assert bool(ready) == (mode == 'ready')
        assert bool(errors) == (mode != 'ready')
        assert not marker.exists() and not marker.parent.exists()
        assert not handoff.timer.isActive()
    finally:
        handoff.cancel()
        if handoff.process is not None:
            handoff.process.wait(timeout=3)


def test_old_window_closes_only_after_acknowledgement(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, 'CACHE', tmp_path)
    monkeypatch.setattr(RestartHandoff, 'start', lambda self: True)
    window = app_module.MainWindow()
    approvals = []
    window.confirm_discard = lambda: approvals.append(True) or True
    window.show()
    app.processEvents()
    try:
        window.restart_requested = True
        window.close()
        assert window.isVisible() and not window.isEnabled()
        handoff = window._restart_handoff
        handoff.ready.emit()
        app.processEvents()
        assert not window.isVisible()
        assert approvals == [True], 'The save/discard decision must not be repeated after startup'
    finally:
        window.dirty = False
        window.close()
