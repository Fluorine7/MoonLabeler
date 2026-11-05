#!/usr/bin/env python3
"""Generate Swift FITS fixtures using the current Python image reader as oracle."""
from pathlib import Path
import argparse
import json
import sys

import numpy as np
import astropy
from astropy.io import fits

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from moonlabeler.sources import read_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", action="store_true", help="Also create an ignored large RGB memory fixture")
    args = parser.parse_args()
    output = ROOT / "swift/Tests/MoonCoreTests/Fixtures"
    output.mkdir(parents=True, exist_ok=True)
    rgb = np.arange(7 * 9 * 3, dtype=np.float64).reshape(7, 9, 3)
    rgb = rgb * np.array([3, 7, 11]) + np.array([1000, 300, 20])
    rgba = np.concatenate((rgb, np.full((7, 9, 1), 50000.0)), axis=-1)
    nonfinite = np.arange(80, dtype=np.float64).reshape(8, 10)
    nonfinite[1, 2:5] = [np.nan, np.inf, -np.inf]
    sparse = np.zeros((64, 64), dtype=np.float64)
    sparse[10, 20:22] = [0.5, 1.0]
    scaled = fits.PrimaryHDU(np.arange(63, dtype=np.int16).reshape(7, 9))
    scaled.data[2, 3] = -32768
    scaled.header.update(BLANK=-32768, BSCALE=2, BZERO=32768)
    cases = {
        "leading-rgb": fits.HDUList([fits.PrimaryHDU(np.moveaxis(rgb, -1, 0))]),
        "trailing-rgb": fits.HDUList([fits.PrimaryHDU(rgb)]),
        "leading-rgba": fits.HDUList([fits.PrimaryHDU(np.moveaxis(rgba, -1, 0))]),
        "trailing-rgba": fits.HDUList([fits.PrimaryHDU(rgba)]),
        "nonfinite": fits.HDUList([fits.PrimaryHDU(nonfinite)]),
        "sparse": fits.HDUList([fits.PrimaryHDU(sparse)]),
        "scaled-blank": fits.HDUList([scaled]),
        "image-extension": fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns([fits.Column(name="x", array=[1, 2], format="J")]), fits.ImageHDU(rgb[None, ...])]),
        "many-singletons": fits.HDUList([fits.PrimaryHDU(rgb.reshape((1,) * 10 + rgb.shape))]),
        "invalid-first-image": fits.HDUList([fits.PrimaryHDU(np.zeros((2, 2, 3, 4))), fits.ImageHDU(np.moveaxis(rgb, -1, 0))]),
    }
    records = []
    for name, hdus in cases.items():
        path = output / f"image-fits-{name}.fits"
        hdus.writeto(path, overwrite=True)
        record = {"name": name, "file": path.name}
        try:
            image = read_image(path)
            record.update(width=image.shape[1], height=image.shape[0], rgb=image.reshape(-1).tolist())
        except ValueError as error:
            record["error"] = str(error)
        records.append(record)
    (output / "image-fits-oracle.json").write_text(json.dumps({"source": "moonlabeler.sources.read_image", "tools": {"astropy": astropy.__version__, "numpy": np.__version__}, "cases": records}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Generated {len(records)} Python image oracles")
    if args.large:
        path = ROOT / "swift/.build/parity-0315/large-rgb.fits"
        path.parent.mkdir(parents=True, exist_ok=True)
        fits.PrimaryHDU(np.arange(3 * 2048 * 3072, dtype=np.float64).reshape(3, 2048, 3072)).writeto(path, overwrite=True)
        print(f"Large fixture: {path}")


if __name__ == "__main__":
    main()
