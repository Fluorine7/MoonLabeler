# Overrides the pyinstaller-hooks-contrib cv2 hook, which is written for the PyPI
# opencv-python wheels (config files, bundled FFmpeg DLLs). Here ``cv2`` is only the
# compatibility shim in cv2/__init__.py; the real extension is MoonLabeler's private
# minimal build, loaded by moonlabeler._opencv through find_spec at run time, which
# static analysis cannot see.
from PyInstaller.utils.hooks import collect_data_files

hiddenimports = ["numpy", "_moonlabeler_opencv.cv2"]
# Native notices and the build manifest travel next to the extension.
datas = collect_data_files("_moonlabeler_opencv")
