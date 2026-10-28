# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Independently certify a unique, weak-albedo limb pose with local LOLA detail.

Only failed albedo/limb searches enter this bounded fallback. A provisional
physical fit retrieves more terrain; it cannot itself authorize a map pose.
The final fit must pass the ordinary four-region holdouts, a fresh terrain
render, and the independently photographed long lunar limb.
"""
import numpy as np

from ._opencv import cv2
from .atlas import _limb_error
from .craters import _lunar_surface
from .identification import IdentificationError, IdentificationResult
from .pose_refinement import propose_view, refine_view
from .recognition_mask import mask_kwargs
from .registration import transform_points
from .terrain import ElevationMap, download_basic_dem
from .terrain_identification import terrain_agreement, refinement_consensus
from .terrain_refinement import local_correspondences, render_local_reference


def identify_limb_terrain(image, geometry, matrix, limb, cache, *, photo_mask=None):
    """Verify one limb/phase/albedo seed; return None when evidence is weak."""
    surface = _lunar_surface(image, **mask_kwargs(photo_mask))
    yy, xx = np.nonzero(surface)
    if not len(xx):
        return None
    h, w = image.shape[:2]
    ratio = np.array([w/surface.shape[1], h/surface.shape[0]])
    pad = max(4., limb[1]*.025)
    lower = np.maximum(np.floor(np.array([xx.min(), yy.min()])*ratio-pad).astype(int), 0)
    upper = np.minimum(np.ceil(np.array([xx.max()+1, yy.max()+1])*ratio+pad).astype(int), [w, h])
    crop = image[lower[1]:upper[1], lower[0]:upper[0]]
    crop_mask = photo_mask.cropped(lower, crop.shape, image.shape) if photo_mask is not None else None
    factor = min(1., 1200/max(crop.shape[:2]))
    photo = cv2.resize(crop, (round(crop.shape[1]*factor), round(crop.shape[0]*factor)),
                       interpolation=cv2.INTER_AREA) if factor < 1 else crop
    sx, sy = photo.shape[1]/crop.shape[1], photo.shape[0]/crop.shape[0]
    working = matrix.copy()
    working[:, 2] -= lower
    working = np.diag([sx, sy])@working
    identity = np.array([[1., 0., 0.], [0., 1., 0.]])

    def original(camera):
        result = np.diag([1/sx, 1/sy])@camera
        result[:, 2] += lower
        return result

    tolerance = max(3., limb[1]*.008, limb[2]*4)
    dem = ElevationMap.load(download_basic_dem(cache))
    try:
        reference = render_local_reference(dem, geometry, working, photo.shape)
        source, target = local_correspondences(reference, photo, **mask_kwargs(crop_mask))
        proposal = propose_view(geometry, working, source, target, photo.shape)
        if proposal is None:
            return None
        proposed_geometry, proposed_matrix = proposal
        if _limb_error(original(proposed_matrix), proposed_geometry, limb) > tolerance:
            return None
        aligned = render_local_reference(dem, proposed_geometry, proposed_matrix, photo.shape)
        source, target = local_correspondences(aligned, photo, **mask_kwargs(crop_mask))
        if len(source) < 40:
            return None
        # Re-extracted source points refer to the provisional view. Express
        # them in the ORIGINAL ephemeris before spatial holdout validation.
        # Direction corrections must never accumulate across the two passes.
        inverse = np.linalg.inv(np.vstack((proposed_matrix, [0., 0., 1.])))[:2]
        lat, lon, visible = proposed_geometry.unproject(transform_points(inverse, source))
        source = transform_points(working, geometry.project(lat[visible], lon[visible])[0])
        refined = refine_view(geometry, working, source, target[visible], photo.shape, max_view_offset_deg=3.)
        if refined is None or _limb_error(original(refined.matrix), refined.geometry, limb) > tolerance:
            return None
        fresh = render_local_reference(dem, refined.geometry, refined.matrix, photo.shape)
        try:
            before = terrain_agreement(reference, photo, identity, require_match=False, **mask_kwargs(crop_mask))
            after = terrain_agreement(fresh, photo, identity, require_match=False, **mask_kwargs(crop_mask))
        except IdentificationError:
            return None
        if (not refinement_consensus(*after, refined.details)
                or after[0] < before[0] or after[1] < before[1]+.02):
            return None
    finally:
        dem.close()
    refined.matrix = original(refined.matrix)
    refined.rms_px /= min(sx, sy)
    details = refined.details
    details.update(working_shape=list(photo.shape[:2]), light_before_after=[before[0], after[0]],
                   detail_before_after=[before[1], after[1]],
                   limb_fit_rms_px=limb[2], limb_samples=limb[3],
                   limb_after_px=_limb_error(refined.matrix, refined.geometry, limb),
                   retrieval='limb-seeded fresh terrain correspondences')
    for key in ('validation_before_px', 'validation_after_px'):
        details[key] /= min(sx, sy)
    for fold in details['validation_folds']:
        fold['before_px'] /= min(sx, sy)
        fold['after_px'] /= min(sx, sy)
    return IdentificationResult(refined.matrix, [], refined.rms_px, float(details['points']), 0,
                                'lunar limb / phase + albedo seed / spatially validated LOLA texture / JPL projection',
                                image_inliers=details['points'], coverage=details['coverage'],
                                limb_inliers=limb[3], texture_correlation=after[1],
                                projection_geometry=refined.geometry, refinement=details)
