# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Local terrain search guided by independently confirmed reference points.

One point locates a region, not a camera pose. Two points can suggest a scale,
but cannot determine handedness. Image correspondences, their distribution,
dense terrain agreement and every supplied point must still validate a pose.
Only the existing small DEM is used; no extra map database is required.
"""
from itertools import combinations

from ._opencv import cv2
import numpy as np

from .geometry import MOON_RADIUS_KM
from .identification import IdentificationError, AmbiguousIdentificationError, IdentificationResult
from .registration import registration_candidates, transform_points
from .terrain import ElevationMap, download_basic_dem
from .terrain_identification import terrain_agreement, terrain_consensus, _pose_difference, _adopt_refinement
from .terrain_refinement import render_local_reference, refine_terrain_pose


def reference_point_errors(matrix, geometry, anchors, catalog):
    features = {f['id']: f for f in catalog}
    try:
        selected = [features[a['id']] for a in anchors]
        pixels = np.asarray([a['pixel'] for a in anchors], float)
    except (KeyError, TypeError, ValueError) as exc:
        raise IdentificationError('参考点的地名或坐标无效，请重新取点。') from exc
    if pixels.shape != (len(anchors), 2) or not np.isfinite(pixels).all():
        raise IdentificationError('参考点坐标无效，请重新取点。')
    points, visible, _ = geometry.project([f['lat'] for f in selected], [f['lon'] for f in selected])
    if not visible.all() or not np.isfinite(points).all():
        raise IdentificationError('参考点位于月球背面或不可投影，请核对拍摄日期和地名。')
    return np.linalg.norm(transform_points(matrix, points)-pixels, axis=1)


def reference_point_tolerance(image_shape, rms_px=0.):
    return max(15., min(image_shape[:2])*.012, rms_px*3)


def _field_widths(features, points, pixels, candidates, image_shape):
    """Bound scale trials; a detected radius is a prior, never a pose proof."""
    h, w = image_shape[:2]
    scales = []
    for i, j in combinations(range(len(points)), 2):
        separation = np.linalg.norm(points[i]-points[j])
        distance = np.linalg.norm(pixels[i]-pixels[j])
        if separation > 1e-6 and distance >= 12:
            scales.append(distance/separation)
    if not scales:
        for feature, pixel in zip(features, pixels):
            if feature['kind'] not in ('Crater, craters', 'Satellite Feature') or feature['diameter'] <= 0:
                continue
            nearby = [c for c in candidates if np.linalg.norm(np.array([c.x, c.y])-pixel) <= max(12., c.major*.6)]
            if nearby:
                candidate = min(nearby, key=lambda c: np.linalg.norm(np.array([c.x, c.y])-pixel))
                scales.append(candidate.major*2*MOON_RADIUS_KM/feature['diameter'])
    if scales:
        scale = np.median(scales)
        extent = max(h, w)*MOON_RADIUS_KM/scale
        widths = [extent*factor for factor in (.85, 1.1, 1.5)]
        # A point near a photo corner needs a wider field. Bound it by the
        # farthest corner, allowing any rotation without another global search.
        corners = np.array([[0, 0], [w, 0], [w, h], [0, h]])
        footprint = 2*np.linalg.norm(corners-pixels.mean(axis=0), axis=1).max()*MOON_RADIUS_KM/scale
        if footprint > widths[-1]:
            widths.append(footprint*1.05)
    else:
        # No radius or pair distance is available; search a few local fields
        # rather than rendering the entire visible Moon at higher resolution.
        widths = [160., 320., 80., 640.]
    return list(dict.fromkeys(float(np.clip(round(width/10)*10, 40, 4200)) for width in widths))


def _finish_guided_search(solutions, pending, image, geometry, dem, anchors, catalog):
    """Certify at most two distinct coarse poses, keeping every click as a check."""
    limit = max(image.shape[:2])*.08
    best = max(solutions, key=lambda result: result.score) if solutions else None
    distinct = []
    for candidate in sorted(pending, key=lambda result: -result.score):
        if best is not None and (candidate.score <= best.score*.8 or
                _pose_difference(best.matrix, candidate.matrix, image.shape) <= limit):
            continue
        if all(_pose_difference(other.matrix, candidate.matrix, image.shape) > limit for other in distinct):
            distinct.append(candidate)
    for candidate in distinct[:2]:
        refined = refine_terrain_pose(image, geometry, candidate.matrix, dem, relief_aware=True)
        if refined is None:
            continue
        light, detail = (refined.details['light_before_after'][1], refined.details['detail_before_after'][1])
        if light < .6 or detail < .25 or not terrain_consensus(light, detail, refined.details['points'], refined.details['coverage']):
            continue
        errors = reference_point_errors(refined.matrix, refined.geometry, anchors, catalog)
        if (errors > reference_point_tolerance(image.shape, refined.rms_px)).any():
            continue
        _adopt_refinement(candidate, refined)
        candidate.method += ' / relief-aware refinement'
        candidate.reference_points['reference_errors_px'] = errors.tolist()
        solutions.append(candidate)
    if not solutions:
        return None
    result = max(solutions, key=lambda candidate: candidate.score)
    for other in solutions:
        if other is not result and other.score > result.score*.8 and _pose_difference(result.matrix, other.matrix, image.shape) > limit:
            raise AmbiguousIdentificationError('参考点附近有多个接近的匹配，请再确认一处地形。')
    return result


def identify_from_reference_points(image, geometry, cache, anchors, catalog, candidates=(), *,
                                   reference_size=600, refine=True):
    """Use manual points first; accept only an independently verified local pose."""
    catalog = list(catalog)
    anchors = [a for a in anchors if a.get('enabled', True) and a.get('source') != 'automatic']
    if not anchors:
        raise IdentificationError('请先确认至少一个已知地形参考点。')
    # Validate input coordinates and visibility before DEM loading/rendering.
    reference_point_errors(np.array([[1., 0., 0.], [0., 1., 0.]]), geometry, anchors, catalog)
    by_id = {f['id']: f for f in catalog}
    features = [by_id[a['id']] for a in anchors]
    pixels = np.asarray([a['pixel'] for a in anchors], float)
    h, w = image.shape[:2]
    if (pixels < 0).any() or (pixels >= [w, h]).any():
        raise IdentificationError('参考点不在照片范围内，请重新取点。')
    points, _, _ = geometry.project([f['lat'] for f in features], [f['lon'] for f in features])
    center = points.mean(axis=0)
    widths = _field_widths(features, points, pixels, candidates, image.shape)
    # Keep retrieval resolution close to the photograph's working resolution.
    # A 1400-pixel reference oversamples the small DEM and loses mutual SIFT
    # matches to real small-crater detail; dense acceptance gates stay unchanged.
    factor = min(1., 880/max(h, w))
    photograph = cv2.resize(image, (round(w*factor), round(h*factor)), interpolation=cv2.INTER_AREA)
    sx, sy = photograph.shape[1]/w, photograph.shape[0]/h
    cv2.setRNGSeed(0)
    dem = ElevationMap.load(download_basic_dem(cache))
    pending = []
    try:
        for width in widths:
            scale = reference_size*MOON_RADIUS_KM/width
            projection = np.column_stack((np.eye(2)*scale, np.full(2, reference_size/2)-center*scale))
            reference = render_local_reference(dem, geometry, projection, (reference_size, reference_size))
            try:
                matches = registration_candidates(reference, photograph, ratio_threshold=.8,
                                                  contrast_threshold=.01, min_inlier_fraction=.25)
            except ValueError:
                continue
            solutions = []
            for match in matches:
                if match.inliers < 24 or match.coverage < .1:
                    continue
                matrix = (np.vstack((match.matrix, [0., 0., 1.])) @ np.vstack((projection, [0., 0., 1.])))[:2]
                matrix = np.diag([1/sx, 1/sy])@matrix
                rms = match.rms_px/min(sx, sy)
                errors = reference_point_errors(matrix, geometry, anchors, catalog)
                if (errors > reference_point_tolerance(image.shape, rms)).any():
                    continue
                try:
                    light, detail = terrain_agreement(reference, photograph, match.matrix, require_match=False)
                except IdentificationError:
                    continue
                # A small matching patch must not certify a mostly uncovered
                # photograph. Check the usable central field independently.
                ph, pw = photograph.shape[:2]
                available = cv2.warpAffine(np.full(reference.shape, 255, np.uint8), match.matrix, (pw, ph))
                if (available[round(ph*.08):round(ph*.93), round(pw*.05):round(pw*.95)] > 250).mean() < .85:
                    continue
                result = IdentificationResult(matrix, [], rms, float(match.inliers*(light+detail)), 0,
                                              'LOLA slope + cast-shadow / reference-point guided SIFT / JPL projection',
                                              match.inliers, match.coverage, 0, light)
                result.reference_points = {'reference_ids': [a['id'] for a in anchors],
                                           'reference_errors_px': errors.tolist(), 'search_width_km': width}
                if terrain_consensus(light, detail, match.inliers, match.coverage):
                    solutions.append(result)
                elif refine and match.inliers >= 40 and match.coverage >= .18 and light >= .4 and detail >= .25:
                    pending.append(result)
            if not solutions:
                continue
            result = _finish_guided_search(solutions, pending, image, geometry, dem, anchors, catalog)
            # Refinement needs forty correspondences itself. Avoid another
            # render when the accepted retrieval has less supporting evidence.
            if refine and result.image_inliers >= 40 and result.refinement is None:
                refined = refine_terrain_pose(image, geometry, result.matrix, dem)
                if refined is not None:
                    updated_errors = reference_point_errors(refined.matrix, refined.geometry, anchors, catalog)
                    if (updated_errors <= reference_point_tolerance(image.shape, refined.rms_px)).all():
                        _adopt_refinement(result, refined)
                        result.reference_points['reference_errors_px'] = updated_errors.tolist()
            return result
        result = _finish_guided_search([], pending, image, geometry, dem, anchors, catalog)
        if result is not None:
            return result
    finally:
        dem.close()
    raise IdentificationError('参考点附近未找到通过纹理、分布和取点位置验证的匹配。请核对地名和坑中心，或再确认一处地形；已保留参考点。')
