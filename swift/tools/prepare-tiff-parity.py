#!/usr/bin/env python3
"""Generate TIFF fixtures with the current Python reader and its TIFF helpers."""
import argparse
import json
from pathlib import Path
import runpy
import sys

import imagecodecs
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from moonlabeler.sources import read_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", action="store_true")
    args = parser.parse_args()
    helpers = runpy.run_path(str(ROOT / "tests/test_sources.py"))
    orient = helpers["set_tiff_orientation"]
    pixels = helpers["sixteen_bit_rgb_photo"]()
    pixels = pixels + np.arange(pixels.shape[0], dtype=np.uint16)[:, None, None] * np.array([7, 3, 1], dtype=np.uint16)
    output = ROOT / "swift/Tests/MoonCoreTests/Fixtures"
    records = []

    def store(name, encoded, orientation=1):
        path = output / ("image-tiff-" + name + ".tif")
        path.write_bytes(encoded)
        if orientation != 1:
            orient(path, orientation)
        image = read_image(path)
        records.append(dict(name=name, file=path.name, width=image.shape[1], height=image.shape[0], rgb=image.reshape(-1).tolist()))

    for compression in (None, 5, 8, 32773):
        for planar in (False, True):
            options = dict(compression=compression, photometric="rgb", planarconfig="separate" if planar else "contig")
            if compression in (5, 8): options["predictor"] = 2
            array = np.moveaxis(pixels, -1, 0) if planar else pixels
            store(f"compression-{compression}-planar-{int(planar)}", imagecodecs.tiff_encode(array, **options))
    for bigtiff, byteorder in ((False, ">"), (True, "<")):
        for orientation in range(1, 9):
            store(f"big-{int(bigtiff)}-orientation-{orientation}", imagecodecs.tiff_encode(pixels, bigtiff=bigtiff, byteorder=byteorder), orientation)
    gray = np.arange(500, dtype=np.uint16).reshape(20, 25)
    gray[-1, -1] = 65535
    store("gray-percentile", imagecodecs.tiff_encode(gray))
    gray = np.arange(497, dtype=np.uint16).reshape(7, 71)
    gray[-1, -1] = 65535
    store("gray-percentile-497", imagecodecs.tiff_encode(gray))
    floating = np.arange(19 * 23, dtype=np.float32).reshape(19, 23) / 7
    floating[2, 4:7] = [np.nan, np.inf, -np.inf]
    store("float-nonfinite", imagecodecs.tiff_encode(floating))
    store("multipage", imagecodecs.tiff_encode(np.stack((pixels, pixels[:, ::-1]))))
    oracle = dict(source="moonlabeler.sources.read_image", tools=dict(numpy=np.__version__, imagecodecs=imagecodecs.__version__, tiff=imagecodecs.tiff_version()), cases=records)
    (output / "image-tiff-oracle.json").write_text(json.dumps(oracle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Generated {len(records)} TIFF oracle cases")
    if args.large:
        path = ROOT / "swift/.build/parity-0316/large-gray.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        values = np.arange(2048 * 3072, dtype=np.uint16).reshape(2048, 3072)
        path.write_bytes(imagecodecs.tiff_encode(values))
        print("Large fixture:", path)


if __name__ == "__main__":
    main()
