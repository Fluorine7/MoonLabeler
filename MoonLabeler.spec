# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows build. Run through build-windows.ps1, or directly:
#   python -m PyInstaller --noconfirm --clean MoonLabeler.spec
# Produces dist/MoonLabeler/MoonLabeler.exe (one-folder build; no installer needed).
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "moonlabeler" / "data"), "moonlabeler/data"),
    (str(ROOT / "moonlabeler" / "ui" / "assets"), "moonlabeler/ui/assets"),
    # "Open demo project" in the Help menu reads ROOT/examples at run time.
    (str(ROOT / "examples" / "demo.moonlabel"), "examples"),
    (str(ROOT / "examples" / "synthetic-moon.png"), "examples"),
]
# JPL kernels fetched by an earlier run ship with the exe so the first launch works
# offline; app.prepare_cache() copies them into the per-user cache on start-up.
ephemeris = ROOT / ".cache" / "ephemeris"
datas += [(str(path), "bundled_ephemeris") for path in sorted(ephemeris.glob("*")) if path.is_file()]

icon = ROOT / "build" / "moonlabeler.ico"

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["astropy.io.fits"],
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
