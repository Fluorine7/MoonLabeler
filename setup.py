# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import platform
import subprocess
import sys

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext
from setuptools.command.bdist_wheel import bdist_wheel


class MinimalOpenCV(build_ext):
    def build_extension(self, extension):
        subprocess.run([
            sys.executable, str(Path(__file__).parent/'native'/'build_opencv.py'),
            '--output', str(Path(self.get_ext_fullpath(extension.name)).resolve()),
            '--build-dir', str((Path(self.build_temp)/'opencv').resolve()),
        ], check=True)


class NativeWheel(bdist_wheel):
    def get_tag(self):
        python, abi, target = super().get_tag()
        if sys.platform == 'darwin':
            # setup-python's universal2 interpreter does not make our CMake
            # extension universal. Advertise only the architecture we build.
            target = f'macosx_11_0_{platform.machine()}'
        return python, abi, target


setup(ext_modules=[Extension('_moonlabeler_opencv.cv2', sources=[])],
      cmdclass={'build_ext': MinimalOpenCV, 'bdist_wheel': NativeWheel})
