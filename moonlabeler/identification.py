# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Identify image crater patterns against the projected IAU name catalogue.

This is an Earth-view similarity pattern search, not an implementation of the
general perspective-conic invariants in Christian et al. (2020).
Seed triangles propose a pose; other crater observations must verify it.
"""
from dataclasses import dataclass
import math

import cv2
import numpy as np

from .geometry import MOON_RADIUS_KM, Geometry
from .registration import fit_similarity, transform_points


class IdentificationError(ValueError):
    pass


class AmbiguousIdentificationError(IdentificationError):
    pass


@dataclass
class IdentifiedCrater:
    candidate_index: int
    feature: dict
    error_px: float


@dataclass
class IdentificationResult:
    matrix: np.ndarray
    matches: list[IdentifiedCrater]
    rms_px: float
    score: float
    alternatives: int
    method: str = "EDCircles / catalogue triangles / JPL projection"
    image_inliers: int = 0
    coverage: float = 0.
    limb_inliers: int = 0
    texture_correlation: float = 0.
    projection_geometry: Geometry | None = None
    refinement: dict | None = None
    crater_rims: dict | None = None
    reference_points: dict | None = None


def _triangle_index(points, radii, neighbors=14, centered=False):
    """Canonical vertices are ordered by opposite side length; mirrors survive."""
    points = np.asarray(points, np.float32)
    if len(points) < 3:
        return np.empty((0, 5), np.float32), np.empty((0, 3), int)
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=2), dict(checks=32))
    near = matcher.knnMatch(points, points, k=min(neighbors+1, len(points)))
    rows = []
    pair_indices = {}
    for i, choices in enumerate(near):
        indices = np.asarray([choice.trainIdx for choice in choices if choice.trainIdx != i], dtype=np.int32)
        count = len(indices)
        if count not in pair_indices:
            pair_indices[count] = np.triu_indices(count, 1)
        left, right = pair_indices[count]
        triples = np.column_stack((np.full(len(left), i, dtype=np.int32), indices[left], indices[right]))
        triples.sort(axis=1)
        rows.append(triples)
    # np.unique(axis=0) uses costly structured-row comparisons. Integer
    # column sorting preserves the same lexicographic order,
    # including hypothesis tie-breaking, without that cost.
    triangles = np.concatenate(rows)
    if not len(triangles):
        return np.empty((0, 5), np.float32), np.empty((0, 3), np.int32)
    triangles = triangles[np.lexsort(triangles.T[::-1])]
    distinct = np.r_[True, np.any(triangles[1:] != triangles[:-1], axis=1)]
    triangles = triangles[distinct]
    p = points[triangles]
    sides = np.stack((np.linalg.norm(p[:, 1]-p[:, 2], axis=1),
                      np.linalg.norm(p[:, 0]-p[:, 2], axis=1),
                      np.linalg.norm(p[:, 0]-p[:, 1], axis=1)), axis=1)
    order = np.argsort(sides, axis=1)
    sides = np.take_along_axis(sides, order, axis=1)
    triangles = np.take_along_axis(triangles, order, axis=1)
    area = np.abs((p[:, 1, 0]-p[:, 0, 0])*(p[:, 2, 1]-p[:, 0, 1])-
                  (p[:, 1, 1]-p[:, 0, 1])*(p[:, 2, 0]-p[:, 0, 0]))
    valid = (sides[:, 0] > 0) & (area > .12*sides[:, 2]**2) & (sides[:, 0] > .18*sides[:, 2])
    # Nearly equal edges make canonical vertex assignment unstable in noisy rims.
    valid &= (np.diff(sides, axis=1).min(axis=1) > .025*sides[:, 2])
    triangles, sides = triangles[valid], sides[valid]
    descriptors = np.column_stack((sides[:, :2]/sides[:, 2:],
                                   .14*np.log(np.maximum(np.asarray(radii)[triangles]/sides[:, 2:], 1e-6))))
    if centered:
        # Shadow/floor fits can underestimate all radii in a group. Retrieve
        # by relative radii here; absolute radius agreement is still verified
        # against the fitted pose below.
        descriptors[:, 2:] -= descriptors[:, 2:].mean(axis=1, keepdims=True)
    return np.ascontiguousarray(descriptors, np.float32), triangles


def identify_from_candidates(candidates, catalog, geometry, image_shape, max_hypotheses=2400, image=None):
    """Try the compact named-crater index, then search satellite crater patterns.

    The broader search requires seven correspondences among the twenty largest
    observations. Small texture fragments must not dilute or create consensus.
    Distributed coverage, lunar foreground and competing poses are checked in
    both passes. No region, scale, rotation or handedness is supplied.
    """
    candidates = list(candidates)
    try:
        return _search_candidates(candidates, catalog, geometry, image_shape, max_hypotheses, image)
    except AmbiguousIdentificationError:
        raise
    except IdentificationError:
        if len(candidates) < 7:
            raise
    return _search_candidates(candidates, catalog, geometry, image_shape, 50000, image, expanded=True)


def _search_candidates(candidates, catalog, geometry, image_shape, max_hypotheses, image, expanded=False):
    # FLANN's trees must not depend on which photograph was processed earlier.
    cv2.setRNGSeed(0)
    candidates = list(candidates)
    minimum_matches = 7 if expanded else max(7, math.ceil(len(candidates)*.35))
    if len(candidates) < 7:
        raise IdentificationError("可用坑缘不足七处，无法独立验证自动识别。")
    photo = np.array([[c.x, c.y] for c in candidates], np.float32)
    observed_radius = np.array([c.major for c in candidates])
    all_features = [f for f in catalog if f["kind"] in ("Crater, craters", "Satellite Feature") and 3 <= f["diameter"] <= 250]
    points, visible, _ = geometry.project([f["lat"] for f in all_features], [f["lon"] for f in all_features])
    usable = visible & (np.linalg.norm(points, axis=1) < .98)
    features = [f for f, valid in zip(all_features, usable) if valid]
    points = points[usable]
    radii = np.array([f["diameter"]/(2*MOON_RADIUS_KM) for f in features])
    if expanded:
        descriptors, triangles = [], []
        # Sparse cohorts retain large-crater relationships that would otherwise
        # be crowded out by many small neighboring satellite craters.
        for minimum in (5, 10, 20, 40, 80):
            indices = np.array([i for i, f in enumerate(features) if f["diameter"] >= minimum], int)
            desc, tri = _triangle_index(points[indices], radii[indices], 24, centered=True)
            descriptors.append(desc)
            triangles.append(indices[tri])
        reference_desc, reference_triangles = np.concatenate(descriptors), np.concatenate(triangles)
        photo_seed_indices = np.argsort(-observed_radius)[:20]
        photo_desc, photo_triangles = _triangle_index(photo[photo_seed_indices], observed_radius[photo_seed_indices], 19, centered=True)
        photo_triangles = photo_seed_indices[photo_triangles]
        core = set(photo_seed_indices.tolist())
    else:
        seed_indices = np.array([i for i, f in enumerate(features) if f["kind"] == "Crater, craters" and f["diameter"] >= 5], int)
        reference_desc, reference_triangles = _triangle_index(points[seed_indices], radii[seed_indices], 16)
        reference_triangles = seed_indices[reference_triangles]
        photo_desc, photo_triangles = _triangle_index(photo, observed_radius, 12)
    if min(len(reference_desc), len(photo_desc)) < 1:
        raise IdentificationError("没有足够分散的环形山图案，自动识别未通过。")
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=512 if expanded else 64))
    nearest = matcher.knnMatch(photo_desc, reference_desc, k=min(128 if expanded else 8, len(reference_desc)))
    proposals = sorted((match for group in nearest for match in group if match.distance < .095), key=lambda m: m.distance)[:max_hypotheses]
    h, w = image_shape[:2]
    foreground = None
    if image is not None:
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY) if np.asarray(image).ndim == 3 else np.asarray(image)
        sample = cv2.resize(gray[:round(h*.93)], (40, 36), interpolation=cv2.INTER_AREA)
        yy, xx = np.nonzero(sample > 30)
        foreground = np.column_stack(((xx+.5)*w/40, (yy+.5)*round(h*.93)/36))
    image_matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=2), dict(checks=48))
    image_matcher.add([photo])
    image_matcher.train()

    def verify(matrix):
        if foreground is not None and len(foreground):
            inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
            on_disk = np.linalg.norm(transform_points(inverse, foreground), axis=1) < 1.01
            if on_disk.mean() < .9:
                return [], 0.
        predicted = transform_points(matrix, points)
        scale = math.sqrt(abs(np.linalg.det(matrix[:, :2])))
        size = radii*scale
        inside = (predicted[:, 0] >= 0) & (predicted[:, 0] < w) & (predicted[:, 1] >= 0) & (predicted[:, 1] < h)
        inside &= (size >= observed_radius.min()*.55) & (size <= observed_radius.max()*1.6)
        ii = np.flatnonzero(inside)
        if len(ii) < minimum_matches:
            return [], 0.
        neighbors = image_matcher.knnMatch(np.ascontiguousarray(predicted[ii], np.float32), k=min(4, len(photo)))
        choices = []
        for source, group in zip(ii, neighbors):
            for neighbor in group:
                target = neighbor.trainIdx
                ratio = observed_radius[target]/size[source]
                threshold = max(8., min(25., observed_radius[target]*.25))
                if .5 < ratio < 1.9 and neighbor.distance < threshold:
                    quality = neighbor.distance/threshold+.25*abs(math.log(ratio))
                    choices.append((quality, source, target, neighbor.distance))
        used_source, used_target, pairs = set(), set(), []
        for quality, source, target, error in sorted(choices):
            if source not in used_source and target not in used_target:
                pairs.append((source, target, error))
                used_source.add(source)
                used_target.add(target)
        if len(pairs) < minimum_matches:
            return pairs, 0.
        named = sum(features[source]["kind"] == "Crater, craters" for source, _, _ in pairs)
        occupied = photo[[target for _, target, _ in pairs]]
        coverage = cv2.contourArea(cv2.convexHull(occupied.astype(np.float32)))/(w*h)
        consensus = sum(target in core for _, target, _ in pairs) >= minimum_matches if expanded else named >= 4
        if not consensus or coverage < .06:
            return pairs, 0.
        score = sum(math.sqrt(observed_radius[target])*(1. if expanded else (1.25 if features[source]["kind"] == "Crater, craters" else .8))
                    *(1.-.5*min(1., error/max(8., min(25., observed_radius[target]*.25)))) for source, target, error in pairs)
        return pairs, score

    solutions, tried = [], set()
    for proposal in proposals:
        source = reference_triangles[proposal.trainIdx]
        target = photo_triangles[proposal.queryIdx]
        try:
            matrix, rms = fit_similarity(points[source], photo[target])
        except ValueError:
            continue
        if rms > max(4., observed_radius[target].mean()*.15):
            continue
        scale = math.sqrt(abs(np.linalg.det(matrix[:, :2])))
        if not 100 < scale < 1e6:
            continue
        key = tuple(np.rint(matrix[:, :2].ravel()/max(1., scale*.025)).astype(int)) + tuple(np.rint(matrix[:, 2]/25).astype(int)) + (round(math.log(scale)*40),)
        if key in tried:
            continue
        tried.add(key)
        pairs, score = verify(matrix)
        if score > 0:
            solutions.append((score, matrix, pairs))
    if not solutions:
        raise IdentificationError("未找到通过多坑验证的月面区域。强阴影或候选中心偏差可能导致识别失败；没有采用猜测地名。")
    solutions.sort(key=lambda solution: -solution[0])
    score, matrix, pairs = solutions[0]
    # Refine using correspondences beyond the seed, then re-evaluate all points.
    for _ in range(2):
        source = [p[0] for p in pairs]
        target = [p[1] for p in pairs]
        refined, _ = fit_similarity(points[source], photo[target])
        updated_pairs, updated_score = verify(refined)
        if updated_score < .9*score:
            break
        matrix, pairs, score = refined, updated_pairs, updated_score
    competitors = []
    center = np.array([[w/2, h/2], [w*.75, h/2], [w/2, h*.75]])
    # Compare poses in image space; repeated seed triangles in the same region
    # are supporting evidence, rather than independent alternative regions.
    inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
    source_center = transform_points(inverse, center)
    for other_score, other_matrix, _ in solutions[1:]:
        difference = np.linalg.norm(transform_points(other_matrix, source_center)-center, axis=1).mean()
        if difference > max(w, h)*.08:
            competitors.append(other_score)
    if competitors and max(competitors) > score*.8:
        raise AmbiguousIdentificationError("出现多个接近的月面匹配，无法可靠区分；自动识别未采用结果。")
    matches = [IdentifiedCrater(target, features[source], float(error)) for source, target, error in pairs]
    rms = float(np.sqrt(np.mean([match.error_px**2 for match in matches])))
    method = "EDCircles / multiscale named + satellite triangles / JPL projection" if expanded else "EDCircles / catalogue triangles / JPL projection"
    occupied = photo[[match.candidate_index for match in matches]]
    coverage = cv2.contourArea(cv2.convexHull(occupied.astype(np.float32)))/(w*h)
    return IdentificationResult(matrix, matches, rms, float(score), len(competitors), method, 0, coverage)
