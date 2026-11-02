# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Hand off to a new GUI only after it acknowledges successful startup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal

from . import i18n
from .i18n import tr, trf

READY_ENV = 'MOONLABELER_RESTART_READY'


class RestartHandoff(QObject):
    ready = Signal()
    failed = Signal(object)

    def __init__(self, program, arguments, cwd, cache, language, parent=None, *, timeout=15):
        super().__init__(parent)
        self.program, self.arguments, self.cwd = program, arguments, cwd
        self.cache, self.language, self.timeout = Path(cache), language, timeout
        self.process = self.temporary = None
        self.error = None
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.poll)

    def start(self):
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            self.temporary = tempfile.TemporaryDirectory(prefix='restart-', dir=self.cache)
            self.marker = Path(self.temporary.name)/'ready.json'
            self.log = self.cache/'restart.log'
            environment = os.environ.copy()
            environment[READY_ENV] = str(self.marker)
            # An explicit UI choice must survive an inherited startup override.
            environment.pop(i18n.ENV_VARIABLE, None)
            if getattr(sys, 'frozen', False):
                environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
            flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
            with self.log.open('ab') as log:
                self.process = subprocess.Popen([self.program, *self.arguments], cwd=self.cwd,
                    env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=os.name != 'nt', creationflags=flags)
        except OSError as exc:
            self.error = exc
            self.cleanup()
            return False
        self.deadline = monotonic()+self.timeout
        self.timer.start()
        return True

    def poll(self):
        code = self.process.poll()
        if code is not None:
            self.fail(ValueError(trf('新窗口启动失败（退出代码 {code}）。启动日志：{path}', code=code, path=str(self.log))))
            return
        if self.marker.exists():
            try:
                result = json.loads(self.marker.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                self.fail(exc)
                return
            # A Windows venv python.exe is a redirector that runs the real interpreter as its
            # child, so the acknowledging process may be one level below the spawned one.
            spawned = isinstance(result, dict) and self.process.pid in (result.get('pid'), result.get('parent'))
            if not spawned or result.get('language') != self.language:
                self.fail(ValueError(tr('新窗口没有应用所选语言，已保留原窗口。')))
                return
            self.cleanup()
            self.ready.emit()
        elif monotonic() >= self.deadline:
            self.fail(ValueError(trf('等待新窗口启动超时，已保留原窗口。启动日志：{path}', path=str(self.log))))

    def cleanup(self):
        self.timer.stop()
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None

    def cancel(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        self.cleanup()

    def fail(self, problem):
        self.cancel()
        self.failed.emit(problem)


def acknowledge_startup(marker, window):
    """The parent owns the marker directory and removes it on cancellation."""
    if not marker:
        return
    from PySide6.QtWidgets import QApplication
    path = Path(marker)
    try:
        if not window.isVisible():
            raise OSError('Replacement window is not visible')
        temporary = path.with_suffix('.part')
        temporary.write_text(json.dumps({'pid': os.getpid(), 'parent': os.getppid(),
                                         'language': i18n.current_language()}), encoding='utf-8')
        temporary.replace(path)
    except OSError:
        # A timed-out/cancelled replacement must not appear later as a duplicate.
        QApplication.instance().exit(1)
