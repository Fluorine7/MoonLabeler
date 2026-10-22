# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows build. Run through build-windows.ps1, or directly:
#   python -m PyInstaller --noconfirm --clean MoonLabeler.spec
# Produces dist/MoonLabeler/MoonLabeler.exe (one-folder build; no installer needed).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "moonlabeler" / "data"), "moonlabeler/data"),
    (str(ROOT / "moonlabeler" / "ui" / "assets"), "moonlabeler/ui/assets"),
    # "Open demo project" in the Help menu reads ROOT/examples at run time.
    (str(ROOT / "examples" / "demo.moonlabel"), "examples"),
    (str(ROOT / "examples" / "synthetic-moon.png"), "examples"),
]
datas += [(str(ROOT / name), ".") for name in (
    "LICENSE", "THIRD_PARTY_NOTICES.md", "ACKNOWLEDGEMENTS.md",
    "README.md", "README.zh-CN.md", "UPDATE_HISTORY.md",
)]
# JPL kernels fetched by an earlier run ship with the exe so the first launch works
# offline; app.prepare_cache() copies them into the per-user cache on start-up.
ephemeris = ROOT / ".cache" / "ephemeris"
datas += [(str(path), "bundled_ephemeris") for path in sorted(ephemeris.glob("*")) if path.is_file()]

# The private OpenCV extension ships its native notices and build manifest next to the
# binary; nothing imports the package statically, so collect them here (the cv2 hook
# only runs when the compatibility shim is imported).
datas += collect_data_files("_moonlabeler_opencv")

icon = ROOT / "build" / "moonlabeler.ico"

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    datas=datas,
    # moonlabeler._opencv loads the private OpenCV extension via find_spec, which static
    # analysis cannot follow; see tools/pyinstaller-hooks/hook-cv2.py.
    hiddenimports=["astropy.io.fits", "_moonlabeler_opencv.cv2"],
    hookspath=[str(ROOT / "tools" / "pyinstaller-hooks")],
    # astropy.visualization.wcsaxes calls pytest.importorskip("matplotlib") on import and
    # aborts PyInstaller's dependency scan whenever pytest is installed; FITS I/O never needs it.
    excludes=["tkinter", "matplotlib", "scipy", "IPython", "pytest", "astropy.visualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    # Same as the PYTHONUTF8=1 the launcher scripts set: Windows defaults to cp950 here.
    [("X utf8", None, "OPTION")],
    exclude_binaries=True,
    name="MoonLabeler",
    icon=str(icon) if icon.exists() else None,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MoonLabeler")
