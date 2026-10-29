# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Cancellation through the real GUI worker and cached download boundary."""
import os
from io import BytesIO
from threading import Event
from time import monotonic

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest

from moonlabeler import app as app_module
from moonlabeler import sources
from moonlabeler.tasks import TaskCancelled, cancellable_task


def wait_until(app, predicate, timeout=3):
    deadline = monotonic()+timeout
    while not predicate() and monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def test_close_during_download_cancels_without_applying_result(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, 'CACHE', tmp_path)
    entered, release = Event(), Event()
    response = BytesIO(b'downloaded')
    response.headers = {'Content-Length': '10'}

    def stalled_connection(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return response

    monkeypatch.setattr(sources, 'urlopen', stalled_connection)
    window = app_module.MainWindow()
    window.show()
    accepted, errors = [], []
    destination = tmp_path/'terrain.img'
    try:
        window.run_background('Downloading', lambda: sources.download('https://example.org/data', destination),
                              accepted.append, errors.append)
        wait_until(app, entered.is_set)
        window.close()
        # Closing must work even while the transport remains stalled.
        wait_until(app, lambda: not window.isVisible(), timeout=1)
        assert not accepted and not errors
        assert not destination.exists()
    finally:
        release.set()
        wait_until(app, lambda: not window.busy)
        QThreadPool.globalInstance().waitForDone(3000)
        window.dirty = False
        window.close()


@pytest.mark.parametrize('stage', ['connect', 'read'])
def test_cancel_button_preserves_cache_and_allows_retry(tmp_path, monkeypatch, stage):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, 'CACHE', tmp_path)
    entered, release, exited = Event(), Event(), Event()

    class StalledResponse(BytesIO):
        headers = {'Content-Length': '3'}

        def read1(self, size):
            entered.set()
            assert release.wait(3)
            return super().read1(size)

        def close(self):
            super().close()
            exited.set()

    response = StalledResponse(b'new')

    def connect(*args, **kwargs):
        if stage == 'connect':
            entered.set()
            assert release.wait(3)
        return response

    monkeypatch.setattr(sources, 'urlopen', connect)
    window = app_module.MainWindow()
    window.show()
    target = tmp_path/'reference.img'
    target.write_bytes(b'previous complete data')
    accepted, errors = [], []
    try:
        window.run_background('Download', lambda: sources.download('https://example.org/data', target, force=True),
                              accepted.append, errors.append)
        wait_until(app, entered.is_set)
        assert window.cancel_task_button.isVisible() and window.cancel_task_button.isEnabled()
        window.cancel_task_button.click()
        wait_until(app, lambda: not window.busy, timeout=1)
        assert target.read_bytes() == b'previous complete data'
        assert not target.with_suffix('.img.part').exists()
        assert not accepted and not errors
        assert window.toolbar.isEnabled() and window.sidebar.isEnabled()
        fresh = BytesIO(b'new')
        fresh.headers = {'Content-Length': '3'}
        monkeypatch.setattr(sources, 'urlopen', lambda *args, **kwargs: fresh)
        window.run_background('Retry', lambda: sources.download('https://example.org/data', target, force=True),
                              accepted.append, errors.append)
        wait_until(app, lambda: not window.busy)
        release.set()
        wait_until(app, exited.is_set)
        assert target.read_bytes() == b'new' and accepted == [target] and not errors
    finally:
        release.set()
        wait_until(app, lambda: not window.busy)
        window.dirty = False
        window.close()


def test_missing_ephemeris_uses_cancellable_downloader(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from moonlabeler.geometry import compute_geometry
    seen = []

    def cancel_download(url, destination):
        seen.append((url, destination))
        raise TaskCancelled()

    monkeypatch.setattr(sources, 'download', cancel_download)
    with pytest.raises(TaskCancelled):
        compute_geometry(datetime(2025, 5, 3, tzinfo=timezone.utc), tmp_path)
    assert len(seen) == 1 and seen[0][1].name == 'de421.bsp'


def test_cancelled_cached_download_does_not_start_network(tmp_path, monkeypatch):
    target = tmp_path/'existing'
    target.write_bytes(b'valid')
    cancel = Event()
    with cancellable_task(cancel):
        cancel.set()
        with pytest.raises(TaskCancelled):
            sources.download('https://example.org/data', target)
        cancel.clear()
