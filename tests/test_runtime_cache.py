# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from types import SimpleNamespace

import pytest

from moonlabeler import app


def test_source_cache_stays_with_the_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'sys', SimpleNamespace(platform='win32', frozen=False))
    monkeypatch.setattr(app, 'ROOT', tmp_path)
    assert app.default_cache() == tmp_path/'.cache'


@pytest.mark.parametrize(('platform', 'variable', 'suffix'), [
    ('win32', 'LOCALAPPDATA', 'MoonLabeler/cache'),
    ('linux', 'XDG_CACHE_HOME', 'MoonLabeler'),
])
def test_frozen_cache_uses_the_platform_user_directory(tmp_path, monkeypatch, platform, variable, suffix):
    monkeypatch.setattr(app, 'sys', SimpleNamespace(platform=platform, frozen=True))
    monkeypatch.setenv(variable, str(tmp_path))
    assert app.default_cache() == tmp_path/suffix


@pytest.mark.parametrize(('platform', 'suffix'), [
    ('win32', 'AppData/Local/MoonLabeler/cache'),
    ('darwin', 'Library/Caches/MoonLabeler'),
    ('linux', '.cache/MoonLabeler'),
])
def test_frozen_cache_has_a_user_home_fallback(monkeypatch, platform, suffix):
    monkeypatch.setattr(app, 'sys', SimpleNamespace(platform=platform, frozen=True))
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
    assert app.default_cache() == Path.home()/suffix

