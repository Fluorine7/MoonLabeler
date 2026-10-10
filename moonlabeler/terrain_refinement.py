# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Local reference refinement using the same small, cached LOLA DEM."""
import cv2
import numpy as np
from .geometry import surface_vectors
from .registration import transform_points, _gray
from .terrain import terrain_shadow
from .pose_refinement import refine_view, refine_camera


def render_local_reference(dem, geometry, matrix, shape):
    """Spherical slope/shadow rendering at photograph scale, in bounded strips."""
    h, w = shape[:2]
    inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
    output = np.zeros((h, w), np.uint8)
    for first in range(0, h, 64):
        xx, yy = np.meshgrid(np.arange(w), np.arange(first, min(h, first+64)))
        lat, lon, visible = geometry.unproject(transform_points(inverse, np.column_stack((xx.ravel(), yy.ravel()))))
        indices = np.flatnonzero(visible)
        lat, lon = lat[indices], lon[indices]
        radial = surface_vectors(lat, lon)
        height, normal = dem.sample(lat, lon), dem.normals(lat, lon)
        incidence = np.maximum(normal@geometry.sun, 0)
        emission = np.maximum(normal@geometry.observer, 0)
        valid = np.isfinite(height) & np.isfinite(normal).all(axis=1) & (incidence > 0) & (emission > 0)
        light = np.sqrt(np.clip(2*incidence/(incidence+emission+1e-8), 0, 1))
        light[~valid] = 0
        if valid.any():
            hidden = terrain_shadow(dem, radial[valid], height[valid], geometry.sun, steps=12)
            light[np.flatnonzero(valid)[hidden]] = 0
        slab = np.zeros(xx.size, np.float32)
        slab[indices] = np.nan_to_num(light)*220
        output[first:first+xx.shape[0]] = slab.reshape(xx.shape).astype(np.uint8)
    return output


def local_correspondences(reference, photograph):
    """Retrieve mutually matched, nearby points; deduplicate SIFT orientations."""
    sift = cv2.SIFT_create(nfeatures=10000, contrastThreshold=.01)
    mask = np.full(reference.shape, 255, np.uint8)
    mask[round(reference.shape[0]*.93):] = 0
    rk, rd = sift.detectAndCompute(_gray(reference)[0], mask)
    pk, pd = sift.detectAndCompute(_gray(photograph)[0], mask)
    empty = np.empty((0, 2), float)
    if rd is None or pd is None:
        return empty, empty.copy()
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    forward, reverse = matcher.knnMatch(rd, pd, k=2), matcher.knnMatch(pd, rd, k=2)
    backwards = {pair[0].queryIdx: pair[0].trainIdx for pair in reverse
                 if len(pair) == 2 and pair[0].distance < .85*pair[1].distance}
    good = [pair[0] for pair in forward if len(pair) == 2 and pair[0].distance < .85*pair[1].distance
            and backwards.get(pair[0].trainIdx) == pair[0].queryIdx]
    if len(good) < 40:
        return empty, empty.copy()
    source = np.array([rk[m.queryIdx].pt for m in good])
    target = np.array([pk[m.trainIdx].pt for m in good])
    keep = np.linalg.norm(source-target, axis=1) < 25
    source, target = source[keep], target[keep]
    if len(source) < 40:
        return empty, empty.copy()
    cv2.setRNGSeed(0)
    _, mask = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
                                        ransacReprojThreshold=5, confidence=.999, maxIters=10000)
    if mask is None:
        return empty, empty.copy()
    keep = mask.ravel().astype(bool)
    source, target = source[keep], target[keep]
    _, keep = np.unique(np.rint(source/4), axis=0, return_index=True)
    return source[keep], target[keep]


def refine_terrain_pose(image, geometry, matrix, dem, *, crater_verified=False):
    """Retain initial registration unless spatial and fresh-render checks pass."""
    from .terrain_identification import terrain_agreement
    from .identification import IdentificationError
    from .geometry import Geometry
    from .terrain_view import TerrainView
    if crater_verified:
        # The map pixels and pose fit must refer to the same 3-D surface. A
        # sphere-draped shading reference otherwise turns relief into a false
        # direction correction, particularly in oblique crater photographs.
        geometry = TerrainView.from_geometry(geometry, dem)
    h, w = image.shape[:2]
    scale = min(1., 1200/max(h, w))
    photograph = cv2.resize(image, (round(w*scale), round(h*scale)), interpolation=cv2.INTER_AREA)
    sx, sy = photograph.shape[1]/w, photograph.shape[0]/h
    working_matrix = np.diag([sx, sy])@matrix
    reference = render_local_reference(dem, geometry, working_matrix, photograph.shape)
    source, target = local_correspondences(reference, photograph)
    camera = None
    if crater_verified:
        camera = refine_camera(geometry, working_matrix, source, target, photograph.shape)
    if camera is not None:
        # Re-retrieve at the corrected camera. Keeping only matches near the
        # initial biased pose would omit valid terrain elsewhere in the photo.
        aligned = render_local_reference(dem, geometry, camera.matrix, photograph.shape)
        source, target = local_correspondences(aligned, photograph)
        result = refine_view(geometry, camera.matrix, source, target, photograph.shape)
        if result is None:
            result = camera
        else:
            result.details['camera_alignment'] = camera.details
    else:
        result = refine_view(geometry, working_matrix, source, target, photograph.shape)
    if result is None:
        return None
    identity = np.array([[1., 0., 0.], [0., 1., 0.]])
    updated = render_local_reference(dem, result.geometry, result.matrix, photograph.shape)
    try:
        before = terrain_agreement(reference, photograph, identity, require_match=False)
        after = terrain_agreement(updated, photograph, identity)
    except IdentificationError:
        return None
    # A small point residual alone cannot certify an improved projection.
    if after[0] < before[0] or after[1] < before[1] + .02:
        return None
    result.details.update({'working_shape': list(photograph.shape[:2]),
                           'light_before_after': [before[0], after[0]],
                           'detail_before_after': [before[1], after[1]],
                           'rms_working_px': result.rms_px})
    result.matrix = np.diag([1/sx, 1/sy])@result.matrix
    result.rms_px /= min(sx, sy)
    # Never retain a view whose memory-mapped DEM will close after this call.
    result.geometry = Geometry.from_dict(result.geometry.to_dict())
    return result


def refine_crater_identification(result, image, geometry, cache, catalog):
    """Refine a verified crater-region pose; optional DEM failure keeps it intact."""
    from dataclasses import replace
    from .terrain import ElevationMap, download_basic_dem
    from .terrain_rims import trace_catalog_rims
    if len(result.matches) < 7 or result.coverage < .06:
        return result
    try:
        dem = ElevationMap.load(download_basic_dem(cache))
        try:
            refined = refine_terrain_pose(image, geometry, result.matrix, dem, crater_verified=True)
            rims = trace_catalog_rims(dem, refined.geometry if refined else geometry,
                                      refined.matrix if refined else result.matrix, catalog, image.shape)
        finally:
            dem.close()
    except (ValueError, OSError):
        return result
    if refined is None:
        return replace(result, crater_rims=rims)
    refined.details['initial_crater_rms_px'] = result.rms_px
    return replace(result, matrix=refined.matrix, rms_px=refined.rms_px,
                   method=result.method + ' / local LOLA refinement',
                   projection_geometry=refined.geometry, refinement=refined.details,
                   image_inliers=refined.details['points'], coverage=refined.details['coverage'],
                   texture_correlation=refined.details['light_before_after'][1], crater_rims=rims)
