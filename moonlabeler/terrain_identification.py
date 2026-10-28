# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Automatic full-Moon search using coarse LOLA slope/shadow references.

The coarse search uses a spherical 2.5-D reference; promising regional poses
may then use relief-aware local refinement before final validation. This is
used only after the albedo, limb and crater searches fail. No region or names
are given to the search. Distributed correspondences, photometric agreement
and competing poses validate a result; catalogue labels share its map pose.
"""
import math

from .recognition_mask import mask_kwargs
from ._opencv import cv2
import numpy as np

from .identification import IdentificationError, IdentificationResult
from .registration import auto_register, transform_points, prepare_registration_photo
from .terrain import ElevationMap, download_basic_dem, shade_atlas_points


def render_terrain_atlas(dem, geometry, size=4000):
    from .compute import try_render
    accelerated = try_render(dem, geometry, size)
    if accelerated is not None:
        return accelerated
    return _render_terrain_atlas_cpu(dem, geometry, size)


def _render_terrain_atlas_cpu(dem, geometry, size=4000):
    """Render the visible sphere in strips; keep DEM sampling memory bounded."""
    scale, center = size*.47, (size-1)/2
    reference = np.zeros((size, size), np.uint8)
    for first in range(0, size, 64):
        x, y = np.meshgrid(np.arange(size), np.arange(first, min(size, first+64)))
        points = np.column_stack(((x.ravel()-center)/scale, (y.ravel()-center)/scale))
        lat, lon, disk = geometry.unproject(points)
        indices = np.flatnonzero(disk)
        latitude, longitude = lat[indices], lon[indices]
        slab = reference[first:first+x.shape[0]].reshape(-1)
        slab[indices] = shade_atlas_points(dem, geometry, latitude, longitude)
    return reference, np.array([[scale, 0., center], [0., scale, center]])


def _photographic_footprint(gray, *, photo_mask=None):
    """Exclude empty mosaic borders without deleting dark crater interiors.

    Derive this from the photograph alone, independent of the tested pose.
    The largest connected surface avoids isolated captions; its convex hull
    retains enclosed shadows, unlike masking individual dark pixels.
    """
    kernel = max(3, round(max(gray.shape)/180) | 1)
    foreground = cv2.morphologyEx((gray > 15).astype(np.uint8), cv2.MORPH_CLOSE,
                                 np.ones((kernel, kernel), np.uint8))
    contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    footprint = np.zeros(gray.shape, np.uint8)
    if contours:
        surface = photo_mask.largest_contour(contours, gray.shape) if photo_mask is not None else max(contours, key=cv2.contourArea)
        if surface is not None:
            cv2.fillConvexPoly(footprint, cv2.convexHull(surface), 1)
    return footprint.astype(bool)


def terrain_agreement(reference, photograph, reference_to_photo, *, require_match=True, photo_mask=None):
    """Independent dense light and spatial-detail checks, outside captions."""
    h, w = photograph.shape[:2]
    gray = cv2.cvtColor(photograph, cv2.COLOR_RGB2GRAY) if photograph.ndim == 3 else photograph
    projected = cv2.warpAffine(reference, reference_to_photo, (w, h))
    available = cv2.warpAffine(np.full(reference.shape, 255, np.uint8), reference_to_photo, (w, h)) > 250
    domain = np.zeros((h, w), bool)
    domain[round(h*.08):round(h*.93), round(w*.05):round(w*.95)] = True
    domain &= available & _photographic_footprint(gray, **mask_kwargs(photo_mask)) & ((gray > 15) | (projected > 15))
    if photo_mask is not None:
        domain &= photo_mask.raster(gray.shape, padding=max(3, round(max(h, w)/88*3))) != 0
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


def refinement_consensus(light, detail, evidence):
    """Certify a fresh local render, including a tightly checked tonal mismatch.

    Absolute brightness can differ even after a valid physical view correction.
    That exception needs strong dense detail plus independently held-out spatial
    geometry; it is never available to a coarse SIFT retrieval on its own.
    """
    points, coverage = evidence.get('points', 0), evidence.get('coverage', 0.)
    if light >= .6 and terrain_consensus(light, detail, points, coverage):
        return True
    before = evidence.get('validation_before_px', float('nan'))
    after = evidence.get('validation_after_px', float('nan'))
    if (not np.isfinite([light, detail, coverage, before, after]).all() or
            light < .5 or detail < .5 or points < 80 or coverage < .25 or
            after > 1.5 or after > before*.75 or before-after < .5):
        return False
    folds = evidence.get('validation_folds', [])
    return (len({fold['cell'] for fold in folds}) >= 4 and
            sum(fold['count'] for fold in folds) >= 80 and
            all(np.isfinite(fold['after_px']) and fold['after_px'] <= 2.5 for fold in folds) and
            sum(fold['after_px'] < fold['before_px'] for fold in folds) >= .75*len(folds))


def _pose_difference(first, second, shape):
    h, w = shape[:2]
    probes = np.array([[w/2, h/2], [w*.75, h/2], [w/2, h*.75]])
    inverse = np.linalg.inv(np.vstack((first, [0., 0., 1.])))[:2]
    return np.linalg.norm(transform_points(second, transform_points(inverse, probes))-probes, axis=1).mean()


def _foreground_inside(matrix, foreground):
    inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
    return not len(foreground) or (np.linalg.norm(transform_points(inverse, foreground), axis=1) < 1.015).mean() >= .95


def _adopt_refinement(result, refined):
    result.matrix, result.rms_px = refined.matrix, refined.rms_px
    result.projection_geometry = refined.geometry
    result.refinement = refined.details
    result.projection_surface = 'terrain' if refined.details.get('relief_aware') is True else 'sphere'
    result.image_inliers = refined.details['points']
    result.coverage = refined.details['coverage']
    result.texture_correlation = refined.details['light_before_after'][1]
    result.score = result.image_inliers*(result.texture_correlation+refined.details['detail_before_after'][1])


def identify_from_terrain(image, geometry, cache, *, atlas_size=4000, tile_size=1536, refine=True, catalog=None, photo_mask=None):
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
    try:
        prepared_photo = prepare_registration_photo(photograph, contrast_threshold=.01, **mask_kwargs(photo_mask))
    except ValueError as exc:
        raise IdentificationError(str(exc)) from exc
    sample = cv2.resize(gray[:round(gray.shape[0]*.93)], (60, 54), interpolation=cv2.INTER_AREA)
    yy, xx = np.nonzero(sample > 30)
    foreground = np.column_stack(((xx+.5)*w/60, (yy+.5)*round(h*.93)/54))
    if photo_mask is not None:
        foreground = foreground[photo_mask.allows(foreground, image.shape)]
    # Rounded dimensions have independent x/y scales, retained in the pose.
    sx, sy = photograph.shape[1]/w, photograph.shape[0]/h
    tile_size = min(tile_size, atlas_size)
    count = max(1, math.ceil((atlas_size-tile_size)/(tile_size*.82))+1)
    starts = np.unique(np.rint(np.linspace(0, atlas_size-tile_size, count)).astype(int))
    solutions = []
    pending = []
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
                                      contrast_threshold=.01, min_inlier_fraction=.25,
                                      prepared_photo=prepared_photo, **mask_kwargs(photo_mask))
            except ValueError:
                continue
            if match.inliers < 12 or match.coverage < .06:
                continue
            offset = np.array([[1., 0., -x], [0., 1., -y], [0., 0., 1.]])
            reference_to_photo = (np.vstack((match.matrix, [0., 0., 1.])) @ offset)[:2]
            try:
                light, detail = terrain_agreement(reference, photograph, reference_to_photo, require_match=False, **mask_kwargs(photo_mask))
            except IdentificationError:
                continue
            sparse_seed = match.inliers < 18
            if sparse_seed and not (refine and match.coverage >= .15 and light >= .6 and detail >= .35):
                continue
            matrix = (np.vstack((reference_to_photo, [0., 0., 1.])) @ np.vstack((projection, [0., 0., 1.])))[:2]
            matrix = np.diag([1/sx, 1/sy]) @ matrix
            if not _foreground_inside(matrix, foreground):
                continue
            score = match.inliers*(light+detail)
            result = IdentificationResult(matrix, [], match.rms_px/min(sx, sy), float(score), 0,
                                          "LOLA slope + cast-shadow tiles / symmetric SIFT / JPL projection",
                                          match.inliers, match.coverage, 0, light)
            if not sparse_seed and terrain_consensus(light, detail, match.inliers, match.coverage):
                solutions.append(result)
            elif refine and match.coverage >= .08 and light >= .25 and detail >= .04:
                # A coarse sphere can retrieve the correct oblique region but
                # displace its relief/shadows. This only nominates a candidate:
                # fresh relief rendering and held-out validation must certify it.
                # Sparse retrieval is useful for blurred polar photographs,
                # but cannot certify the final result by itself.
                pending.append(result)
    if pending:
        from .terrain_refinement import refine_terrain_pose
        pending.sort(key=lambda result: -result.score)
        distinct = []
        best = max(solutions, key=lambda result: result.score) if solutions else None
        for candidate in pending:
            # A coarse accepted pose must not hide a stronger candidate in a
            # different region. Avoid spending refinement on weak alternatives
            # or duplicate retrievals of an already accepted map pose.
            if best is not None and (candidate.score <= best.score*.8 or
                    _pose_difference(best.matrix, candidate.matrix, image.shape) <= max(w, h)*.08):
                continue
            if all(_pose_difference(other.matrix, candidate.matrix, image.shape) > max(w, h)*.08 for other in distinct):
                distinct.append(candidate)
        # Overlapping tiles often retrieve the same pose. Refine it once, and
        # at most one competing region; preserve a bounded fallback cost.
        if distinct:
            dem = ElevationMap.load(download_basic_dem(cache))
            try:
                for candidate in distinct[:2]:
                    refined = refine_terrain_pose(image, geometry, candidate.matrix, dem, relief_aware=True, **mask_kwargs(photo_mask))
                    if refined is None:
                        continue
                    light = refined.details['light_before_after'][1]
                    detail = refined.details['detail_before_after'][1]
                    if (not refinement_consensus(light, detail, refined.details) or
                            not _foreground_inside(refined.matrix, foreground)):
                        continue
                    _adopt_refinement(candidate, refined)
                    candidate.method += ' / relief-aware refinement'
                    solutions.append(candidate)
            finally:
                dem.close()
    if not solutions:
        raise IdentificationError("高程阴影参考也未找到通过纹理与分布验证的月面区域。")
    solutions.sort(key=lambda result: -result.score)
    result = solutions[0]
    for other in solutions[1:]:
        difference = _pose_difference(result.matrix, other.matrix, image.shape)
        if difference > max(w, h)*.08:
            result.alternatives += 1
            if other.score > result.score*.8:
                raise IdentificationError("出现多个接近的高程纹理匹配，未采用结果。")
    if refine and result.refinement is None:
        from .terrain_refinement import refine_terrain_pose
        dem = ElevationMap.load(download_basic_dem(cache))
        try:
            refined = refine_terrain_pose(image, geometry, result.matrix, dem, **mask_kwargs(photo_mask))
        finally:
            dem.close()
        if refined is not None:
            _adopt_refinement(result, refined)
    if catalog is not None and result.refinement and result.refinement.get('relief_aware'):
        from .terrain_rims import trace_catalog_rims
        dem = ElevationMap.load(download_basic_dem(cache))
        try:
            result.crater_rims = trace_catalog_rims(dem, result.projection_geometry or geometry,
                                                   result.matrix, catalog, image.shape)
        finally:
            dem.close()
    return result
