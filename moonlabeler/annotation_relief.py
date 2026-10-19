# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Small, portable elevation snapshots for display, independent of pose fitting.

Only existing local LOLA data is read. No DEM handle or download is needed to
redraw or export a saved project. Reference rims are not measured crater crests.
"""
from pathlib import Path

import numpy as np

from .geometry import MOON_RADIUS_KM, surface_vectors
from .registration import transform_points
from .eyepiece import distort_points
from .landing_sites import landing_sites
from .terrain import ElevationMap

MIN_OUTLINE_DIAMETER_KM = 35.
MAX_HEIGHT_KM = 15.


def catalogue_rim(feature, radius_factors=(1.,)):
    center = surface_vectors([feature['lat']], [feature['lon']])[0]
    lon = np.radians(feature['lon'])
    east = np.array([-np.sin(lon), np.cos(lon), 0.])
    north = np.cross(center, east)
    theta = np.linspace(0., 2*np.pi, 97)
    tangent = np.cos(theta[:, None])*north + np.sin(theta[:, None])*east
    angles = feature['diameter']/(2*MOON_RADIUS_KM)*np.asarray(radius_factors)
    vectors = (np.cos(angles[:, None, None])*center + np.sin(angles[:, None, None])*tangent).reshape(-1, 3)
    return np.column_stack((np.degrees(np.arcsin(np.clip(vectors[:, 2], -1, 1))),
                            np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0]))))


def prepare_annotation_relief(catalog, geometry, matrix, shape, cache, *, dem_path='', lens_distortion=None):
    """Batch sample on-frame locations and resolvable large reference rims.

    Invalid/missing local maps leave display on its original reference sphere.
    A failed optional height correction must never discard a validated pose.
    """
    if geometry is None or matrix is None:
        return {}
    paths = [Path(dem_path)] if dem_path else []
    paths.append(Path(cache)/'terrain'/'LDEM_16.LBL')
    for path in dict.fromkeys(paths):
        if not path.is_file():
            continue
        try:
            dem = ElevationMap.load(path)
            try:
                return _sample(catalog, geometry, matrix, shape, dem, lens_distortion)
            finally:
                dem.close()
        except (ValueError, OSError):
            continue
    return {}


def _sample(catalog, geometry, matrix, shape, dem, lens_distortion):
    # Include the optional landing layer now so toggling it needs no DEM I/O.
    catalog = list(catalog) + landing_sites()
    if not catalog:
        return {}
    lat, lon = [f['lat'] for f in catalog], [f['lon'] for f in catalog]
    points, visible, _ = geometry.project(lat, lon)
    pixels = distort_points(transform_points(matrix, points), lens_distortion)
    h, w = shape[:2]
    scale = np.linalg.norm(matrix[:, :2], ord=2)
    # Include locations which relief could move across the image border.
    margin = max(4., scale*MAX_HEIGHT_KM/MOON_RADIUS_KM*3)
    keep = (visible & np.isfinite(pixels).all(axis=1) &
            (pixels[:, 0] >= -margin) & (pixels[:, 0] < w+margin) &
            (pixels[:, 1] >= -margin) & (pixels[:, 1] < h+margin))
    chosen = [f for f, okay in zip(catalog, keep) if okay]
    heights = dem.sample([f['lat'] for f in chosen], [f['lon'] for f in chosen])
    valid = np.isfinite(heights) & (np.abs(heights) <= MAX_HEIGHT_KM)
    sampled = {f['id']: [float(f['lat']), float(f['lon']), float(height)]
               for f, height, okay in zip(chosen, heights, valid) if okay}
    rings, candidates = [], []
    for f in chosen:
        if (f['id'] not in sampled or f['kind'] not in ('Crater, craters', 'Satellite Feature') or
                f['diameter'] < max(MIN_OUTLINE_DIAMETER_KM, 6*dem.resolution_km) or
                f['diameter']/MOON_RADIUS_KM*scale < min(h, w)*.055):
            continue
        candidates.append(f)
        rings.append(catalogue_rim(f))
    rims = {}
    if rings:
        coordinates = np.concatenate(rings)
        heights = dem.sample(coordinates[:, 0], coordinates[:, 1]).reshape(len(rings), -1)
        for f, ring, height in zip(candidates, rings, heights):
            if np.isfinite(height).all() and (np.abs(height) <= MAX_HEIGHT_KM).all():
                rims[f['id']] = {'feature': [float(f['lat']), float(f['lon']), float(f['diameter'])],
                                 'coordinates': np.column_stack((ring, height)).tolist()}
    return {'source': dem.name, 'resolution_km': float(dem.resolution_km), 'points': sampled, 'rims': rims}


def contour_center(pixels):
    """Area centroid; a partial or degenerate contour has no visual centre."""
    if len(pixels) < 6 or not np.allclose(pixels[0], pixels[-1]) or not np.isfinite(pixels).all():
        return None
    origin = np.mean(pixels[:-1], axis=0)
    ring = pixels-origin
    cross = ring[:-1, 0]*ring[1:, 1]-ring[1:, 0]*ring[:-1, 1]
    area = cross.sum()
    if abs(area) < 1e-6:
        return None
    return origin+np.sum((ring[:-1]+ring[1:])*cross[:, None], axis=0)/(3*area)
