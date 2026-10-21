# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import subprocess
import sys

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class MinimalOpenCV(build_ext):
    def build_extension(self, extension):
        subprocess.run([
            sys.executable, str(Path(__file__).parent/'native'/'build_opencv.py'),
            '--output', str(Path(self.get_ext_fullpath(extension.name)).resolve()),
            '--build-dir', str((Path(self.build_temp)/'opencv').resolve()),
        ], check=True)


setup(ext_modules=[Extension('_moonlabeler_opencv.cv2', sources=[])],
      cmdclass={'build_ext': MinimalOpenCV})
