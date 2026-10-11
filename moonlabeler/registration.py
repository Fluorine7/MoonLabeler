# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Manual similarity fitting and conservative local feature matching."""
from dataclasses import dataclass

import cv2
import numpy as np


def transform_points(matrix, points):
    points = np.asarray(points, dtype=float)
    return points @ np.asarray(matrix)[:, :2].T + np.asarray(matrix)[:, 2]


def fit_similarity(source, target, mirror="auto"):
    source, target = np.asarray(source, float), np.asarray(target, float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 2:
        raise ValueError("参考点格式不正确。")
    if len(source) < 2 or not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("至少需要两个有效的参考点。")
    centered = source - source.mean(axis=0)
    if np.sum(centered ** 2) < 1e-10 or np.max(np.linalg.norm(target-target.mean(0), axis=1)) < 1:
        raise ValueError("参考点太接近，请选择分布更广的地形。")
    if len(source) >= 3 and np.linalg.svd(centered, compute_uv=False)[1] < 0.01 * np.linalg.svd(centered, compute_uv=False)[0]:
        raise ValueError("参考点接近一条直线，请加入不共线的地形点。")
    # With two points handedness is unidentifiable: require explicit mirror,
    # defaulting to non-mirrored rather than claiming it has been determined.
    signs = [-1] if mirror == "yes" else [1]
    if mirror == "auto" and len(source) >= 3:
        signs = [1, -1]
    candidates = []
    for sign in signs:
        reflected = source * [sign, 1]
        x, y = reflected.T
        design = np.zeros((len(x) * 2, 4))
        design[0::2] = np.column_stack((x, -y, np.ones(len(x)), np.zeros(len(x))))
        design[1::2] = np.column_stack((y, x, np.zeros(len(x)), np.ones(len(x))))
        a, b, tx, ty = np.linalg.lstsq(design, target.ravel(), rcond=None)[0]
        matrix = np.array([[a * sign, -b, tx], [b * sign, a, ty]])
        rms = float(np.sqrt(np.mean(np.sum((transform_points(matrix, source) - target)**2, axis=1))))
        candidates.append((rms, matrix))
    rms, matrix = min(candidates, key=lambda pair: pair[0])
    return matrix, rms


@dataclass
class CalibrationReport:
    matrix: np.ndarray
    rms_px: float
    residuals_px: np.ndarray
    check_errors_px: np.ndarray
    suspect_index: int | None


def calibration_report(source, target, mirror="auto"):
    """Fit every enabled anchor. Suggest review, never silently discard a point.

    Leave-one-out errors are independent of the held-out click but still depend
    on the same spherical model. They do not measure absolute map accuracy.
    """
    source, target = np.asarray(source, float), np.asarray(target, float)
    matrix, rms = fit_similarity(source, target, mirror)
    residuals = np.linalg.norm(transform_points(matrix, source)-target, axis=1)
    checks = np.full(len(source), np.nan)
    alternatives = []
    if len(source) >= 4:
        for index in range(len(source)):
            keep = np.arange(len(source)) != index
            try:
                other, other_rms = fit_similarity(source[keep], target[keep], mirror)
            except ValueError:
                continue
            checks[index] = np.linalg.norm(transform_points(other, source[index:index+1])[0]-target[index])
            alternatives.append((other_rms, index))
    suspect = None
    # Four points cannot reliably identify which one is incorrect. With five
    # or more, flag only a large, uniquely explained improvement.
    if len(source) >= 5 and alternatives and rms > 2:
        alternatives.sort()
        best_rms, index = alternatives[0]
        second_rms = alternatives[1][0] if len(alternatives) > 1 else float("inf")
        if best_rms < 0.3*rms and second_rms > max(1., 2*best_rms) and checks[index] > max(5., 4*best_rms):
            suspect = index
    return CalibrationReport(matrix, rms, residuals, checks, suspect)


def _gray(image, maximum=2200):
    image = np.asarray(image)
    gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    scale = min(1., maximum / max(gray.shape))
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(gray.astype(np.uint8))
    return gray, scale


@dataclass
class MatchResult:
    matrix: np.ndarray
    inliers: int
    matches: int
    rms_px: float
    coverage: float
    mirrored: bool
    # RANSAC inliers in the original, unreflected images' pixel coordinates.
    source_points: np.ndarray | None = None
    target_points: np.ndarray | None = None


def registration_candidates(reference, photograph, *, ratio_threshold=.75,
                            contrast_threshold=.02, min_inlier_fraction=.35):
    """Map reference pixels to photograph pixels. No assumed crop/rotation.

    Reflections are tested explicitly. RANSAC uses a similarity rather than an
    arbitrary homography that could bend a wrong match into apparent agreement.
    """
    ref, rs = _gray(reference)
    photo, ps = _gray(photograph)
    sift = cv2.SIFT_create(nfeatures=10000, contrastThreshold=contrast_threshold)
    pk, pd = sift.detectAndCompute(photo, None)
    if pd is None or len(pk) < 12:
        raise ValueError("照片细节不足，自动配准失败。请使用手动地形参考点。")
    candidates = []
    for mirrored in (False, True):
        current = cv2.flip(ref, 1) if mirrored else ref
        rk, rd = sift.detectAndCompute(current, None)
        if rd is None:
            continue
        matcher = cv2.BFMatcher(cv2.NORM_L2)
        forward = matcher.knnMatch(rd, pd, k=2)
        reverse = matcher.knnMatch(pd, rd, k=2)
        backwards = {pair[0].queryIdx: pair[0].trainIdx for pair in reverse
                     if len(pair) == 2 and pair[0].distance < ratio_threshold * pair[1].distance}
        good = [p[0] for p in forward if len(p) == 2 and
                p[0].distance < ratio_threshold * p[1].distance and
                backwards.get(p[0].trainIdx) == p[0].queryIdx]
        if len(good) < 12:
            continue
        src = np.float32([rk[m.queryIdx].pt for m in good])
        dst = np.float32([pk[m.trainIdx].pt for m in good])
        matrix, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                  ransacReprojThreshold=3.,
                                                  maxIters=10000, confidence=0.999)
        if matrix is None or mask is None:
            continue
        inliers = mask.ravel().astype(bool)
        count = int(inliers.sum())
        if count < 12 or count / len(good) < min_inlier_fraction:
            continue
        hull = cv2.convexHull(dst[inliers])
        coverage = cv2.contourArea(hull) / (photo.shape[0] * photo.shape[1])
        if coverage < 0.015:
            continue
        error = np.linalg.norm(transform_points(matrix, src[inliers]) - dst[inliers], axis=1)
        rms = float(np.sqrt(np.mean(error ** 2)) / ps)
        if rms > 4 / ps:
            continue
        source_points = src[inliers].astype(float)
        target_points = dst[inliers].astype(float) / ps
        if mirrored:
            reflection = np.array([[-1., 0., ref.shape[1]-1], [0., 1., 0.], [0., 0., 1.]])
            matrix = (np.vstack((matrix, [0., 0., 1.])) @ reflection)[:2]
            source_points[:, 0] = ref.shape[1]-1-source_points[:, 0]
        source_points /= rs
        matrix[:, :2] *= rs / ps
        matrix[:, 2] /= ps
        candidates.append(MatchResult(matrix, count, len(good), rms, coverage, mirrored,
                                      source_points, target_points))
    if not candidates:
        raise ValueError("没有足够可靠的匹配。请核对拍摄时间，或用至少三处已知地形手动配准。")
    return candidates


def auto_register(reference, photograph, *, ratio_threshold=.75,
                  contrast_threshold=.02, min_inlier_fraction=.35):
    """Return the strongest image pose, testing both camera handednesses."""
    candidates = registration_candidates(reference, photograph,
                                         ratio_threshold=ratio_threshold,
                                         contrast_threshold=contrast_threshold,
                                         min_inlier_fraction=min_inlier_fraction)
    return max(candidates, key=lambda candidate: (candidate.inliers, candidate.coverage))
