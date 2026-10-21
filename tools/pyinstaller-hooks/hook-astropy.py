# Overrides the pyinstaller-hooks-contrib astropy hook, which imports every astropy
# submodule and dies on astropy.visualization.wcsaxes (it calls pytest.importorskip
# for matplotlib at import time). MoonLabeler only reads FITS files, so collect the
# I/O and utility packages plus astropy's data files.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("astropy.io") + collect_submodules("astropy.utils") + collect_submodules("astropy.units")
datas = collect_data_files("astropy", excludes=["**/tests/**"])
