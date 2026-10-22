# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Render the application icon: an orthographic Moon disc from the bundled albedo map.

Usage: python tools/make_icon.py OUTPUT.ico [--size 256]

The near side (longitude 0 at the centre) is projected onto a disc with mild limb
darkening and an anti-aliased edge; the .ico carries the usual Windows sizes.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image

ALBEDO = Path(__file__).resolve().parent.parent / "moonlabeler" / "data" / "moon_albedo_2k.jpg"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def render_disc(size):
    with Image.open(ALBEDO) as source:
        albedo = np.asarray(source.convert("L"), dtype=np.float32) / 255.0
    rows, cols = albedo.shape
    radius = size * 0.47
    ys, xs = np.mgrid[0:size, 0:size]
    x = (xs + 0.5 - size / 2) / radius
    y = (size / 2 - ys - 0.5) / radius
    rr = x * x + y * y
    z = np.sqrt(np.clip(1.0 - rr, 0.0, 1.0))
    lat = np.arcsin(np.clip(y, -1.0, 1.0))
    lon = np.arctan2(x, z)
    col = np.clip(np.round(((lon / (2 * np.pi) + 0.5) % 1.0) * (cols - 1)).astype(int), 0, cols - 1)
    row = np.clip(np.round((0.5 - lat / np.pi) * (rows - 1)).astype(int), 0, rows - 1)
    shade = np.clip(albedo[row, col] ** 0.7 * 1.1, 0.0, 1.0) * (0.6 + 0.4 * z)
    rgb = np.stack([shade, shade * 0.98, shade * 0.93], axis=-1)
    edge = (np.sqrt(rr) - 1.0) * radius
    alpha = np.clip(0.5 - edge, 0.0, 1.0)
    pixels = np.dstack([(rgb * 255).astype(np.uint8), (alpha * 255).astype(np.uint8)])
    return Image.fromarray(pixels, "RGBA")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=256, help="largest icon size in pixels")
    args = parser.parse_args()
    disc = render_disc(args.size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() == ".ico":
        disc.save(args.output, format="ICO", sizes=[s for s in ICO_SIZES if s[0] <= args.size])
    else:
        disc.save(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
