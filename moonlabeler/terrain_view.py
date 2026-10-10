# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Temporary relief-aware view used while a local DEM is open."""
from dataclasses import dataclass
import numpy as np
from .geometry import Geometry, MOON_RADIUS_KM


@dataclass
class TerrainView(Geometry):
    dem: object

    @classmethod
    def from_geometry(cls, geometry, dem):
        return cls(geometry.observer, geometry.right, geometry.north, geometry.sun,
                   geometry.distance_km, geometry.utc, dem)

    def project(self, latitudes, longitudes, height_km=None):
        if height_km is None:
            height_km = self.dem.sample(latitudes, longitudes)
        return super().project(latitudes, longitudes, height_km)

    def unproject(self, points):
        """Find the first sampled terrain crossing, then bisect its bracket.

        The +/-15 km shell bounds the local search. This is a bounded-resolution
        DEM intersection, not a claim of sub-grid or exact silhouette accuracy.
        """
        points = np.asarray(points, float)
        if points.ndim != 2 or points.shape[1] != 2:
            raise ValueError('Projection coordinates must have N x 2 shape')
        d = self.distance_km/MOON_RADIUS_KM
        rays = -self.observer + (points[:, :1]*self.right-points[:, 1:]*self.north)/d
        a = np.sum(rays*rays, axis=1)
        upper, lower = 1+15/MOON_RADIUS_KM, 1-15/MOON_RADIUS_KM
        disc = d*d-a*(d*d-upper*upper)
        valid = np.isfinite(points).all(axis=1) & (disc >= 0)
        indices = np.flatnonzero(valid)
        latitude, longitude = np.full(len(points), np.nan), np.full(len(points), np.nan)
        if not len(indices):
            return latitude, longitude, valid
        rays, a, disc = rays[indices], a[indices], disc[indices]
        first = (d*d-upper*upper)/(d+np.sqrt(disc))
        lower_disc = d*d-a*(d*d-lower*lower)
        last = (d*d-lower*lower)/(d+np.sqrt(np.maximum(lower_disc, 0)))
        last = np.where(lower_disc >= 0, last, d/a)

        def sample(length):
            vectors = d*self.observer + length[:, None]*rays
            radius = np.linalg.norm(vectors, axis=1)
            lat = np.degrees(np.arcsin(np.clip(vectors[:, 2]/radius, -1, 1)))
            lon = np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0]))
            height = self.dem.sample(lat, lon)
            return lat, lon, radius-1-height/MOON_RADIUS_KM

        near, far, previous = first.copy(), last.copy(), first.copy()
        found = np.zeros(len(indices), bool)
        for fraction in np.linspace(0, 1, 33)[1:]:
            current = first + (last-first)*fraction
            crossed = (sample(current)[2] <= 0) & ~found
            near[crossed], far[crossed] = previous[crossed], current[crossed]
            found |= crossed
            previous = current
        for _ in range(10):
            middle = (near+far)/2
            residual = sample(middle)[2]
            near = np.where(residual > 0, middle, near)
            far = np.where(residual <= 0, middle, far)
        lat, lon, _ = sample((near+far)/2)
        valid[indices] = found
        latitude[indices[found]], longitude[indices[found]] = lat[found], lon[found]
        return latitude, longitude, valid
