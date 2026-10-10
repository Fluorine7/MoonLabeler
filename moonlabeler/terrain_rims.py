# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Trace bounded, continuous crater crests in a local elevation map.

Catalogue centers and diameters constrain the search. Results describe the DEM
crest at its native resolution; they are not photographic edge measurements.
"""
import numpy as np
from .geometry import MOON_RADIUS_KM, surface_vectors
from .registration import transform_points
from .project import MIN_OUTLINE_DIAMETER_KM


def trace_crater_rim(dem, feature):
    radius = feature['diameter']/2
    if radius < 3*dem.resolution_km:
        return None
    center = surface_vectors([feature['lat']], [feature['lon']])[0]
    lon = np.radians(feature['lon'])
    east = np.array([-np.sin(lon), np.cos(lon), 0.])
    north = np.cross(center, east)
    theta = np.linspace(0, 2*np.pi, 128, endpoint=False)
    tangent = np.cos(theta)[:, None]*north + np.sin(theta)[:, None]*east
    factors = np.linspace(.65, 1.35, 71)
    angles = radius/MOON_RADIUS_KM*factors
    vectors = np.cos(angles)[None, :, None]*center + np.sin(angles)[None, :, None]*tangent[:, None, :]
    lat = np.degrees(np.arcsin(np.clip(vectors[:, :, 2], -1, 1)))
    lon = np.degrees(np.arctan2(vectors[:, :, 1], vectors[:, :, 0]))
    height = dem.sample(lat.ravel(), lon.ravel()).reshape(lat.shape)
    if not np.isfinite(height).all() or np.median(np.ptp(height, axis=1)) < .25:
        return None
    score = (height-height.min(axis=1)[:, None])/np.maximum(np.ptp(height, axis=1)[:, None], .2)
    score -= .25*((factors-1)/.35)**2
    transition = .03*((factors[:, None]-factors[None, :])/.035)**2
    # Enforce continuity, including the angular seam, without forcing a circle.
    end = np.argmin(abs(factors-1))
    for _ in range(2):
        state = score[0] - transition[end]
        trace = []
        for row in score[1:]:
            choices = state[:, None]-transition
            previous = choices.argmax(axis=0)
            trace.append(previous)
            state = choices[previous, np.arange(len(factors))]+row
        selected = np.zeros(len(theta), int)
        selected[-1] = state.argmax()
        for row in range(len(theta)-2, -1, -1):
            selected[row] = trace[row][selected[row+1]]
        end = selected[-1]
    if np.mean((selected > 1) & (selected < len(factors)-2)) < .85:
        return None
    # Smooth angular grid steps, retaining the measured departures from a circle.
    radii = factors[selected]
    radii = sum(weight*np.roll(radii, offset) for offset, weight in
                ((-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1)))/9
    angles = radius/MOON_RADIUS_KM*radii
    vectors = np.cos(angles)[:, None]*center + np.sin(angles)[:, None]*tangent
    lat = np.degrees(np.arcsin(np.clip(vectors[:, 2], -1, 1)))
    lon = np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0]))
    height = dem.sample(lat, lon)
    center_height = float(dem.sample([feature['lat']], [feature['lon']])[0])
    if not np.isfinite(height).all() or np.mean(height)-center_height < .15:
        return None
    coordinates = np.column_stack((lat, lon, height))
    return {'coordinates': np.vstack((coordinates, coordinates[0])).tolist(),
            'source': dem.name, 'resolution_km': dem.resolution_km}


def trace_catalog_rims(dem, geometry, matrix, catalog, shape):
    """Keep only resolvable crater outlines large enough for this photograph."""
    h, w = shape[:2]
    eligible = [f for f in catalog if f['kind'] in ('Crater, craters', 'Satellite Feature')
                and f['diameter'] >= max(MIN_OUTLINE_DIAMETER_KM, 6*dem.resolution_km)]
    if not eligible:
        return {}
    points, visible, _ = geometry.project([f['lat'] for f in eligible], [f['lon'] for f in eligible])
    pixels = transform_points(matrix, points)
    scale = np.sqrt(abs(np.linalg.det(matrix[:, :2])))
    rims = {}
    for feature, pixel, okay in zip(eligible, pixels, visible):
        diameter_px = feature['diameter']/MOON_RADIUS_KM*scale
        if not okay or diameter_px < min(h, w)*.055:
            continue
        if not -diameter_px < pixel[0] < w+diameter_px or not -diameter_px < pixel[1] < h+diameter_px:
            continue
        rim = trace_crater_rim(dem, feature)
        if rim:
            rims[feature['id']] = rim
    return rims
