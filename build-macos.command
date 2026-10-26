#!/bin/bash
# Build locally with an already prepared Python 3.12 environment and private OpenCV.
# Usage: ./build-macos.command /absolute/path/to/python
set -euo pipefail
cd "$(dirname "$0")"
BUILD_PYTHON="${1:-.venv-macos-build/bin/python}"
export MACOSX_DEPLOYMENT_TARGET=14.4
export PYTHONUTF8=1
export PYINSTALLER_CONFIG_DIR="$PWD/.cache/pyinstaller-macos"
"$BUILD_PYTHON" -c 'import platform, sys; assert sys.platform == "darwin" and platform.machine() == "arm64"; assert sys.version_info >= (3, 12); import PyInstaller, astropy, wgpu; from moonlabeler._opencv import cv2; assert not hasattr(cv2, "imread")'
"$BUILD_PYTHON" -c 'from PySide6.QtSvg import QSvgRenderer'
"$BUILD_PYTHON" -c 'from importlib.metadata import version; from moonlabeler import __version__; assert version("moonlabeler") == __version__, "Install the current project in the packaging environment first"'
"$BUILD_PYTHON" -c 'from datetime import datetime, timezone; from pathlib import Path; from moonlabeler.geometry import compute_geometry; compute_geometry(datetime(2026, 1, 1, tzinfo=timezone.utc), Path(".cache/ephemeris"))'
mkdir -p build
"$BUILD_PYTHON" tools/make_icon.py build/moonlabeler.icns --size 1024
"$BUILD_PYTHON" - <<'PY'
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import subprocess
report = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
          "build_host": platform.mac_ver()[0], "minimum_macos": "14.4", "architecture": "arm64",
          "python": platform.python_version(),
          "qt_binding_source": "f50facb83fc3dc5f3240c854668c7a6dd93871b2",
          "dependencies": {name: metadata.version(name) for name in
              ("PySide6-Essentials", "shiboken6", "numpy", "Pillow", "imagecodecs", "astropy", "wgpu", "certifi")}}
Path("build/macos-build-info.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
PY
"$BUILD_PYTHON" -m PyInstaller --noconfirm --clean MoonLabeler.spec
"$BUILD_PYTHON" tools/check_macos_bundle.py dist/MoonLabeler.app --output dist/macos-bundle-verification.json
/usr/bin/codesign --verify --deep --strict dist/MoonLabeler.app
CHECK_FOLDER="$(mktemp -d "$PWD/build/macos-check.XXXXXX")"
/usr/bin/env -u PYTHONHOME -u PYTHONPATH PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  QT_QPA_PLATFORM=offscreen MOONLABELER_COMPUTE=cpu MOONLABELER_CACHE="$CHECK_FOLDER/cache" \
  MOONLABELER_BUNDLE_CHECK="$PWD/dist/macos-frozen-verification.json" \
  "$PWD/dist/MoonLabeler.app/Contents/MacOS/MoonLabeler"
VERSION="$("$BUILD_PYTHON" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent dist/MoonLabeler.app "dist/MoonLabeler-$VERSION-macos-arm64.zip"
echo "Built dist/MoonLabeler-$VERSION-macos-arm64.zip (macOS 14.4+, Apple Silicon)"
