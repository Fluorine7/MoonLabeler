# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('native_ready', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_launcher_removes_old_codec_wheel_and_bootstraps_native_build(tmp_path, native_ready, legacy):
    zsh = shutil.which('zsh')
    if zsh is None:
        pytest.skip('The macOS launcher requires zsh')
    launcher = tmp_path/'start-mac.command'
    shutil.copyfile(Path(__file__).parents[1]/'start-mac.command', launcher)
    python = tmp_path/'.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('''#!/bin/sh
if [ "$1" = "-c" ]; then
    case "$2" in
        *m.distributions*) %s; exit 0 ;;
        *moonlabeler._opencv*) exit %d ;;
        *) exit 0 ;;
    esac
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    case "$*" in
        *--dry-run*) exit 0 ;;
        *uninstall*) echo REMOVE_OLD_OPENCV; exit 0 ;;
        *--no-deps*) echo BUILD_PRIVATE_OPENCV; exit 0 ;;
    esac
fi
echo RUN_MOONLABELER
''' % ('echo opencv-contrib-python-headless' if legacy else 'true', 0 if native_ready else 1), encoding='utf-8')
    python.chmod(0o755)
    outcome = subprocess.run([zsh, str(launcher)], capture_output=True, text=True, timeout=5)
    assert outcome.returncode == 0 and 'RUN_MOONLABELER' in outcome.stdout
    assert ('REMOVE_OLD_OPENCV' in outcome.stdout) == legacy
    assert ('BUILD_PRIVATE_OPENCV' in outcome.stdout) == (not native_ready)
