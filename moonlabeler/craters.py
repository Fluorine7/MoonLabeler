# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Local, unlabelled crater candidates; no ephemeris or name recognition.

OpenCV preprocessing and ellipse fitting adapted from Ram Maruboina's
lunar-crater-detector (MIT), commit 0babc2a6fb3d02cfbf58aa9bafe9f44edf8dc3dd.
See THIRD_PARTY_NOTICES.md. Fixed pixel cutoffs and the slow optional skimage
Hough ellipse pass are replaced by configurable radii and edge support checks.
"""
from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class DetectionOptions:
    min_radius: float = 8.
    max_radius: float = 180.
    sensitivity: int = 50
    max_candidates: int = 80
    max_dimension: int = 1600
    prefer_large: bool = False


@dataclass(frozen=True)
class CraterCandidate:
    x: float
    y: float
    major: float
    minor: float
    angle: float
    support: float | None
    method: str


@dataclass
class DetectionResult:
    candidates: list[CraterCandidate]
    region: tuple[int, int, int, int]
    scale: float


def _map_candidate(candidate, sx, sy, x=0, y=0):
    """Map a fitted conic through the actual (possibly rounded) resize."""
    theta = math.radians(candidate.angle)
    basis = np.array([[math.cos(theta), -math.sin(theta)],
                      [math.sin(theta), math.cos(theta)]]) @ np.diag([candidate.major, candidate.minor])
    axes, lengths, _ = np.linalg.svd(np.diag([1/sx, 1/sy]) @ basis)
    return CraterCandidate(candidate.x/sx+x, candidate.y/sy+y,
                           float(lengths[0]), float(lengths[1]),
                           math.degrees(math.atan2(axes[1, 0], axes[0, 0])) % 180,
                           candidate.support, candidate.method)


def _large_rim_candidates(gray):
    """Low-frequency arc proposals for craters dominating a close-up.

    High-pass enhancement fragments terraced rims. Fit long smoothed arcs,
    then check the *whole* ellipse against independently sampled edge normals
    in at least six octants. This is only a centre proposal, not a named feature
    or an accurate physical rim. Work is bounded by a 600-pixel image.
    """
    h, w = gray.shape
    factor = min(1., 600/max(h, w))
    sample = cv2.resize(gray, (round(w*factor), round(h*factor)), interpolation=cv2.INTER_AREA) if factor < 1 else gray
    sh, sw = sample.shape
    if min(sh, sw) < 32:
        return []
    sy, sx = sh/h, sw/w
    t = np.linspace(0, 2*np.pi, 144, endpoint=False)
    proposals = []
    for sigma in (1.3, 2.):
        smooth = cv2.GaussianBlur(sample, (0, 0), sigma)
        edges = cv2.Canny(smooth, 10, 25)
        ey, ex = np.nonzero(edges)
        if not len(ex):
            continue
        distance, labels = cv2.distanceTransformWithLabels(255-edges, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
        gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1)
        normals = np.column_stack((gx[ey, ex], gy[ey, ex]))
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-6)
        gradient = np.zeros((int(labels.max())+1, 2), np.float32)
        gradient[labels[ey, ex]] = normals
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        arcs = []
        for contour in sorted(contours, key=len, reverse=True)[:32]:
            arcs.append(contour)
            # Connected terrace/shadow edges can branch into unrelated terrain.
            # Bounded overlapping arc windows avoid fitting the entire branch.
            for length in (80, 160, 320):
                if len(contour) >= length*1.5:
                    for start in range(0, len(contour)-length+1, length//2):
                        arcs.append(contour[start:start+length])
        for contour in arcs:
            if len(contour) < max(60, min(sh, sw)*.2):
                continue
            (cx, cy), (da, db), angle = cv2.fitEllipse(contour)
            a, b = da/2, db/2
            radius = (a+b)/2
            if (not np.isfinite([cx, cy, a, b, angle]).all() or
                    min(a, b) <= 0 or min(a, b)/max(a, b) < .35 or
                    radius < min(sh, sw)*.2 or max(a, b) > max(sh, sw)*.5):
                continue
            theta = math.radians(angle)
            ct, st = math.cos(theta), math.sin(theta)
            hw, hh = math.hypot(a*ct, b*st), math.hypot(a*st, b*ct)
            if cx-hw < 2 or cy-hh < 2 or cx+hw >= sw-2 or cy+hh >= sh-2:
                continue
            delta = contour[:, 0, :]-[cx, cy]
            u, v = delta[:, 0]*ct+delta[:, 1]*st, -delta[:, 0]*st+delta[:, 1]*ct
            if np.quantile(np.abs(np.hypot(u/a, v/b)-1), .8) > .06:
                continue
            # At least a quarter arc nominates a conic; the full-rim check
            # below must independently support the remaining directions.
            phase = np.mod(np.arctan2(v/b, u/a), 2*np.pi)
            if len(np.unique((phase/(2*np.pi)*24).astype(int))) < 6:
                continue
            xx = np.rint(cx+a*np.cos(t)*ct-b*np.sin(t)*st).astype(int)
            yy = np.rint(cy+a*np.cos(t)*st+b*np.sin(t)*ct).astype(int)
            ox = np.rint(cx+1.1*(xx-cx)).astype(int)
            oy = np.rint(cy+1.1*(yy-cy)).astype(int)
            outside = (ox >= 0) & (oy >= 0) & (ox < sw) & (oy < sh)
            if outside.sum() >= 72 and np.mean(sample[oy[outside], ox[outside]] < 15) > .7:
                # The Moon/black-sky boundary is not a crater rim.
                continue
            radial = np.column_stack((np.cos(t)/a*ct-np.sin(t)/b*st,
                                      np.cos(t)/a*st+np.sin(t)/b*ct))
            radial /= np.linalg.norm(radial, axis=1, keepdims=True)
            aligned = np.abs(np.sum(gradient[labels[yy, xx]]*radial, axis=1)) > .75
            supported = (distance[yy, xx] <= 2.5) & aligned
            support = float(supported.mean())
            if support < .6 or np.count_nonzero(supported.reshape(8, -1).mean(axis=1) >= .4) < 6:
                continue
            candidate = CraterCandidate(cx, cy, a, b, angle, support, 'coarse-ellipse')
            proposals.append(_map_candidate(candidate, sx, sy))
    return sorted(proposals, key=lambda c: -c.support)


def detect_crater_rims(image):
    """Group partial rim arcs with OpenCV EDCircles at several resolutions.

    Unlike closed shadow contours, separate illuminated arcs can contribute to
    one ellipse. NFA validation checks the arc fit, not the crater's identity.
    Coordinates and semiaxes always refer to the original image. No names,
    lunar region, ephemeris, training weights or network are used here.
    """
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[2] != 3):
        raise ValueError("检测需要 8 位灰度或 RGB 图像。")
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    h, w = gray.shape
    if min(h, w) < 64 or float(np.std(gray)) < 1:
        return DetectionResult([], (0, 0, w, h), 1.)
    proposals = []
    # Exclude a detached, very dark caption strip if a sharp full-width seam
    # starts it near the bottom. Letter loops must not become crater evidence.
    bottom = h
    passes = set()
    dark_fraction = np.mean(gray < 15, axis=1)
    for row in range(int(h*.9), h-2):
        if dark_fraction[row:row+3].min() > .9 and dark_fraction[row-3:row].max() < .3:
            bottom = row
            break
    for dimension, sigma, threshold in ((1600, 1., 20), (1600, 2., 12),
                                         (1000, 1., 15), (2400, 1., 20)):
        factor = min(1., dimension/max(h, w))
        key = (factor, sigma, threshold)
        if key in passes:
            continue
        passes.add(key)
        sample = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA) if factor < 1 else gray
        sy, sx = sample.shape[0]/h, sample.shape[1]/w
        detector = cv2.ximgproc.createEdgeDrawing()
        params = cv2.ximgproc_EdgeDrawing_Params()
        params.MinPathLength = 20
        params.Sigma = sigma
        params.GradientThresholdValue = threshold
        params.NFAValidation = True
        detector.setParams(params)
        detector.detectEdges(sample)
        ellipses = detector.detectEllipses()
        if ellipses is None:
            continue
        for cx, cy, radius, a, b, angle in ellipses.reshape(-1, 6):
            a, b = a+radius, b+radius
            if min(a, b) <= 0:
                continue
            t = math.radians(angle)
            basis = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]]) @ np.diag([a, b])
            axes, lengths, _ = np.linalg.svd(np.diag([1/sx, 1/sy]) @ basis)
            major, minor = lengths
            x, y = cx/sx, cy/sy
            if minor/major < .25 or (major+minor)/2 < 8 or major > min(w, h)*.3:
                continue
            if not 0 <= x < w or not 0 <= y < bottom:
                continue
            original_angle = math.degrees(math.atan2(axes[1, 0], axes[0, 0])) % 180
            proposals.append(CraterCandidate(x, y, float(major), float(minor), original_angle, None, "edge-drawing"))
    proposals.extend(_large_rim_candidates(gray[:bottom]))
    # Keep the first high resolution fit in each scale-consistent cluster;
    # retaining every pass would falsely count one rim as several observations.
    kept = []
    for candidate in proposals:
        duplicate = any(math.hypot(candidate.x-other.x, candidate.y-other.y) < .45*min(candidate.major, other.major)
                        and .5 < candidate.major/other.major < 2 for other in kept)
        if not duplicate:
            kept.append(candidate)
    kept.sort(key=lambda c: -c.major)
    return DetectionResult(kept[:120], (0, 0, w, h), 1.)


def detect_craters(image, options=None, region=None):
    """Return ellipse candidates in ORIGINAL image pixels, optionally in an ROI.

    Radius limits refer to the mean of ellipse semiaxes. Support is sampled
    edge coverage used for ordering, not a probability that a crater is real.
    A candidate touching the detection boundary is intentionally excluded.
    """
    options = options or DetectionOptions()
    if (not math.isfinite(options.min_radius) or not math.isfinite(options.max_radius)
            or options.min_radius < 3 or options.max_radius <= options.min_radius):
        raise ValueError("最大半径必须大于最小半径，最小半径至少 3 像素。")
    if not 0 <= options.sensitivity <= 100 or not 1 <= options.max_candidates <= 500 or options.max_dimension < 128:
        raise ValueError("检测参数超出有效范围。")
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[2] != 3):
        raise ValueError("检测需要 8 位灰度或 RGB 图像。")
    height, width = image.shape[:2]
    if region is None:
        x, y, w, h = 0, 0, width, height
    else:
        if len(region) != 4 or not all(math.isfinite(v) for v in region):
            raise ValueError("检测区域无效。")
        rx, ry, rw, rh = region
        x, y = max(0, math.floor(rx)), max(0, math.floor(ry))
        right, bottom = min(width, math.ceil(rx+rw)), min(height, math.ceil(ry+rh))
        w, h = right-x, bottom-y
    if min(w, h) < 32:
        raise ValueError("检测区域太小，请扩大视野。")
    gray = image[y:y+h, x:x+w]
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    # Bound Hough memory/work. A zoomed ROI preserves smaller original details.
    # Large-radius searches need far fewer pixels. Keep at least ~24 samples
    # per minimum radius, avoiding a costly 1600px Hough pass for close-ups.
    dimension = min(options.max_dimension, max(600., max(w, h)*24/options.min_radius))
    factor = min(1., dimension/max(w, h))
    if factor < 1:
        gray = cv2.resize(gray, (max(1, round(w*factor)), max(1, round(h*factor))), interpolation=cv2.INTER_AREA)
    sy, sx = gray.shape[0]/h, gray.shape[1]/w
    factor = min(sx, sy)
    if float(np.std(gray)) < 1:
        return DetectionResult([], (x, y, w, h), factor)
    background = cv2.GaussianBlur(gray, (0, 0), sigmaX=32., sigmaY=32.)
    high_pass = cv2.addWeighted(gray, 1., background, -1., 128.)
    equalized = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(high_pass)
    blurred = cv2.GaussianBlur(equalized, (0, 0), 1.)
    sharp = cv2.addWeighted(equalized, 1.4, blurred, -.4, 0)
    enhanced = cv2.GaussianBlur(sharp, (5, 5), 1.)
    median = float(np.median(enhanced))
    sensitivity = options.sensitivity/100.
    lower = max(12., (.75-.45*sensitivity)*median)
    upper = max(lower+20., (1.7-.5*sensitivity)*median)
    edges = cv2.Canny(enhanced, lower, min(255., upper))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    distance, labels = cv2.distanceTransformWithLabels(255-edges, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    gx = cv2.Sobel(enhanced, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(enhanced, cv2.CV_32F, 0, 1, ksize=3)
    ey, ex = np.nonzero(edges)
    gradient = np.zeros((int(labels.max())+1, 2), np.float32)
    if len(ex):
        normals = np.column_stack((gx[ey, ex], gy[ey, ex]))
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-6)
        gradient[labels[ey, ex]] = normals
    proposals = []
    if options.max_radius*factor >= min(gray.shape)*.2:
        for candidate in _large_rim_candidates(gray):
            original = _map_candidate(candidate, sx, sy, x, y)
            if options.min_radius <= (original.major+original.minor)/2 <= options.max_radius:
                proposals.append(original)

    def accept(cx, cy, a, b, angle, method):
        if b > a:
            a, b, angle = b, a, (angle+90.) % 180.
        radius = (a+b)/2
        if not options.min_radius*factor <= radius <= options.max_radius*factor or b/a < .28:
            return
        theta = math.radians(angle)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        half_w = math.hypot(a*cos_t, b*sin_t)
        half_h = math.hypot(a*sin_t, b*cos_t)
        sh, sw = gray.shape
        if cx-half_w < 2 or cy-half_h < 2 or cx+half_w >= sw-2 or cy+half_h >= sh-2:
            return
        t = np.linspace(0, 2*np.pi, 96, endpoint=False)
        xx = np.rint(cx+a*np.cos(t)*cos_t-b*np.sin(t)*sin_t).astype(int)
        yy = np.rint(cy+a*np.cos(t)*sin_t+b*np.sin(t)*cos_t).astype(int)
        rim_normal = np.column_stack((np.cos(t)/a*cos_t-np.sin(t)/b*sin_t,
                                      np.cos(t)/a*sin_t+np.sin(t)/b*cos_t))
        rim_normal /= np.linalg.norm(rim_normal, axis=1, keepdims=True)
        alignment = np.abs(np.sum(gradient[labels[yy, xx]]*rim_normal, axis=1))
        support = float(np.mean((distance[yy, xx] <= 2.) & (alignment > .85)))
        if support < .58-.16*sensitivity:
            return
        if radius >= min(gray.shape)*.2:
            supported = (distance[yy, xx] <= 2.) & (alignment > .85)
            if support < .55 or np.count_nonzero(supported.reshape(8, -1).mean(axis=1) >= .4) < 6:
                return
        # Transform the conic, not just the center: rounded resize dimensions
        # can have slightly different x/y factors.
        basis = np.array([[cos_t, -sin_t], [sin_t, cos_t]]) @ np.diag([a, b])
        axes, lengths, _ = np.linalg.svd(np.diag([1/sx, 1/sy]) @ basis)
        angle_original = math.degrees(math.atan2(axes[1, 0], axes[0, 0])) % 180.
        proposals.append(CraterCandidate(cx/sx+x, cy/sy+y, float(lengths[0]), float(lengths[1]),
                                         angle_original, support, method))

    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    for contour in contours:
        if len(contour) < 12:
            continue
        (cx, cy), (cw, ch), angle = cv2.fitEllipse(contour)
        if cw <= 0 or ch <= 0:
            continue
        # Reject jagged mountain contours that only share an ellipse bounding box.
        theta = math.radians(angle)
        delta = contour[:, 0, :]-[cx, cy]
        u = delta[:, 0]*math.cos(theta)+delta[:, 1]*math.sin(theta)
        v = -delta[:, 0]*math.sin(theta)+delta[:, 1]*math.cos(theta)
        radial_error = np.abs(np.sqrt((u/(cw/2))**2+(v/(ch/2))**2)-1.)
        if float(np.median(radial_error)) > .09+.08*sensitivity:
            continue
        accept(cx, cy, cw/2, ch/2, angle, "ellipse")
    minimum = max(3, math.floor(options.min_radius*factor))
    maximum = math.ceil(min(options.max_radius*factor, min(gray.shape)/2))
    circles = cv2.HoughCircles(enhanced, cv2.HOUGH_GRADIENT, dp=1.4,
                               minDist=max(8., options.min_radius*factor), param1=upper,
                               param2=42.-24.*sensitivity,
                               minRadius=minimum, maxRadius=maximum) if maximum > minimum else None
    if circles is not None:
        for cx, cy, radius in circles[0]:
            accept(float(cx), float(cy), float(radius), float(radius), 0., "circle")
    kept = []
    rank = (lambda c: (-c.support*(1.+.2*math.log1p(c.major/8)), -c.major, c.y, c.x)) if options.prefer_large else (lambda c: (-c.support, c.method != "ellipse", -c.major, c.y, c.x))
    for candidate in sorted(proposals, key=rank):
        # Compare radius as well as center, regardless of angle or method.
        # This suppresses two edges of one rim without merging nested craters.
        radius = (candidate.major+candidate.minor)/2
        duplicate = any(math.hypot(candidate.x-other.x, candidate.y-other.y) < .45*min(radius, (other.major+other.minor)/2)
                        and .55 < radius/((other.major+other.minor)/2) < 1.8 for other in kept)
        if not duplicate:
            kept.append(candidate)
            if len(kept) >= options.max_candidates:
                break
    return DetectionResult(kept, (x, y, w, h), factor)
