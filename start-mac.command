#!/bin/zsh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
set -e
cd "$(dirname "$0")"
python_is_supported() {
    "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' >/dev/null 2>&1
}
if [[ -d .venv ]]; then
    if [[ ! -x .venv/bin/python ]] || ! python_is_supported .venv/bin/python; then
        print "当前 .venv 的 Python 无法运行，或版本低于 3.12。"
        print "请用 Python 3.12 或更高版本手动重建 .venv 后再启动；当前环境未改动。"
        exit 1
    fi
fi
if [[ ! -x .venv/bin/python ]]; then
    task_python=""
    for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3 /usr/local/bin/python3.12 /usr/local/bin/python3; do
        if [[ -x "$candidate" ]] && python_is_supported "$candidate"; then
            task_python="$candidate"
            break
        fi
    done
    if [[ -z "$task_python" ]]; then
        path_python="$(command -v python3 || true)"
        if [[ -n "$path_python" ]] && python_is_supported "$path_python"; then
            task_python="$path_python"
        fi
    fi
    if [[ -z "$task_python" ]]; then
        print "请先安装 Python 3.12 或更高版本。"
        read -k 1
        exit 1
    fi
    "$task_python" -m venv .venv
fi
if ! .venv/bin/python -c 'import PySide6, numpy, PIL, skyfield, shapefile, certifi, opencc, imagecodecs' >/dev/null 2>&1 || ! .venv/bin/python -m pip install --dry-run --no-index --disable-pip-version-check -r requirements.txt >/dev/null 2>&1; then
    .venv/bin/python -m pip install -r requirements.txt
fi
# Old OpenCV wheels must not leave their bundled media libraries in this venv.
legacy_opencv="$(.venv/bin/python -c 'import importlib.metadata as m; names=("opencv-python", "opencv-contrib-python", "opencv-python-headless", "opencv-contrib-python-headless"); installed={d.metadata["Name"].lower() for d in m.distributions()}; print(" ".join(n for n in names if n in installed))')"
if [[ -n "$legacy_opencv" ]]; then
    .venv/bin/python -m pip uninstall -y ${=legacy_opencv}
fi
if ! .venv/bin/python -c 'from moonlabeler._opencv import cv2; assert hasattr(cv2, "ximgproc"); assert not hasattr(cv2, "imread")' >/dev/null 2>&1; then
    print "正在构建不含图像 / 视频解码器的 OpenCV；首次需要 Xcode Command Line Tools。"
    .venv/bin/python -m pip install --no-deps .
fi
exec .venv/bin/python -m moonlabeler "$@"
