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

from .geometry import MOON_RADIUS_KM, surface_vectors
from .identification import IdentificationError, IdentificationResult
from .pose_refinement import refine_view
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


def _photographed_limb(image, matrix):
    """Measure a long outer arc in a moon-sized crop, ignoring canvas padding."""
    from .limb import fit_lunar_limb  # limb also uses render_atlas
    scale = np.linalg.norm(matrix[:, 0])
    center = matrix[:, 2]
    height, width = image.shape[:2]
    # A partial lunar field cannot independently certify the whole sphere.
    if scale < 50 or np.any(center-scale < 0) or np.any(center+scale >= [width, height]):
        return None
    lower = np.maximum(np.floor(center-1.1*scale).astype(int), 0)
    upper = np.minimum(np.ceil(center+1.1*scale).astype(int), [width, height])
    try:
        measured_center, radius, rms, count = fit_lunar_limb(image[lower[1]:upper[1], lower[0]:upper[0]])
    except IdentificationError:
        return None
    return measured_center+lower, radius, rms, count


def _limb_error(matrix, geometry, limb):
    center, radius, _, _ = limb
    predicted_radius = np.linalg.norm(matrix[:, 0])/np.sqrt(1-(MOON_RADIUS_KM/geometry.distance_km)**2)
    # Radial RMS over a complete circle, to first order in the small displacement.
    return float(np.hypot(np.linalg.norm(matrix[:, 2]-center)/np.sqrt(2), predicted_radius-radius))


def _refine_atlas_pose(image, geometry, matrix, projection, match, limb):
    if match.source_points is None or match.target_points is None:
        return None
    source, target = match.source_points, match.target_points
    inverse = np.linalg.inv(np.vstack((projection, [0., 0., 1.])))[:2]
    model = transform_points(inverse, source)
    keep = np.linalg.norm(model, axis=1) < .92
    source, target, model = source[keep], target[keep], model[keep]
    # Multiple SIFT orientations at one point are one observation, not evidence
    # for separate held-out terrain. Keep at most 1000 distributed observations.
    _, indices = np.unique(np.rint(np.column_stack((source, target))*8), axis=0, return_index=True)
    indices.sort()
    if len(indices) > 1000:
        indices = indices[np.linspace(0, len(indices)-1, 1000).astype(int)]
    target, model = target[indices], model[indices]
    scale = np.linalg.norm(matrix[:, 0])
    height, width = image.shape[:2]
    lower = np.maximum(matrix[:, 2]-scale, 0.)
    upper = np.minimum(matrix[:, 2]+scale, [width, height])
    if np.any(upper <= lower):
        return None
    # Spatial validation covers the observed lunar field, not its black margins.
    # Bound the working resolution so high-resolution photographs cost no more.
    factor = min(1., 1200/max(upper-lower))
    working = matrix.copy()*factor
    working[:, 2] -= lower*factor
    source = transform_points(working, model)
    target = (target-lower)*factor
    shape = tuple((upper-lower)[::-1]*factor)
    result = refine_view(geometry, working, source, target, shape,
                         max_view_offset_deg=3. if limb is not None else 1.25)
    if result is None:
        return None
    result.matrix /= factor
    result.matrix[:, 2] += lower
    result.rms_px /= factor
    for key in ('validation_before_px', 'validation_after_px'):
        result.details[key] /= factor
    for fold in result.details['validation_folds']:
        fold['before_px'] /= factor
        fold['after_px'] /= factor
    if limb is not None:
        before = _limb_error(matrix, geometry, limb)
        after = _limb_error(result.matrix, result.geometry, limb)
        tolerance = max(2.5, limb[1]*.006, limb[2]*3)
        if after > tolerance or (np.linalg.norm(result.details['view_offset_deg']) > 1.25 and after > before*.85):
            return None
        result.details.update(limb_before_px=before, limb_after_px=after,
                              limb_fit_rms_px=limb[2], limb_samples=limb[3])
    return result


def _eyepiece_or_raise(image, geometry, projection, match, message):
    from .eyepiece import identify_eyepiece
    try:
        return identify_eyepiece(image, geometry, projection, match)
    except IdentificationError:
        raise IdentificationError(message) from None


def identify_from_atlas(image, geometry):
    """No supplied region, camera angle, mirror, scale or feature names."""
    reference, projection = render_atlas(geometry)
    match = auto_register(reference, image)
    # The map search has no user-supplied region, so require more evidence than
    # the existing manually selected reference matching tool.
    if match.inliers < 24 or match.inliers/match.matches < .45 or match.coverage < .04:
        raise IdentificationError("纹理对应点太少或过于集中，未采用配准。")
    matrix = (np.vstack((match.matrix, [0., 0., 1.])) @ np.vstack((projection, [0., 0., 1.])))[:2]
    limb = _photographed_limb(image, matrix)
    refined = _refine_atlas_pose(image, geometry, matrix, projection, match, limb)
    if refined is not None:
        matrix = refined.matrix
    effective_geometry = refined.geometry if refined is not None else geometry
    if limb is not None and _limb_error(matrix, effective_geometry, limb) > max(3., limb[1]*.008, limb[2]*4):
        return _eyepiece_or_raise(image, geometry, projection, match, "纹理配准与照片月缘不一致，未采用配准。")
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    height, width = gray.shape
    sample = cv2.resize(gray[:round(height*.93)], (60, 54), interpolation=cv2.INTER_AREA)
    yy, xx = np.nonzero(sample > 30)
    foreground = np.column_stack(((xx+.5)*width/60, (yy+.5)*round(height*.93)/54))
    if len(foreground):
        inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
        if (np.linalg.norm(transform_points(inverse, foreground), axis=1) < 1.015).mean() < .95:
            return _eyepiece_or_raise(image, geometry, projection, match, "纹理配准与照片中的月盘范围不一致。")
    method = "LROC albedo / symmetric SIFT / JPL projection"
    if refined is not None:
        method += " / spatially validated view refinement"
    return IdentificationResult(matrix, [], refined.rms_px if refined is not None else match.rms_px,
                                float(match.inliers), 0, method, match.inliers, match.coverage,
                                projection_geometry=refined.geometry if refined is not None else None,
                                refinement=refined.details if refined is not None else None)
