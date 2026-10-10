# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Spherical Moon geometry in the IAU mean Earth / polar axis frame.

Image coordinates: celestial north up, lunar east right, y increases down.
Registration absorbs the camera's rotation, scale, translation and reflection.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

MOON_RADIUS_KM = 1737.4


def unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)


def surface_vectors(latitudes, longitudes):
    lat, lon = np.radians(latitudes), np.radians(longitudes)
    return np.column_stack((np.cos(lat) * np.cos(lon),
                            np.cos(lat) * np.sin(lon), np.sin(lat)))


@dataclass
class Geometry:
    observer: np.ndarray
    right: np.ndarray
    north: np.ndarray
    sun: np.ndarray
    distance_km: float
    utc: str

    def project(self, latitudes, longitudes, height_km=None):
        vectors = surface_vectors(latitudes, longitudes)
        if height_km is not None:
            heights = np.broadcast_to(np.asarray(height_km, float), (len(vectors),))
            vectors *= (1 + heights/MOON_RADIUS_KM)[:, None]
        depth = vectors @ self.observer
        perspective = 1.0 - MOON_RADIUS_KM / self.distance_km * depth
        xy = np.column_stack((vectors @ self.right, -vectors @ self.north))
        xy /= perspective[:, None]
        # Finite-distance horizon, rather than merely the near hemisphere.
        visible = depth > MOON_RADIUS_KM / self.distance_km * np.sum(vectors*vectors, axis=1)
        illuminated = vectors @ self.sun > 0.0
        return xy, visible, illuminated

    def unproject(self, points):
        """Intersect view rays with the reference sphere; off-disk pixels are NaN."""
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2:
            raise ValueError("投影坐标必须为 N×2。")
        distance = self.distance_km / MOON_RADIUS_KM
        rays = -self.observer + (points[:, :1]*self.right - points[:, 1:]*self.north)/distance
        a = np.sum(rays*rays, axis=1)
        discriminant = distance*distance - a*(distance*distance-1.)
        visible = discriminant >= 0
        length = (distance*distance-1.)/(distance + np.sqrt(np.maximum(discriminant, 0)))
        vectors = distance*self.observer + length[:, None]*rays
        vectors[~visible] = np.nan
        latitude = np.degrees(np.arcsin(np.clip(vectors[:, 2], -1, 1)))
        longitude = np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0]))
        return latitude, longitude, visible

    @property
    def libration(self):
        lat = np.degrees(np.arcsin(self.observer[2]))
        lon = np.degrees(np.arctan2(self.observer[1], self.observer[0]))
        return float(lat), float(lon)

    def to_dict(self):
        return {key: getattr(self, key).tolist() for key in
                ("observer", "right", "north", "sun")} | {
                    "distance_km": self.distance_km, "utc": self.utc}

    @classmethod
    def from_dict(cls, data):
        return cls(*(np.asarray(data[k], dtype=float) for k in
                     ("observer", "right", "north", "sun")),
                   float(data["distance_km"]), data["utc"])


def geometry_from_nasa(record, utc):
    """NASA SVS hourly geocentric data; position angle east of celestial north."""
    obs = surface_vectors([record["subearth"]["lat"]],
                          [record["subearth"]["lon"]])[0]
    lunar_north = unit(np.array([0., 0., 1.]) - obs[2] * obs)
    lunar_right = unit(np.cross(lunar_north, obs))
    angle = np.radians(record["posangle"])
    # Celestial east is LEFT on a north-up sky image. A positive pole
    # position angle therefore puts lunar north to the left of camera north.
    north = np.cos(angle) * lunar_north + np.sin(angle) * lunar_right
    right = unit(np.cross(north, obs))
    sun = surface_vectors([record["subsolar"]["lat"]],
                          [record["subsolar"]["lon"]])[0]
    return Geometry(obs, right, north, sun, record["distance"], utc.isoformat())


def compute_geometry(utc: datetime, cache: Path, latitude=None, longitude=None):
    """JPL DE421 lunar orientation; range approximately 1900–2050.

    Uses the geometric observer-Moon vector, following Skyfield's libration
    convention. Does not model local lunar relief or atmospheric refraction.
    """
    from skyfield.api import Loader, PlanetaryConstants, wgs84

    if utc.tzinfo is None:
        raise ValueError("拍摄时间必须包含时区。")
    load = Loader(str(cache), verbose=False)
    t = load.timescale(builtin=True).from_datetime(utc.astimezone(timezone.utc))
    eph = load("de421.bsp")
    try:
        pc = PlanetaryConstants()
        with load("moon_080317.tf") as stream:
            pc.read_text(stream)
        with load("pck00008.tpc") as stream:
            pc.read_text(stream)
        binary = load("moon_pa_de421_1900-2050.bpc")
        pc.read_binary(binary)
        frame = pc.build_frame_named("MOON_ME_DE421")
        rotation = frame.rotation_at(t)
        observer_body = eph["earth"]
        if latitude is not None and longitude is not None:
            observer_body += wgs84.latlon(latitude, longitude)
        moon = eph["moon"]
        difference = (observer_body - moon).at(t).position.km
        distance = float(np.linalg.norm(difference))
        direction = unit(difference)
        sky_north = unit(np.array([0., 0., 1.]) - direction[2] * direction)
        sky_right = unit(np.cross(sky_north, direction))
        sunlight = unit((eph["sun"] - moon).at(t).position.km)
        return Geometry(rotation @ direction, rotation @ sky_right,
                        rotation @ sky_north, rotation @ sunlight,
                        distance, utc.isoformat())
    finally:
        if "binary" in locals():
            binary.close()
        eph.close()
