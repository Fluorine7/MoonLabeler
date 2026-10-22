# Overrides the pyinstaller-hooks-contrib astropy hook, which imports every astropy
# submodule and dies on astropy.visualization.wcsaxes (it calls pytest.importorskip
# for matplotlib at import time). MoonLabeler only reads FITS files, so collect the
# I/O and utility packages plus astropy's data files.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (collect_submodules("astropy.io") + collect_submodules("astropy.utils")
                 + collect_submodules("astropy.units") + collect_submodules("astropy.constants"))
datas = collect_data_files("astropy", excludes=["**/tests/**"])
# Astropy 8's PLY adapter reads the parser tables as source files before import.
module_collection_mode = {"astropy.units.format": "py+pyz", "astropy.coordinates.angles": "py+pyz"}
