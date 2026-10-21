"""Check the installed native binary and print/save CI evidence."""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from moonlabeler._opencv import cv2

EXPECTED = {'core', 'imgproc', 'flann', 'features2d', 'calib3d', 'ximgproc', 'python3'}
CODECS = ('imread', 'imdecode', 'imwrite', 'imencode', 'VideoCapture', 'VideoWriter', 'imshow')
LEGACY = ('opencv-python', 'opencv-contrib-python', 'opencv-python-headless', 'opencv-contrib-python-headless')


def verify():
    path = Path(cv2.__file__).resolve()
    assert path.parent.name == '_moonlabeler_opencv', path
    info = cv2.getBuildInformation()
    modules = set(re.search(r'^\s*To be built:\s*(.+)$', info, re.MULTILINE)[1].split())
    assert modules == EXPECTED, modules
    assert not any(hasattr(cv2, name) for name in CODECS)
    assert callable(cv2.SIFT_create) and callable(cv2.ximgproc.createEdgeDrawing)
    for name in LEGACY:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        raise AssertionError(f'Remove legacy wheel {distribution.metadata["Name"]}')
    manifest = json.loads((path.parent/'build-manifest.json').read_text(encoding='utf-8'))
    assert set(manifest['modules']) == EXPECTED and manifest['codec_sources'] == []
    if sys.platform == 'darwin':
        command = ['otool', '-L', str(path)]
    elif sys.platform == 'win32':
        tool = shutil.which('dumpbin')
        if not tool:
            vswhere = Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
            tool = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-find',
                r'VC\Tools\MSVC\**\bin\Hostx64\x64\dumpbin.exe'], text=True).strip().splitlines()[0]
        command = [tool, '/DEPENDENTS', str(path)]
    else:
        command = ['readelf', '-d', str(path)]
    linked = subprocess.check_output(command, text=True, encoding='utf-8', errors='replace')
    # Inspect linked-library names, rather than the CMake report's feature labels.
    forbidden = re.compile(r'(?i)(libtiff|libjpeg|libpng|libwebp|openjp|openexr|ilmimf|avcodec|avformat|avutil|swscale|ffmpeg|gstreamer)')
    assert not forbidden.search(linked), linked
    return {'opencv': cv2.__version__, 'binary': str(path), 'bytes': path.stat().st_size,
            'modules': sorted(modules), 'codec_api': [], 'legacy_wheels': [],
            'native_dependencies': linked, 'build': manifest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = json.dumps(verify(), indent=2)
    if args.output:
        args.output.write_text(report, encoding='utf-8')
    print(report)
