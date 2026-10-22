# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Exercise launcher decisions without installing dependencies or deleting a venv."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('compatible', [False, True])
def test_launcher_checks_existing_virtualenv_python(tmp_path, compatible):
    zsh = shutil.which('zsh')
    if zsh is None:
        pytest.skip('The macOS launcher requires zsh')
    launcher = tmp_path / 'start-mac.command'
    shutil.copyfile(Path(__file__).parents[1] / 'start-mac.command', launcher)
    python = tmp_path / '.venv' / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.write_text('''#!/bin/sh
if [ "$1" = "-c" ]; then
    case "$2" in
        *sys.version_info*) exit %d ;;
        *) exit 0 ;;
    esac
fi
echo RUN_MOONLABELER
''' % (0 if compatible else 1))
    python.chmod(0o755)
    outcome = subprocess.run([zsh, str(launcher)], capture_output=True, text=True,
                             input='\n', timeout=5)
    if compatible:
        assert outcome.returncode == 0 and 'RUN_MOONLABELER' in outcome.stdout
    else:
        assert outcome.returncode != 0
        assert '3.12' in outcome.stdout
        assert 'RUN_MOONLABELER' not in outcome.stdout
        assert python.exists()


@pytest.mark.parametrize('requirements_met', [False, True])
def test_launcher_refreshes_importable_but_outdated_dependencies(tmp_path, requirements_met):
    zsh = shutil.which('zsh')
    if zsh is None:
        pytest.skip('The macOS launcher requires zsh')
    launcher = tmp_path / 'start-mac.command'
    shutil.copyfile(Path(__file__).parents[1] / 'start-mac.command', launcher)
    python = tmp_path / '.venv' / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.write_text("""#!/bin/sh
if [ "$1" = "-c" ]; then
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    case "$*" in
        *--dry-run*) exit %d ;;
        *uninstall*) exit 0 ;;
        *install*) echo REFRESH_REQUIREMENTS; exit 0 ;;
    esac
fi
echo RUN_MOONLABELER
""" % (0 if requirements_met else 1), encoding='utf-8')
    python.chmod(0o755)
    outcome = subprocess.run([zsh, str(launcher)], capture_output=True, text=True,
                             input='\n', timeout=5)
    assert outcome.returncode == 0 and 'RUN_MOONLABELER' in outcome.stdout
    assert ('REFRESH_REQUIREMENTS' in outcome.stdout) == (not requirements_met)
