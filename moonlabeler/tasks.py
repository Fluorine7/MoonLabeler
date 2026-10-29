# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Cooperative cancellation shared by background work and data downloads."""
from contextlib import contextmanager
from contextvars import ContextVar


class TaskCancelled(Exception):
    """A user cancellation, distinct from recognition and download failures."""


_cancellation = ContextVar('moonlabeler_cancellation', default=None)


def cancellation_event():
    return _cancellation.get()


def check_cancelled():
    event = cancellation_event()
    if event is not None and event.is_set():
        raise TaskCancelled()


@contextmanager
def cancellable_task(event):
    token = _cancellation.set(event)
    try:
        check_cancelled()
        yield
        check_cancelled()
    finally:
        _cancellation.reset(token)
