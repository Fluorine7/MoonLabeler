# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Bounded view-direction refinement, verified by spatially held-out points.

The fitted direction is an image-derived projection correction, not a recovered
observing site or measured libration. No per-crater deformation is allowed.
"""
from dataclasses import dataclass
import numpy as np
import cv2
from .geometry import Geometry, unit
from .registration import transform_points


@dataclass
class PoseRefinement:
    geometry: Geometry
    matrix: np.ndarray
    rms_px: float
    details: dict


def shifted_geometry(geometry, offsets_deg):
    observer = unit(geometry.observer + np.tan(np.radians(offsets_deg[0]))*geometry.right
                    + np.tan(np.radians(offsets_deg[1]))*geometry.north)
    north = unit(geometry.north - np.dot(geometry.north, observer)*observer)
    right = unit(np.cross(north, observer))
    return Geometry(observer, right, north, geometry.sun.copy(), geometry.distance_km, geometry.utc)


def _camera(params):
    c, s = np.cos(params[3]), np.sin(params[3])
    return np.exp(params[2])*np.array([[c, -s], [s, c]])


def _predict(params, geometry, matrix, lat, lon):
    points = shifted_geometry(geometry, params[:2]).project(lat, lon)[0]
    return transform_points(matrix, points) @ _camera(params).T + params[4:6]


def _fit(geometry, matrix, lat, lon, target, free_view):
    params = np.zeros(6)
    free = np.arange(6) if free_view else np.arange(2, 6)
    steps = np.array([1e-4, 1e-4, 1e-5, 1e-5, .001, .001])
    damping = 1e-4
    def cost(errors):
        return np.sum(np.where(errors < 3, errors**2, 6*errors-9))
    for _ in range(60):
        predicted = _predict(params, geometry, matrix, lat, lon)
        residual = (predicted-target).ravel()
        errors = np.linalg.norm(predicted-target, axis=1)
        weights = np.repeat(np.minimum(1, 3/np.maximum(errors, 1e-8)), 2)
        jacobian = np.column_stack([
            ((_predict(params+np.eye(6)[j]*steps[j], geometry, matrix, lat, lon)-predicted)/steps[j]).ravel()
            for j in free])
        normal = jacobian.T @ (weights[:, None]*jacobian)
        rhs = jacobian.T @ (weights*residual)
        try:
            delta = np.linalg.solve(normal + damping*np.diag(np.maximum(np.diag(normal), 1e-8)), rhs)
        except np.linalg.LinAlgError:
            return None
        proposal = params.copy()
        proposal[free] -= delta
        proposal[:2] = np.clip(proposal[:2], -1.5, 1.5)
        proposal[2:4] = np.clip(proposal[2:4], -.1, .1)
        if cost(np.linalg.norm(_predict(proposal, geometry, matrix, lat, lon)-target, axis=1)) < cost(errors):
            params = proposal
            damping = max(damping/3, 1e-8)
            if np.linalg.norm(delta) < 1e-7:
                break
        else:
            damping *= 10
            if damping > 1e12:
                break
    return params


def refine_view(geometry, matrix, source_pixels, target_pixels, image_shape):
    """Return a validated six-parameter fit, or None to retain the original.

    Inputs are independently matched reference/photo pixels at a common working
    resolution. Repeated keypoint orientations must already be deduplicated.
    """
    source, target = np.asarray(source_pixels, float), np.asarray(target_pixels, float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 2:
        raise ValueError('Correspondences must have matching N x 2 shapes')
    if len(source) < 40 or not np.isfinite(source).all() or not np.isfinite(target).all():
        return None
    h, w = image_shape[:2]
    coverage = cv2.contourArea(cv2.convexHull(target.astype(np.float32)))/(h*w)
    if coverage < .18:
        return None
    inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
    lat, lon, visible = geometry.unproject(transform_points(inverse, source))
    if not visible.all():
        return None
    cell_xy = np.clip((source/np.array([w, h])*3).astype(int), 0, 2)
    cells = cell_xy[:, 0] + 3*cell_xy[:, 1]
    rms = lambda residual: float(np.sqrt(np.mean(np.sum(residual**2, axis=1))))
    fit = _fit(geometry, matrix, lat, lon, target, True)
    if fit is None or np.linalg.norm(fit[:2]) > 1.25:
        return None
    folds = []
    for cell in np.unique(cells):
        hold = cells == cell
        if hold.sum() < 3 or (~hold).sum() < 20:
            continue
        baseline = _fit(geometry, matrix, lat[~hold], lon[~hold], target[~hold], False)
        candidate = _fit(geometry, matrix, lat[~hold], lon[~hold], target[~hold], True)
        if baseline is None or candidate is None or np.linalg.norm(candidate[:2]-fit[:2]) > .35:
            return None
        before = rms(_predict(baseline, geometry, matrix, lat[hold], lon[hold])-target[hold])
        after = rms(_predict(candidate, geometry, matrix, lat[hold], lon[hold])-target[hold])
        if after > before*1.1 + .25:
            return None
        folds.append({'cell': int(cell), 'count': int(hold.sum()), 'before_px': before, 'after_px': after})
    if len(folds) < 4 or sum(f['after_px'] < f['before_px'] for f in folds) < .75*len(folds):
        return None
    count = sum(f['count'] for f in folds)
    before = np.sqrt(sum(f['count']*f['before_px']**2 for f in folds)/count)
    after = np.sqrt(sum(f['count']*f['after_px']**2 for f in folds)/count)
    if after > before*.85 or before-after < .25:
        return None
    camera = _camera(fit)
    updated = np.column_stack((camera@matrix[:, :2], camera@matrix[:, 2]+fit[4:6]))
    details = {'view_offset_deg': fit[:2].tolist(), 'points': len(source), 'coverage': coverage,
               'validation_before_px': float(before), 'validation_after_px': float(after),
               'validation_folds': folds, 'base_geometry': geometry.to_dict()}
    return PoseRefinement(shifted_geometry(geometry, fit[:2]), updated,
                          rms(_predict(fit, geometry, matrix, lat, lon)-target), details)
