# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded terrain evidence for strongly distorted, weakly supported moon edges.

Albedo retrieval remains the fast path. This optional second stage keeps the
original pixels, supplies missing polar texture observations, and validates a
second radial term against held-out areas and a separate half of the limb.
"""
from dataclasses import replace

import numpy as np

from ._opencv import cv2
from .eyepiece import _predict, _radial, _limb_check, undistort_points
from .geometry import surface_vectors
from .identification import IdentificationError
from .pose_refinement import shifted_geometry
from .recognition_mask import mask_kwargs
from .registration import transform_points, _gray, prepare_registration_photo
from .tasks import check_cancelled
from .terrain import ElevationMap, download_basic_dem, shade_atlas_points


def needs_edge_refinement(result):
    lens = result.lens_distortion
    if not lens or lens['k'] < .08:
        return False
    error = (result.refinement or {}).get('limb_p95_px', 0.)
    return np.isfinite(error) and error > max(3., lens['scale']*.004)


def _reference(image, project, dem, maximum=1800):
    from .map_layers import photo_coordinates
    h, w = image.shape[:2]
    factor = min(1., maximum/max(h, w))
    width, height = round(w*factor), round(h*factor)
    sx, sy = width/w, height/h
    output = np.zeros((height, width), np.uint8)
    for first in range(0, height, 64):
        check_cancelled()
        x, y = np.meshgrid(np.arange(width), np.arange(first, min(height, first+64)))
        pixels = np.column_stack((x.ravel()/sx, y.ravel()/sy))
        lat, lon, visible = project.geometry.unproject(photo_coordinates(project, pixels))
        slab = np.zeros(x.size, np.uint8)
        slab[visible] = shade_atlas_points(dem, project.geometry, lat[visible], lon[visible])
        output[first:first+x.shape[0]] = slab.reshape(x.shape)
    return output, np.array([sx, sy])


def _terrain_pairs(image, project, dem, prepared_photo, photo_mask):
    reference, scales = _reference(image, project, dem)
    gray = _gray(cv2.GaussianBlur(reference, (0, 0), .65))[0]
    mask = photo_mask.raster(gray.shape, padding=2) if photo_mask is not None else None
    sift = cv2.SIFT_create(nfeatures=10000, contrastThreshold=.01)
    rk, rd = sift.detectAndCompute(gray, mask)
    if prepared_photo is None or prepared_photo.image is not image:
        prepared_photo = prepare_registration_photo(image, contrast_threshold=.01, **mask_kwargs(photo_mask))
    if rd is None or len(rk) < 40:
        raise IdentificationError('高程参考有效纹理不足，未采用结果。')
    pk, pd = prepared_photo.keypoints, prepared_photo.descriptors
    check_cancelled()
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    reverse = {p[0].queryIdx: p[0].trainIdx for p in matcher.knnMatch(pd, rd, k=2)
               if len(p) == 2 and p[0].distance < .85*p[1].distance}
    forward = matcher.knnMatch(rd, pd, k=2)
    good = [p[0] for p in forward if len(p) == 2 and p[0].distance < .85*p[1].distance
            and reverse.get(p[0].trainIdx) == p[0].queryIdx]
    if len(good) < 40:
        raise IdentificationError('高程参考有效纹理不足，未采用结果。')
    source = np.array([rk[m.queryIdx].pt for m in good])/scales
    target = np.array([pk[m.trainIdx].pt for m in good])/prepared_photo.scale
    keep = np.linalg.norm(source-target, axis=1) < max(12., project.identification['lens_distortion']['scale']*.03)
    if photo_mask is not None:
        keep &= photo_mask.allows(source, image.shape, padding=2) & photo_mask.allows(target, image.shape, padding=2)
    source, target = source[keep], target[keep]
    _, unique = np.unique(np.rint(np.column_stack((source, target))*4), axis=0, return_index=True)
    return source[unique], target[unique]


def _limb_data(image, result, params, center, scale, sign, photo_mask):
    h, w = image.shape[:2]
    factor = min(1., 1800/max(h, w))
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    if factor < 1:
        gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    bright = photo_mask.percentile(gray, 99) if photo_mask is not None else float(np.percentile(gray, 99))
    contours, _ = cv2.findContours((gray > max(30, bright*.25)).astype(np.uint8),
                                  cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = (photo_mask.largest_contour(contours, gray.shape) if photo_mask is not None
               else max(contours, key=cv2.contourArea)) if contours else None
    if contour is None:
        raise IdentificationError('目镜校正缺少可验证的受光月缘。')
    contour = contour.reshape(-1, 2).astype(np.float32)/factor
    if photo_mask is not None:
        contour = contour[photo_mask.allows(contour, image.shape, padding=2)]
    if len(contour) < 100:
        raise IdentificationError('目镜校正缺少可验证的受光月缘。')
    inverse = np.linalg.inv(np.vstack((result.matrix, [0., 0., 1.])))[:2]
    model = transform_points(inverse, undistort_points(contour, result.lens_distortion))
    radii = np.linalg.norm(model, axis=1)
    angle_index = np.floor((np.arctan2(model[:, 1], model[:, 0]) % (2*np.pi))*360/np.pi).astype(int)
    outer = (radii > .94) & (radii < 1.06)
    measured_train = contour[outer & ((angle_index//4) % 2 == 0)]
    measured_hold = contour[outer & ((angle_index//4) % 2 == 1)]
    if min(len(measured_train), len(measured_hold)) < 100:
        raise IdentificationError('目镜校正缺少可验证的受光月缘。')

    def make_nearest(measured):
        matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=1), dict(checks=64))
        def nearest(points):
            matches = matcher.knnMatch(np.float32(points), measured, k=1)
            return measured[[m[0].trainIdx for m in matches]]
        return nearest

    circle = np.column_stack((np.cos(np.arange(720)*np.pi/360), np.sin(np.arange(720)*np.pi/360)))
    geometry = result.projection_geometry
    lat, lon, _ = geometry.unproject(circle*.999)
    lit = surface_vectors(lat, lon) @ geometry.sun > .15
    pixels = _radial(params, circle*[sign, 1])*scale+center
    keep = lit & (pixels[:, 0] > 3) & (pixels[:, 0] < w-4) & (pixels[:, 1] > 3) & (pixels[:, 1] < h-4)
    if photo_mask is not None:
        keep &= photo_mask.allows(pixels, image.shape, padding=2)
    indices = np.flatnonzero(keep)
    train = circle[indices[(indices//4) % 2 == 0]]
    hold = circle[indices[(indices//4) % 2 == 1]]
    if min(len(train), len(hold)) < 100:
        raise IdentificationError('目镜校正的可验证月缘不足 120°。')
    return train, hold, make_nearest(measured_train), make_nearest(measured_hold), factor


def _fit(initial, coordinates, target, geometry, sign, scale, center, rim, nearest):
    params = initial.copy()
    eye = np.eye(len(params))*1e-5
    importance = np.r_[np.ones(len(target)), np.full(len(rim), .25)]
    damping = .001

    def predict(p):
        return np.vstack((_predict(p, coordinates, geometry, sign), _radial(p, rim*[sign, 1])))

    def targets(predicted):
        return np.vstack((target, (nearest(predicted[len(target):]*scale+center)-center)/scale))

    def loss(errors):
        return np.sum(importance*np.where(errors < 3, errors**2, 6*errors-9))

    for _ in range(80):
        check_cancelled()
        predicted = predict(params)
        observed = targets(predicted)
        residual = (predicted-observed).ravel()
        errors = np.linalg.norm(predicted-observed, axis=1)*scale
        weights = np.repeat(importance*np.minimum(1, 3/np.maximum(errors, 1e-8)), 2)
        jacobian = np.column_stack([((predict(params+row)-predicted)/1e-5).ravel() for row in eye])
        normal = jacobian.T @ (weights[:, None]*jacobian)
        delta = np.linalg.solve(normal+damping*np.diag(np.maximum(np.diag(normal), 1e-8)),
                                jacobian.T @ (weights*residual))
        trial = params-delta
        trial[4] = np.clip(trial[4], 0, .6)
        trial[5:7] = np.clip(trial[5:7], -.7, .7)
        trial[7:9] = np.clip(trial[7:9], -1.25, 1.25)
        trial[9] = np.clip(trial[9], -.3, .3)
        updated = predict(trial)
        if loss(np.linalg.norm(updated-targets(updated), axis=1)*scale) < loss(errors):
            params = trial
            damping = max(1e-8, damping/3)
            if np.linalg.norm(delta) < 1e-7:
                break
        else:
            damping *= 10
            if damping > 1e12:
                break
    return params


def _physical(params, sign):
    if not np.isfinite(params).all() or not .015 < params[4] < .55 or np.linalg.norm(params[7:9]) > 1.25:
        return False
    angles = np.arange(360)*np.pi/180
    circle = np.column_stack((np.cos(angles), np.sin(angles)))*[sign, 1]
    a, b, tx, ty, k, cx, cy = params[:7]
    ideal = circle @ np.array([[a, b], [-b, a]])+[tx-cx, ty-cy]
    squared = np.sum(ideal**2, axis=1)
    # A higher-order polynomial must never fold any part of the lunar field.
    return bool(np.min(1+3*k*squared+5*params[9]*squared**2) > .2)


def _refine(image, geometry, projection, match, result, dem, prepared_photo, photo_mask):
    from .map_layers import photo_coordinates
    from .project import Project
    project = Project(geometry=result.projection_geometry, matrix=result.matrix,
                      identification={'lens_distortion': result.lens_distortion})
    source, target = _terrain_pairs(image, project, dem, prepared_photo, photo_mask)
    if len(source) < 80:
        raise IdentificationError('目镜校正需要至少 100 个分散的纹理对应点。')
    lat, lon, visible = project.geometry.unproject(photo_coordinates(project, source))
    source = transform_points(projection, geometry.project(lat[visible], lon[visible])[0])
    target = target[visible]
    extra_count = len(source)
    original_source, original_target = match.source_matches, match.target_matches
    source = np.vstack((original_source, source))
    target = np.vstack((original_target, target))
    inverse = np.linalg.inv(np.vstack((projection, [0., 0., 1.])))[:2]
    lat, lon, visible = geometry.unproject(transform_points(inverse, source))
    _, unique = np.unique(np.rint(np.column_stack((source, target))*8), axis=0, return_index=True)
    indices = unique[visible[unique]]
    if len(indices) > 800:
        indices = indices[np.linspace(0, len(indices)-1, 800).astype(int)]
    coordinates = np.column_stack((lat, lon))[indices]
    target = target[indices]
    h, w = image.shape[:2]
    lens = result.lens_distortion
    scale, center = lens['scale'], np.array([w/2, h/2])
    if np.max(np.abs((np.asarray(lens['center'])-center)/scale)) > .5:
        center = np.asarray(lens['center'], float)
    sign = -1 if np.linalg.det(result.matrix[:, :2]) < 0 else 1
    initial = np.array([result.matrix[0, 0]/sign/scale, result.matrix[1, 0]/sign/scale,
                        *((result.matrix[:, 2]-center)/scale), lens['k'],
                        *((np.asarray(lens['center'])-center)/scale),
                        *result.refinement['view_offset_deg'], 0.])
    train, hold, nearest, validation_nearest, factor = _limb_data(image, result, initial, center, scale, sign, photo_mask)
    normalized = (target-center)/scale
    params = _fit(initial, coordinates, normalized, geometry, sign, scale, center, train, nearest)
    if not _physical(params, sign):
        raise IdentificationError('目镜校正参数未通过验证。')
    errors = np.linalg.norm(_predict(params, coordinates, geometry, sign)-normalized, axis=1)*scale
    inliers = errors < 3
    area = min(h*w, 4*scale**2)
    coverage = cv2.contourArea(cv2.convexHull(target[inliers].astype(np.float32)))/area
    if inliers.sum() < 100 or inliers.mean() < .8 or coverage < .08:
        raise IdentificationError('目镜校正的纹理验证不足。')
    effective = shifted_geometry(geometry, params[7:9])
    rim, limb_error, arc = _limb_check(image, effective, params, center, scale, sign,
                                     field_area=area, **mask_kwargs(photo_mask))
    held_rim = _radial(params, hold*[sign, 1])*scale+center
    held_error = np.linalg.norm(held_rim-validation_nearest(held_rim), axis=1)
    tolerance = max(4./factor, scale*.008)
    if np.percentile(held_error, 95) > tolerance or np.median(held_error) > tolerance*.7:
        raise IdentificationError('目镜校正仍与实际受光月缘不一致。')
    # Preserve the reliable old albedo anchors, including areas away from the pole.
    olat, olon, valid = geometry.unproject(transform_points(inverse, original_source))
    original_coordinates = np.column_stack((olat, olon))[valid]
    expected = original_target[valid]
    before = np.linalg.norm(_predict(initial, original_coordinates, geometry, sign)*scale+center-expected, axis=1)
    after = np.linalg.norm(_predict(params, original_coordinates, geometry, sign)*scale+center-expected, axis=1)
    reliable = before < 3
    if not reliable.any() or np.mean(after[reliable] < 4) < .95 or np.median(after[reliable]) > np.median(before[reliable])+1:
        raise IdentificationError('目镜校正的分区预测不稳定。')
    new = indices >= len(original_source)
    old_error = np.linalg.norm(_predict(initial, coordinates[new], geometry, sign)-normalized[new], axis=1)*scale
    new_error = errors[new]
    if len(new_error) < 80 or np.median(old_error)-np.median(new_error) < .75 or np.median(new_error) > .75*np.median(old_error):
        return result
    lower = target[inliers].min(0)
    span = np.maximum(np.ptp(target[inliers], axis=0), 1)
    grid = np.clip(((target-lower)/span*3).astype(int), 0, 2)
    cells = grid[:, 0]+3*grid[:, 1]
    folds = []
    predicted_rim = _radial(params, rim*[sign, 1])*scale
    for cell in np.unique(cells):
        check_cancelled()
        held = cells == cell
        if held.sum() < 10:
            continue
        other = _fit(initial, coordinates[~held], normalized[~held], geometry, sign, scale, center, train, nearest)
        check = np.linalg.norm(_predict(other, coordinates[held], geometry, sign)-normalized[held], axis=1)*scale
        rim_delta = np.linalg.norm(_radial(other, rim*[sign, 1])*scale-predicted_rim, axis=1)
        if not _physical(other, sign) or np.mean(check < 4) < .8 or np.percentile(rim_delta, 95) > max(3., scale*.006):
            raise IdentificationError('目镜校正的分区预测不稳定。')
        folds.append(dict(cell=int(cell), count=int(held.sum()), median_px=float(np.median(check)), within_4px=float(np.mean(check < 4))))
    if len(folds) < 4:
        raise IdentificationError('目镜校正缺少独立的验证区域。')
    a, b, tx, ty, k, cx, cy = params[:7]
    matrix = np.array([[a*sign, -b, tx], [b*sign, a, ty]])*scale
    matrix[:, 2] += center
    details = dict(result.refinement, view_offset_deg=params[7:9].tolist(), validation_folds=folds,
                   limb_p95_px=limb_error, limb_arc_deg=arc,
                   edge_refinement=dict(status='accepted', terrain_matches=extra_count,
                       median_before_px=float(np.median(old_error)), median_after_px=float(np.median(new_error)),
                       limb_training_points=len(train), limb_validation_points=len(hold),
                       heldout_limb_p95_px=float(np.percentile(held_error, 95))))
    return replace(result, matrix=matrix, projection_geometry=effective, refinement=details,
                   method=result.method+' / terrain-supported edge correction',
                   image_inliers=int(inliers.sum()), coverage=coverage, score=float(inliers.sum()),
                   rms_px=float(np.sqrt(np.mean(errors[inliers]**2))),
                   lens_distortion=dict(center=(center+scale*np.array([cx, cy])).tolist(),
                                        scale=float(scale), k=float(k), k2=float(params[9])))


def refine_eyepiece_edges(image, geometry, projection, match, result, cache, *, prepared_photo=None, photo_mask=None):
    if not needs_edge_refinement(result) or np.dot(geometry.observer, geometry.sun) > .98:
        return result
    try:
        check_cancelled()
        dem = ElevationMap.load(download_basic_dem(cache))
        try:
            return _refine(image, geometry, projection, match, result, dem, prepared_photo, photo_mask)
        finally:
            dem.close()
    except (ValueError, OSError, np.linalg.LinAlgError) as error:
        details = dict(result.refinement or {})
        details['edge_refinement'] = dict(status='unavailable' if isinstance(error, OSError) else 'not_adopted', reason=str(error))
        return replace(result, refinement=details)
