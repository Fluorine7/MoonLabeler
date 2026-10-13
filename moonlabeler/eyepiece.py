# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Conservative whole-field pincushion recovery for afocal photographs.

Only a strong pre-existing atlas match can propose this model. Spatially held
out textures AND a long independently measured illuminated limb must validate
it. This is an image-derived correction, not a camera/libration measurement.
The photograph itself is never resampled.
"""
import cv2
import numpy as np
from .geometry import surface_vectors
from .identification import IdentificationError, IdentificationResult
from .pose_refinement import shifted_geometry
from .registration import transform_points


def distort_points(points, distortion):
    points = np.asarray(points, float)
    if not distortion:
        return points
    delta = (points-np.asarray(distortion['center']))/distortion['scale']
    return points + distortion['k']*delta*np.sum(delta**2, axis=-1, keepdims=True)*distortion['scale']


def distortion_jacobian(points, distortion):
    delta = (np.asarray(points)-distortion['center'])/distortion['scale']
    return ((1+distortion['k']*np.sum(delta**2, axis=-1))[:, None, None]*np.eye(2)
            + 2*distortion['k']*delta[:, :, None]*delta[:, None, :])


def _radial(params, points):
    a, b, tx, ty, k, cx, cy = params[:7]
    camera = points @ np.array([[a, b], [-b, a]]) + [tx, ty]
    delta = camera-[cx, cy]
    return camera+k*delta*np.sum(delta**2, axis=1, keepdims=True)


def _predict(params, coordinates, geometry, sign):
    points = shifted_geometry(geometry, params[7:]).project(coordinates[:, 0], coordinates[:, 1])[0]
    return _radial(params, points*[sign, 1])


def _fit(initial, coordinates, target, geometry, sign, scale):
    params = initial.copy()
    damping = .001
    def loss(errors):
        return np.sum(np.where(errors < 3, errors**2, 6*errors-9))
    for _ in range(80):
        predicted = _predict(params, coordinates, geometry, sign)
        residual = (predicted-target).ravel()
        errors = np.linalg.norm(predicted-target, axis=1)*scale
        weights = np.repeat(np.minimum(1, 3/np.maximum(errors, 1e-8)), 2)
        jacobian = np.column_stack([
            ((_predict(params+np.eye(9)[i]*1e-5, coordinates, geometry, sign)-predicted)/1e-5).ravel()
            for i in range(9)])
        normal = jacobian.T @ (weights[:, None]*jacobian)
        try:
            delta = np.linalg.solve(normal+damping*np.diag(np.maximum(np.diag(normal), 1e-8)),
                                    jacobian.T @ (weights*residual))
        except np.linalg.LinAlgError:
            return None
        trial = params-delta
        trial[4] = np.clip(trial[4], 0, .6)
        trial[5:7] = np.clip(trial[5:7], -.7, .7)
        trial[7:] = np.clip(trial[7:], -1.25, 1.25)
        if loss(np.linalg.norm(_predict(trial, coordinates, geometry, sign)-target, axis=1)*scale) < loss(errors):
            params = trial
            damping = max(1e-8, damping/3)
            if np.linalg.norm(delta) < 1e-7:
                break
        else:
            damping *= 10
            if damping > 1e12:
                break
    return params


def _limb_check(image, geometry, params, center, scale, sign, *, field_area=None):
    """Use observed boundary pixels, not a fitted circle, as independent data."""
    h, w = image.shape[:2]
    # Bound contour/distance work on large photographs.
    factor = min(1., 1400/max(h, w))
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    if factor < 1:
        gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    threshold = max(30, float(np.percentile(gray, 99))*.25)
    contours, _ = cv2.findContours((gray > threshold).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise IdentificationError('目镜校正缺少可验证的受光月缘。')
    contour = max(contours, key=cv2.contourArea)
    area = h*w if field_area is None else min(h*w, field_area)
    if cv2.contourArea(contour)/factor**2 < area*.1:
        raise IdentificationError('目镜校正需要较完整的月面视野。')
    boundary = np.ones(gray.shape, np.uint8)
    cv2.drawContours(boundary, [contour], -1, 0, 1)
    distances = cv2.distanceTransform(boundary, cv2.DIST_L2, 5)/factor
    angles = np.linspace(0, 2*np.pi, 720, endpoint=False)
    circle = np.column_stack((np.cos(angles), np.sin(angles)))
    # .999 lies just inside the apparent lunar limb. Do not include terminator
    # or the unilluminated, invisible half of a hypothetical complete circle.
    lat, lon, _ = geometry.unproject(circle*.999)
    margin = .02 if np.dot(geometry.observer, geometry.sun) > .98 else .15
    illuminated = surface_vectors(lat, lon) @ geometry.sun > margin
    predicted = _radial(params, circle*[sign, 1])*scale+center
    keep = (illuminated & (predicted[:, 0] > 3) & (predicted[:, 0] < w-4)
            & (predicted[:, 1] > 3) & (predicted[:, 1] < h-4))
    if keep.sum() < 240:
        raise IdentificationError('目镜校正的可验证月缘不足 120°。')
    xy = np.rint(predicted[keep]*factor).astype(int)
    errors = distances[xy[:, 1], xy[:, 0]]
    # Four working pixels bound the discretization of a downsampled boundary;
    # enlarging the source canvas must not enlarge optical fitting parameters.
    tolerance = max(4./factor, scale*.008)
    if np.percentile(errors, 95) > tolerance or np.median(errors) > tolerance*.7:
        raise IdentificationError('目镜校正仍与实际受光月缘不一致。')
    return circle[keep], float(np.percentile(errors, 95)), float(keep.sum()/2)


def identify_eyepiece(image, geometry, projection, match, *, limb=None):
    if match.inliers < 64 or match.source_matches is None or match.target_matches is None:
        raise IdentificationError('目镜校正缺少可靠的纹理对应点。')
    source, target = match.source_matches, match.target_matches
    inverse = np.linalg.inv(np.vstack((projection, [0., 0., 1.])))[:2]
    model = transform_points(inverse, source)
    lat, lon, visible = geometry.unproject(model)
    # Multiple SIFT orientations at the same location are one observation.
    _, unique = np.unique(np.rint(np.column_stack((source, target))*8), axis=0, return_index=True)
    indices = unique[visible[unique]]
    if len(indices) > 800:
        indices = indices[np.linspace(0, len(indices)-1, 800).astype(int)]
    coordinates = np.column_stack((lat, lon))[indices]
    target = target[indices]
    if len(target) < 100:
        raise IdentificationError('目镜校正需要至少 100 个分散的纹理对应点。')
    h, w = image.shape[:2]
    camera = (np.vstack((match.matrix, [0, 0, 1])) @ np.vstack((projection, [0, 0, 1])))[:2]
    area = h*w
    scale, center = max(h, w)/2, np.array([w/2, h/2])
    if match.coverage < .08:
        if limb is None:
            from .atlas import _photographed_limb
            limb = _photographed_limb(image, camera)
        if limb is not None:
            area = min(area, 4*limb[1]**2)
            scale, center = limb[1], limb[0]
    sign = -1 if np.linalg.det(camera[:, :2]) < 0 else 1
    initial = np.array([camera[0, 0]/sign/scale, camera[1, 0]/sign/scale,
                        *( (camera[:, 2]-center)/scale ), .1, 0., 0., 0., 0.])
    normalized = (target-center)/scale
    params = _fit(initial, coordinates, normalized, geometry, sign, scale)
    if params is None or not .015 < params[4] < .55 or np.linalg.norm(params[7:]) > 1.25:
        raise IdentificationError('目镜校正参数未通过验证。')
    errors = np.linalg.norm(_predict(params, coordinates, geometry, sign)-normalized, axis=1)*scale
    inliers = errors < 3
    coverage = cv2.contourArea(cv2.convexHull(target[inliers].astype(np.float32)))/area
    if inliers.sum() < 100 or inliers.mean() < .8 or coverage < .08:
        raise IdentificationError('目镜校正的纹理验证不足。')
    effective = shifted_geometry(geometry, params[7:])
    rim, limb_error, arc = _limb_check(image, effective, params, center, scale, sign, field_area=area)
    predicted_rim = _radial(params, rim*[sign, 1])*scale
    cells = np.minimum(((target-target.min(0))/np.maximum(np.ptp(target, axis=0), 1)*3).astype(int), 2)
    cells = cells[:, 0]+3*cells[:, 1]
    if np.count_nonzero(np.bincount(cells, minlength=9) >= 10) < 4:
        # Isolated bad descriptors must not stretch the grid until a crescent's
        # consistent textures share only a few cells. All original matches,
        # including outliers, still enter the held-out checks below.
        lower = target[inliers].min(0)
        span = np.maximum(np.ptp(target[inliers], axis=0), 1)
        grid = np.clip(((target-lower)/span*3).astype(int), 0, 2)
        cells = grid[:, 0]+3*grid[:, 1]
    folds = []
    for cell in np.unique(cells):
        hold = cells == cell
        if hold.sum() < 10:
            continue
        other = _fit(initial, coordinates[~hold], normalized[~hold], geometry, sign, scale)
        if other is None or np.linalg.norm(other[7:]) > 1.25:
            raise IdentificationError('目镜校正的分区验证失败。')
        check = np.linalg.norm(_predict(other, coordinates[hold], geometry, sign)-normalized[hold], axis=1)*scale
        rim_delta = np.linalg.norm(_radial(other, rim*[sign, 1])*scale-predicted_rim, axis=1)
        # Evaluate every held-out descriptor match, including outliers. At least
        # 80% must agree without fitting that region; do not cherry-pick inliers.
        if np.mean(check < 4) < .8 or np.percentile(rim_delta, 95) > max(3., scale*.006):
            raise IdentificationError('目镜校正的分区预测不稳定。')
        folds.append({'cell': int(cell), 'count': int(hold.sum()),
                      'median_px': float(np.median(check)), 'within_4px': float(np.mean(check < 4))})
    if len(folds) < 4:
        raise IdentificationError('目镜校正缺少独立的验证区域。')
    a, b, tx, ty, k, cx, cy = params[:7]
    matrix = np.array([[a*sign, -b, tx], [b*sign, a, ty]])*scale
    matrix[:, 2] += center
    return IdentificationResult(matrix, [], float(np.sqrt(np.mean(errors[inliers]**2))),
        float(inliers.sum()), 0, 'LROC albedo / validated eyepiece distortion', int(inliers.sum()), coverage,
        projection_geometry=effective,
        refinement={'view_offset_deg': params[7:].tolist(), 'base_geometry': geometry.to_dict(),
                    'validation_folds': folds, 'limb_p95_px': limb_error, 'limb_arc_deg': arc},
        lens_distortion={'center': (center+scale*np.array([cx, cy])).tolist(), 'scale': float(scale), 'k': float(k)})
