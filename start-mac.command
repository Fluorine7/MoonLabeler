#!/bin/zsh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
    task_python=""
    for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3.12 /usr/local/bin/python3; do
        if [[ -x "$candidate" ]]; then
            task_python="$candidate"
            break
        fi
    done
    if [[ -z "$task_python" ]]; then
        task_python="$(command -v python3 || true)"
    fi
    if [[ -z "$task_python" ]]; then
        print "请先安装 Python 3.11 或更高版本。"
        read -k 1
        exit 1
    fi
    "$task_python" -m venv .venv
fi
if ! .venv/bin/python -c 'import PySide6, numpy, PIL, cv2, skyfield, shapefile; assert hasattr(cv2, "ximgproc")' >/dev/null 2>&1; then
    if .venv/bin/python -c 'import importlib.metadata as m; m.version("opencv-python-headless")' >/dev/null 2>&1; then
        .venv/bin/python -m pip uninstall -y opencv-python-headless
    fi
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m moonlabeler "$@"
