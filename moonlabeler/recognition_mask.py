# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Immutable photo exclusions, rasterized lazily at each search resolution.

Project files hold vector operations in original photo pixels. A search shares
one snapshot across its detectors and verification stages. Empty/disabled masks
are represented by None, retaining the existing image-processing fast path.
"""
from collections import OrderedDict
import math

import numpy as np
from ._opencv import cv2


def mask_kwargs(photo_mask):
    return {} if photo_mask is None else {'photo_mask': photo_mask}


class PhotoMask:
    def __init__(self, operations, shape):
        self.shape = tuple(shape[:2])
        self.operations = tuple((op['kind'], tuple(tuple(p) for p in op['points']),
                                 float(op.get('radius', 0))) for op in operations)
        self._rasters = OrderedDict()
        self._distances = OrderedDict()
        self._crops = {}

    def raster(self, shape, padding=0):
        """255 means usable. Work and storage depend on search, not photo, size."""
        h, w = map(int, shape[:2])
        key = (h, w, padding)
        if key in self._rasters:
            self._rasters.move_to_end(key)
            return self._rasters[key]
        if padding:
            allowed = cv2.erode(self.raster((h, w)), np.ones((2*padding+1, 2*padding+1), np.uint8))
        else:
            allowed = np.full((h, w), 255, np.uint8)
            sx, sy = w/self.shape[1], h/self.shape[0]
            for kind, points, radius in self.operations:
                vertices = np.rint(np.asarray(points)*[sx, sy]).astype(np.int32)
                if kind == 'polygon':
                    # Fill separately: an even-odd fill of all contours would
                    # turn overlapping exclusions back into usable holes.
                    cv2.fillPoly(allowed, [vertices], 0)
                else:
                    value = 255 if kind == 'erase' else 0
                    axes = (max(1, round(radius*sx)), max(1, round(radius*sy)))
                    for point in vertices:
                        cv2.ellipse(allowed, tuple(point), axes, 0, 0, 360, value, -1)
                    for first, last in zip(points, points[1:]):
                        delta = np.subtract(last, first)
                        length = float(np.linalg.norm(delta))
                        if length:
                            offset = np.array([-delta[1], delta[0]])*(radius/length)
                            quad = np.array([first+offset, last+offset, last-offset, first-offset])
                            cv2.fillPoly(allowed, [np.rint(quad*[sx, sy]).astype(np.int32)], value)
        allowed.flags.writeable = False
        self._rasters[key] = allowed
        # A few bounded working resolutions fit comfortably; never retain a
        # full photo pyramid just because a user repeatedly changes the ROI.
        while len(self._rasters) > 8 or (len(self._rasters) > 1 and
                sum(value.nbytes for value in self._rasters.values()) > 32*1024**2):
            self._rasters.popitem(last=False)
        return allowed

    def cropped(self, origin, shape, source_shape=None):
        """A view in crop pixels; resizing alone does not require a new object."""
        source_shape = self.shape if source_shape is None else source_shape[:2]
        key = (*origin, *shape[:2], *source_shape)
        if key not in self._crops:
            sx, sy = source_shape[1]/self.shape[1], source_shape[0]/self.shape[0]
            operations = [{'kind': kind, 'points': (np.asarray(points)*[sx, sy]-origin).tolist(),
                           'radius': radius*math.sqrt(sx*sy)} for kind, points, radius in self.operations]
            self._crops[key] = PhotoMask(operations, shape)
            if len(self._crops) > 8:
                self._crops.pop(next(iter(self._crops)))
        return self._crops[key]

    def allows(self, points, shape, padding=0):
        points = np.asarray(points)
        h, w = shape[:2]
        # Point queries also stay bounded for large original photographs.
        scale = min(1., 2200/max(h, w))
        rh, rw = max(1, round(h*scale)), max(1, round(w*scale))
        xy = np.rint(points*[rw/w, rh/h]).astype(int)
        inside = (points[..., 0] >= 0) & (points[..., 1] >= 0) & (points[..., 0] < w) & (points[..., 1] < h)
        # Rounding near the last pixel must not turn an in-frame point into
        # an exclusion merely because this query uses a smaller working grid.
        xy = np.clip(xy, [0, 0], [rw-1, rh-1])
        result = np.zeros(inside.shape, bool)
        result[inside] = self.raster((rh, rw), padding)[xy[..., 1][inside], xy[..., 0][inside]] != 0
        return result

    def percentile(self, gray, percentile):
        values = gray[self.raster(gray.shape) != 0]
        return float(np.percentile(values, percentile)) if values.size else 0.

    def largest_contour(self, contours, shape):
        """Rank real contours by usable area, without creating mask-cut edges."""
        allowed = self.raster(shape)
        best, score = None, 0
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w*h <= score:
                continue
            region = allowed[y:y+h, x:x+w]
            if not np.any(region):
                continue
            interior = np.zeros((h, w), np.uint8)
            cv2.fillPoly(interior, [contour-[x, y]], 1)
            usable = np.count_nonzero(interior & region)
            if usable > score:
                best, score = contour, usable
        return best

    def keypoint_selection(self, keypoints, shape):
        """Reject descriptors whose neighbourhood straddles excluded pixels."""
        key = tuple(shape[:2])
        if key not in self._distances:
            self._distances[key] = cv2.distanceTransform(self.raster(shape), cv2.DIST_L2, 3)
            if len(self._distances) > 2:
                self._distances.popitem(last=False)
        distance = self._distances[key]
        return np.array([distance[min(round(k.pt[1]), shape[0]-1), min(round(k.pt[0]), shape[1]-1)]
                         > max(3., k.size*2) for k in keypoints], bool)

    def accepts_crater(self, candidate, shape):
        angle = math.radians(candidate.angle)
        t = np.linspace(0, 2*np.pi, 64, endpoint=False)
        x = candidate.x+candidate.major*np.cos(t)*math.cos(angle)-candidate.minor*np.sin(t)*math.sin(angle)
        y = candidate.y+candidate.major*np.cos(t)*math.sin(angle)+candidate.minor*np.sin(t)*math.cos(angle)
        points = np.vstack(([candidate.x, candidate.y], np.column_stack((x, y))))
        h, w = shape[:2]
        inside = (points[:, 0] >= 0) & (points[:, 0] < w) & (points[:, 1] >= 0) & (points[:, 1] < h)
        # The detector already validates partial rims. A mask elsewhere in
        # the photo must not introduce a new requirement for a complete rim.
        return bool(inside.any() and self.allows(points[inside], shape).all())
