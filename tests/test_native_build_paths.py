# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest

from native import build_opencv


def test_ascii_build_path_is_preserved(tmp_path):
    assert build_opencv.ascii_build_dir(tmp_path) == tmp_path


def test_non_ascii_checkout_uses_separate_ascii_build_directories(tmp_path, monkeypatch):
    monkeypatch.setenv('MOONLABELER_OPENCV_BUILD_ROOT', str(tmp_path))
    first = build_opencv.ascii_build_dir(Path('中文目录')/'build')
    second = build_opencv.ascii_build_dir(Path('中文目录')/'build')
    assert first != second
    assert first.is_dir() and second.is_dir()
    assert first.parent == second.parent == tmp_path.resolve()
    assert str(first).isascii() and str(second).isascii()


def test_non_ascii_temp_directory_requires_an_ascii_override(tmp_path, monkeypatch):
    monkeypatch.delenv('MOONLABELER_OPENCV_BUILD_ROOT', raising=False)
    monkeypatch.setattr(build_opencv.tempfile, 'gettempdir', lambda: str(tmp_path/'用户'))
    with pytest.raises(RuntimeError, match='MOONLABELER_OPENCV_BUILD_ROOT'):
        build_opencv.ascii_build_dir(Path('中文目录')/'build')

