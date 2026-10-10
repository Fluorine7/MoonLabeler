# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Offline LROC albedo reference projected into the supplied JPL view.

Image feature correspondences establish a map pose, not individually detected
named craters. The bundled map's source and recompression are documented in
data/moon_albedo_2k.provenance.json and THIRD_PARTY_NOTICES.md.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .geometry import surface_vectors
from .identification import IdentificationError, IdentificationResult
from .registration import auto_register, transform_points


def render_atlas(geometry, size=1600):
    with Image.open(Path(__file__).parent / "data/moon_albedo_2k.jpg") as source:
        texture = np.asarray(source.convert("RGB"))
    scale, center = size*.47, (size-1)/2
    reference = np.zeros((size, size, 3), np.uint8)
    for first in range(0, size, 64):
        x, y = np.meshgrid(np.arange(size), np.arange(first, min(size, first+64)))
        points = np.column_stack(((x.ravel()-center)/scale, (y.ravel()-center)/scale))
        lat, lon, disk = geometry.unproject(points)
        mx = np.nan_to_num((lon+180)/360*texture.shape[1]-.5).astype(np.float32).reshape(x.shape)
        my = np.nan_to_num((90-lat)/180*texture.shape[0]-.5).astype(np.float32).reshape(x.shape)
        color = cv2.remap(texture, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        vectors = surface_vectors(lat, lon)
        incidence = np.maximum(vectors @ geometry.sun, 0)
        emission = np.maximum(vectors @ geometry.observer, 0)
        light = np.sqrt(np.clip(2*incidence/(incidence+emission+1e-8), 0, 1))
        light[~disk] = 0
        reference[first:first+x.shape[0]] = (color*light.reshape(x.shape+(1,))).astype(np.uint8)
    matrix = np.array([[scale, 0., center], [0., scale, center]])
    return reference, matrix


def identify_from_atlas(image, geometry):
    """No supplied region, camera angle, mirror, scale or feature names."""
    reference, projection = render_atlas(geometry)
    match = auto_register(reference, image)
    # The map search has no user-supplied region, so require more evidence than
    # the existing manually selected reference matching tool.
    if match.inliers < 24 or match.inliers/match.matches < .45 or match.coverage < .04:
        raise IdentificationError("纹理对应点太少或过于集中，未采用配准。")
    matrix = (np.vstack((match.matrix, [0., 0., 1.])) @ np.vstack((projection, [0., 0., 1.])))[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    height, width = gray.shape
    sample = cv2.resize(gray[:round(height*.93)], (60, 54), interpolation=cv2.INTER_AREA)
    yy, xx = np.nonzero(sample > 30)
    foreground = np.column_stack(((xx+.5)*width/60, (yy+.5)*round(height*.93)/54))
    if len(foreground):
        inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
        if (np.linalg.norm(transform_points(inverse, foreground), axis=1) < 1.015).mean() < .95:
            raise IdentificationError("纹理配准与照片中的月盘范围不一致。")
    return IdentificationResult(matrix, [], match.rms_px, float(match.inliers), 0,
                                "LROC albedo / symmetric SIFT / JPL projection",
                                match.inliers, match.coverage)
