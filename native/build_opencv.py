"""Build the pinned, codec-free private OpenCV extension used by MoonLabeler."""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import sysconfig
import tarfile
from urllib.request import urlopen

import certifi
import numpy

SOURCES = {
    'opencv': ('0654a42e19215ef25b1d367d822f3c630447e7c7',
               '7a75663094ebd50bf212928423a24394e29d751db878044ad015ba28546a59db'),
    'opencv_contrib': ('a8e9acd62cabd30419dba83007f2ac0d07de5e2c',
                       'c96663affc1e6125fc5b630539db83f5bcff19f911c2bbc40e9b7566f86508c9'),
}
MODULES = {'core', 'imgproc', 'flann', 'features2d', 'calib3d', 'ximgproc', 'python3'}
FORBIDDEN = ('/modules/imgcodecs/', '/modules/videoio/', '/modules/highgui/',
             '/modules/dnn/', '/3rdparty/libtiff/', '/3rdparty/openexr/',
             '/3rdparty/openjpeg/', '/3rdparty/libjpeg', '/3rdparty/libpng/',
             '/3rdparty/libwebp/', 'ffmpeg')


def fetch_sources(destination):
    context = ssl.create_default_context(cafile=certifi.where())
    destination.mkdir(parents=True, exist_ok=True)
    for name, (commit, expected) in SOURCES.items():
        archive = destination/f'{name}.tar.gz'
        digest = hashlib.sha256()
        with urlopen(f'https://codeload.github.com/opencv/{name}/tar.gz/{commit}',
                     context=context, timeout=120) as response, archive.open('wb') as output:
            while chunk := response.read(1024*1024):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError(f'{name} source archive checksum mismatch')
        with tarfile.open(archive) as package:
            package.extractall(destination, filter='data')
        archive.unlink()


def edge_module(contrib, destination):
    """Keep upstream EdgeDrawing code intact; omit other contrib algorithms."""
    original = contrib/'modules'/'ximgproc'
    for name in ('src/edge_drawing.cpp', 'src/edge_drawing_common.hpp', 'src/precomp.hpp',
                 'misc/python/pyopencv_ximgproc.hpp',
                 'include/opencv2/ximgproc/edge_drawing.hpp'):
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original/name, target)
    (destination/'include/opencv2/ximgproc.hpp').write_text(
        '#pragma once\n#include <opencv2/ximgproc/edge_drawing.hpp>\n', encoding='utf-8')
    (destination/'CMakeLists.txt').write_text(
        'set(the_description "MoonLabeler: upstream EdgeDrawing only")\n'
        'ocv_define_module(ximgproc opencv_core opencv_imgproc WRAP python)\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    args = parser.parse_args()
    args.build_dir.mkdir(parents=True, exist_ok=True)
    # Local developers can reuse sources already fetched and verified in the
    # same controlled session. CI always downloads/checks the pinned archives.
    existing = os.environ.get('MOONLABELER_OPENCV_SOURCE_ROOT')
    sources = Path(existing) if existing else args.build_dir/'sources'
    if not existing:
        fetch_sources(sources)
    opencv, contrib = [sources/f'{name}-{SOURCES[name][0]}' for name in SOURCES]
    extra = args.build_dir/'edgedrawing'
    edge_module(contrib, extra)
    cmake_build = args.build_dir/'cmake'
    command = ['cmake', '-S', str(opencv), '-B', str(cmake_build),
               '-C', str(Path(__file__).with_name('minimal.cmake')), '-G', 'Ninja',
               '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
               f'-DOPENCV_EXTRA_MODULES_PATH={extra}',
               f'-DPYTHON3_EXECUTABLE={sys.executable}',
               f'-DPYTHON3_INCLUDE_DIR={sysconfig.get_path("include")}',
               f'-DPYTHON3_NUMPY_INCLUDE_DIRS={numpy.get_include()}']
    if sys.platform == 'darwin':
        command.append('-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0')
    environment = os.environ.copy()
    if sys.platform == 'win32':
        from setuptools._distutils.compilers.C.msvc import _get_vc_env
        environment.update({key.upper(): value for key, value in _get_vc_env('x86_amd64').items()})
    subprocess.run(command, check=True, env=environment)
    jobs = os.environ.get('CMAKE_BUILD_PARALLEL_LEVEL', str(min(8, os.cpu_count() or 2)))
    subprocess.run(['cmake', '--build', str(cmake_build), '--target', 'opencv_python3',
                    '--config', 'Release', '--parallel', jobs], check=True, env=environment)
    commands = json.loads((cmake_build/'compile_commands.json').read_text(encoding='utf-8'))
    for item in commands:
        source = item['file'].replace('\\', '/').lower()
        if any(part in source for part in FORBIDDEN):
            raise RuntimeError(f'Unexpected codec source in minimal build: {source}')
    binaries = list((cmake_build/'lib').rglob('cv2*.pyd' if sys.platform == 'win32' else 'cv2*.so'))
    if len(binaries) != 1:
        raise RuntimeError(f'Expected one OpenCV extension, found {binaries}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binaries[0], args.output)
    # Notices travel with the native binary in the application wheel.
    notices = args.output.parent/'licenses'
    notices.mkdir(exist_ok=True)
    for name, source in [('OpenCV-LICENSE.txt', opencv/'LICENSE'),
                         ('opencv_contrib-LICENSE.txt', contrib/'LICENSE'),
                         ('ximgproc-precomp-BSD.txt', contrib/'modules/ximgproc/src/precomp.hpp'),
                         ('zlib-notice.txt', opencv/'3rdparty/zlib/zlib.h')]:
        shutil.copyfile(source, notices/name)
    for source in (opencv/'modules/features2d/src/kaze').glob('LICENSE*'):
        shutil.copyfile(source, notices/f'features2d-{source.name}.txt')
    shutil.copyfile(opencv/'modules/features2d/3rdparty/mscr/chi_table_LICENSE.txt', notices/'mscr-LICENSE.txt')
    softfloat = (opencv/'modules/core/src/softfloat.cpp').read_text(encoding='utf-8').split('#include "precomp.hpp"', 1)[0]
    (notices/'softfloat-fdlibm-LICENSE.txt').write_text(softfloat, encoding='utf-8')
    (args.output.parent/'build-manifest.json').write_text(json.dumps({
        'opencv_version': '4.14.0', 'sources': SOURCES, 'modules': sorted(MODULES),
        'contrib_subset': ['edge_drawing.cpp', 'edge_drawing_common.hpp', 'precomp.hpp', 'edge_drawing.hpp', 'pyopencv_ximgproc.hpp'],
        'compiled_sources': len(commands), 'codec_sources': [],
    }, indent=2), encoding='utf-8')
    print(f'Minimal OpenCV: {len(commands)} compiled sources; no image/video codecs; {args.output}', flush=True)


if __name__ == '__main__':
    main()
