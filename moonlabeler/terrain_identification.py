# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Automatic full-Moon search using coarse LOLA slope/shadow references.

This is a spherical 2.5-D reference, not a terrain ray-tracer. It is used only
after the albedo, limb and crater searches fail. No region or names are given
to the search. Distributed image correspondences, photometric agreement and
competing poses validate a result; catalogue labels then share its map pose.
"""
import math

import cv2
import numpy as np

from .geometry import surface_vectors
from .identification import IdentificationError, IdentificationResult
from .registration import auto_register, transform_points
from .terrain import ElevationMap, download_basic_dem, terrain_shadow


def render_terrain_atlas(dem, geometry, size=4000):
    """Render the visible sphere in strips; keep DEM sampling memory bounded."""
    scale, center = size*.47, (size-1)/2
    reference = np.zeros((size, size), np.uint8)
    for first in range(0, size, 64):
        x, y = np.meshgrid(np.arange(size), np.arange(first, min(size, first+64)))
        points = np.column_stack(((x.ravel()-center)/scale, (y.ravel()-center)/scale))
        lat, lon, disk = geometry.unproject(points)
        indices = np.flatnonzero(disk)
        latitude, longitude = lat[indices], lon[indices]
        radial = surface_vectors(latitude, longitude)
        height = dem.sample(latitude, longitude)
        normal = dem.normals(latitude, longitude)
        incidence = np.maximum(normal @ geometry.sun, 0)
        emission = np.maximum(normal @ geometry.observer, 0)
        valid = np.isfinite(height) & np.isfinite(normal).all(axis=1)
        lit = valid & (incidence > 0) & (emission > 0)
        light = np.sqrt(np.clip(2*incidence/(incidence+emission+1e-8), 0, 1))
        light[~lit] = 0
        if lit.any():
            hidden = terrain_shadow(dem, radial[lit], height[lit], geometry.sun, steps=12)
            light[np.flatnonzero(lit)[hidden]] = 0
        slab = np.zeros(x.size, np.float32)
        slab[indices] = np.nan_to_num(light)*220
        reference[first:first+x.shape[0]] = slab.reshape(x.shape).astype(np.uint8)
    return reference, np.array([[scale, 0., center], [0., scale, center]])


def terrain_agreement(reference, photograph, reference_to_photo, *, require_match=True):
    """Independent dense light and spatial-detail checks, outside captions."""
    h, w = photograph.shape[:2]
    gray = cv2.cvtColor(photograph, cv2.COLOR_RGB2GRAY) if photograph.ndim == 3 else photograph
    projected = cv2.warpAffine(reference, reference_to_photo, (w, h))
    available = cv2.warpAffine(np.full(reference.shape, 255, np.uint8), reference_to_photo, (w, h)) > 250
    domain = np.zeros((h, w), bool)
    domain[round(h*.08):round(h*.93), round(w*.05):round(w*.95)] = True
    domain &= available & ((gray > 15) | (projected > 15))
    if domain.sum() < 600 or np.std(gray[domain]) < 8 or np.std(projected[domain]) < 8:
        raise IdentificationError("高程参考有效纹理不足，未采用结果。")
    a, b = gray.astype(np.float32), projected.astype(np.float32)
    light = float(np.corrcoef(a[domain], b[domain])[0, 1])
    sigma = max(2., max(h, w)/88)
    detail_a = a-cv2.GaussianBlur(a, (0, 0), sigma)
    detail_b = b-cv2.GaussianBlur(b, (0, 0), sigma)
    if min(np.std(detail_a[domain]), np.std(detail_b[domain])) < 2:
        raise IdentificationError("高程参考只有宽泛明暗，没有足够地形细节。")
    detail = float(np.corrcoef(detail_a[domain], detail_b[domain])[0, 1])
    if not np.isfinite([light, detail]).all() or (require_match and (light < .6 or detail < .25)):
        raise IdentificationError("图像对应点与高程阴影纹理不一致，未采用结果。")
    return light, detail


def terrain_consensus(light, detail, inliers, coverage):
    """Dense validation with a narrow, more strongly supported boundary band.

    Small shading changes can move a valid polar reference just below 0.60.
    The 0.59--0.60 band needs more correspondences, more spatial coverage and
    stronger detail than the normal path; a weak dense match still fails.
    """
    if not np.isfinite([light, detail, coverage]).all():
        return False
    if light >= .6 and detail >= .25:
        return inliers >= 24 and coverage >= .06
    return light >= .59 and detail >= .30 and inliers >= 32 and coverage >= .15


def identify_from_terrain(image, geometry, cache, *, atlas_size=4000, tile_size=1536, refine=True):
    """Search every atlas tile, both handednesses, at a coarse image scale."""
    dem = ElevationMap.load(download_basic_dem(cache))
    try:
        reference, projection = render_terrain_atlas(dem, geometry, atlas_size)
    finally:
        dem.close()
    cv2.setRNGSeed(0)
    h, w = image.shape[:2]
    factor = min(1., 880/max(h, w))
    photograph = cv2.resize(image, (round(w*factor), round(h*factor)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(photograph, cv2.COLOR_RGB2GRAY) if photograph.ndim == 3 else photograph
    sample = cv2.resize(gray[:round(gray.shape[0]*.93)], (60, 54), interpolation=cv2.INTER_AREA)
    yy, xx = np.nonzero(sample > 30)
    foreground = np.column_stack(((xx+.5)*w/60, (yy+.5)*round(h*.93)/54))
    # Rounded dimensions have independent x/y scales, retained in the pose.
    sx, sy = photograph.shape[1]/w, photograph.shape[0]/h
    tile_size = min(tile_size, atlas_size)
    count = max(1, math.ceil((atlas_size-tile_size)/(tile_size*.82))+1)
    starts = np.unique(np.rint(np.linspace(0, atlas_size-tile_size, count)).astype(int))
    solutions = []
    for y in starts:
        for x in starts:
            tile = reference[y:y+tile_size, x:x+tile_size]
            if np.std(tile) < 8:
                continue
            try:
                # Cross-source slope and photographic textures need broader
                # retrieval. Stronger count, coverage and dense checks follow;
                # the normal albedo/manual matching defaults are unchanged.
                match = auto_register(tile, photograph, ratio_threshold=.8,
                                      contrast_threshold=.01, min_inlier_fraction=.25)
            except ValueError:
                continue
            if match.inliers < 24 or match.coverage < .06:
                continue
            offset = np.array([[1., 0., -x], [0., 1., -y], [0., 0., 1.]])
            reference_to_photo = (np.vstack((match.matrix, [0., 0., 1.])) @ offset)[:2]
            try:
                light, detail = terrain_agreement(reference, photograph, reference_to_photo, require_match=False)
            except IdentificationError:
                continue
            if not terrain_consensus(light, detail, match.inliers, match.coverage):
                continue
            matrix = (np.vstack((reference_to_photo, [0., 0., 1.])) @ np.vstack((projection, [0., 0., 1.])))[:2]
            matrix = np.diag([1/sx, 1/sy]) @ matrix
            inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
            if len(foreground) and (np.linalg.norm(transform_points(inverse, foreground), axis=1) < 1.015).mean() < .95:
                continue
            score = match.inliers*(light+detail)
            solutions.append((score, matrix, match, light))
    if not solutions:
        raise IdentificationError("高程阴影参考也未找到通过纹理与分布验证的月面区域。")
    solutions.sort(key=lambda result: -result[0])
    score, matrix, match, light = solutions[0]
    center = np.array([[w/2, h/2], [w*.75, h/2], [w/2, h*.75]])
    inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
    source = transform_points(inverse, center)
    alternatives = 0
    for other_score, other_matrix, _, _ in solutions[1:]:
        difference = np.linalg.norm(transform_points(other_matrix, source)-center, axis=1).mean()
        if difference > max(w, h)*.08:
            alternatives += 1
            if other_score > score*.8:
                raise IdentificationError("出现多个接近的高程纹理匹配，未采用结果。")
    result = IdentificationResult(matrix, [], match.rms_px/min(sx, sy), float(score), alternatives,
                                "LOLA slope + cast-shadow tiles / symmetric SIFT / JPL projection",
                                match.inliers, match.coverage, 0, light)
    if refine:
        from .terrain_refinement import refine_terrain_pose
        dem = ElevationMap.load(download_basic_dem(cache))
        try:
            refined = refine_terrain_pose(image, geometry, matrix, dem)
        finally:
            dem.close()
        if refined is not None:
            result.matrix, result.rms_px = refined.matrix, refined.rms_px
            result.projection_geometry = refined.geometry
            result.refinement = refined.details
            result.image_inliers = refined.details['points']
            result.coverage = refined.details['coverage']
            result.texture_correlation = refined.details['light_before_after'][1]
    return result
