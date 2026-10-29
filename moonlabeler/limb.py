# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Wide lunar-limb registration, independently implemented without AI models.

A long circular limb establishes scale and translation. Phase and high-pass
albedo templates then distinguish rotation and handedness. Limb samples are
not image-feature correspondences or individually identified crater centers.
Short polar arcs, weak textures, and competing orientations are rejected.
"""
import math

from .tasks import check_cancelled
from ._opencv import cv2
import numpy as np

from .atlas import render_atlas
from .geometry import MOON_RADIUS_KM
from .identification import IdentificationError, IdentificationResult
from .recognition_mask import mask_kwargs


def fit_lunar_limb(image, *, photo_mask=None):
    """Return original-image center, radius, edge RMS and supporting samples."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    factor = min(1., 800/max(gray.shape))
    small = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    bright = photo_mask.percentile(small, 99) if photo_mask is not None else float(np.percentile(small, 99))
    threshold = max(4., bright*.12)
    contours, _ = cv2.findContours((small > threshold).astype(np.uint8)*255,
                                  cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise IdentificationError("没有可用的月盘轮廓。")
    contour = photo_mask.largest_contour(contours, small.shape) if photo_mask is not None else max(contours, key=cv2.contourArea)
    if contour is None:
        raise IdentificationError("月盘外缘弧度不足；局部月缘不能仅靠轮廓定位。")
    if cv2.contourArea(contour) < small.size*.02 or len(contour) < 60:
        raise IdentificationError("月盘轮廓太小，无法独立验证。")
    points = contour[::max(1, len(contour)//700), 0].astype(float)
    if photo_mask is not None:
        points = points[photo_mask.allows(points, small.shape, padding=2)]
        if len(points) < 60:
            raise IdentificationError("月盘外缘弧度不足；局部月缘不能仅靠轮廓定位。")
    rng = np.random.default_rng(17)
    best = None
    h, w = small.shape
    for _ in range(3500):
        if _ % 64 == 0:
            check_cancelled()
        p = points[rng.choice(len(points), 3, replace=False)]
        design = 2*(p[1:]-p[0])
        if abs(np.linalg.det(design)) < 50:
            continue
        center = np.linalg.solve(design, np.sum(p[1:]**2, axis=1)-np.sum(p[0]**2))
        radius = np.linalg.norm(center-p[0])
        if not .2*w < radius < 1.1*w or not -.1*w < center[0] < 1.1*w or not -.1*h < center[1] < 2*h:
            continue
        inside = np.abs(np.linalg.norm(points-center, axis=1)-radius) < 1.5
        if best is None or inside.sum() > best.sum():
            best = inside
    if best is None or best.sum() < max(60, len(points)*.25):
        raise IdentificationError("月盘外缘弧度不足；局部月缘不能仅靠轮廓定位。")
    p = points[best]
    solution = np.linalg.lstsq(np.column_stack((2*p, np.ones(len(p)))), np.sum(p*p, axis=1), rcond=None)[0]
    center = solution[:2]
    radius = math.sqrt(max(0., solution[2]+np.sum(center*center)))
    if radius <= 0:
        raise IdentificationError("月盘轮廓拟合无效。")
    angles = np.sort(np.arctan2(p[:, 1]-center[1], p[:, 0]-center[0]))
    span = 2*np.pi-np.diff(np.r_[angles, angles[0]+2*np.pi]).max()
    rms = float(np.sqrt(np.mean((np.linalg.norm(p-center, axis=1)-radius)**2)))
    if span < np.radians(120) or rms > radius*.004:
        raise IdentificationError("月盘外缘过短或偏离圆形，未采用轮廓配准。")
    return center/factor, radius/factor, rms/factor, int(best.sum())


def _correlation(first, second):
    first, second = first-first.mean(), second-second.mean()
    denominator = math.sqrt(float(np.dot(first, first)*np.dot(second, second)))
    return float(np.dot(first, second)/denominator) if denominator > 1e-6 else -1.


def identify_from_limb(image, geometry, *, cache=None, photo_mask=None):
    """Require a long limb AND distinct albedo evidence, not phase alone."""
    center, radius, rms, count = fit_lunar_limb(image, **mask_kwargs(photo_mask))
    size = 256
    reference, _ = render_atlas(geometry, size)
    reference = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY).astype(np.float32)
    reference_hp = reference-cv2.GaussianBlur(reference, (0, 0), 8)
    yy, xx = np.mgrid[:size, :size]
    points = np.stack(((xx-(size-1)/2)/(size*.47), (yy-(size-1)/2)/(size*.47)), axis=-1)
    disk = np.sum(points*points, axis=-1) < .9**2
    keep = disk & (reference > 20)
    if keep.sum() < 500 or reference_hp[keep].std() < 2:
        raise IdentificationError("月海纹理不足，月相轮廓本身不能确认方向。")
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    photo = cv2.GaussianBlur(gray, (0, 0), radius/100).astype(np.float32)
    # Finite-distance perspective puts the spherical horizon just outside 1.
    scale = radius*math.sqrt(1-(MOON_RADIUS_KM/geometry.distance_km)**2)
    scores = []

    def compare(degree, mirror):
        theta = math.radians(degree)
        linear = np.array([[math.cos(theta), -math.sin(theta)],
                           [math.sin(theta), math.cos(theta)]]) @ np.diag([mirror, 1])
        target = points @ linear.T*scale+center
        in_frame = ((target[:, :, 0] >= 0) & (target[:, :, 0] < gray.shape[1]) &
                    (target[:, :, 1] >= 0) & (target[:, :, 1] < gray.shape[0]))
        if np.mean(in_frame[keep]) < .8:
            return (-1., -1., mirror, degree)
        sample = cv2.remap(photo, target[:, :, 0].astype(np.float32), target[:, :, 1].astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        sample_hp = sample-cv2.GaussianBlur(sample, (0, 0), 8)
        detail_domain, phase_domain = keep, disk
        if photo_mask is not None:
            usable = photo_mask.allows(target, gray.shape, padding=3)
            detail_domain, phase_domain = keep & usable, disk & usable
            if detail_domain.sum() < max(500, keep.sum()*.5) or phase_domain.sum() < disk.sum()*.5:
                return (-1., -1., mirror, degree)
        return (_correlation(reference_hp[detail_domain], sample_hp[detail_domain]),
                _correlation(reference[phase_domain], sample[phase_domain]), mirror, degree)

    for mirror in (1, -1):
        scores.extend(compare(degree, mirror) for degree in range(0, 360, 2))
    best = max(scores)
    scores.extend(compare(best[3]+offset, best[2]) for offset in np.arange(-2, 2.01, .25))
    best = max(scores)
    texture, phase, mirror, degree = best
    alternatives = [row[0] for row in scores if row[2] != mirror or abs((row[3]-degree+180)%360-180) >= 8]
    theta = math.radians(degree)
    linear = np.array([[math.cos(theta), -math.sin(theta)],
                       [math.sin(theta), math.cos(theta)]]) @ np.diag([mirror, 1])
    matrix = np.column_stack((linear*scale, center))
    if texture < .5 or phase < .75:
        # A distinct direction below the albedo threshold can only nominate
        # a bounded terrain search. Existing successful paths do no extra work;
        # weak phase, competing directions and untextured shapes still fail.
        if (cache is not None and .35 <= texture < .5 and phase >= .8
                and (not alternatives or texture-max(alternatives) >= .15)):
            from .limb_refinement import identify_limb_terrain
            try:
                verified = identify_limb_terrain(image, geometry, matrix, (center, radius, rms, count),
                                                 cache, **mask_kwargs(photo_mask))
            except (OSError, ValueError):
                verified = None
            if verified is not None:
                verified.refinement.update(seed_albedo_correlation=texture, seed_phase_correlation=phase)
                return verified
        raise IdentificationError("月盘轮廓已拟合，但月海纹理与月相未同时通过验证。")
    if alternatives and texture-max(alternatives) < .15:
        raise IdentificationError("月海纹理存在接近的方向或镜像结果，未采用配准。")
    return IdentificationResult(matrix, [], rms, texture, 0,
                                "lunar limb / phase + high-pass LROC albedo / JPL projection",
                                limb_inliers=count, texture_correlation=texture)
