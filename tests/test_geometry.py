# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from moonlabeler.geometry import Geometry, compute_geometry, geometry_from_nasa, MOON_RADIUS_KM


def test_cardinal_projection_and_horizon():
    geometry = Geometry(np.array([1.,0,0]), np.array([0.,1,0]), np.array([0.,0,1]),
                        np.array([1.,0,0]), 384400, "2026-01-01T00:00:00+00:00")
    points, visible, lit = geometry.project([0,0,45,0], [0,45,0,180])
    assert np.allclose(points[0], [0,0])
    assert points[1,0] > 0 and points[2,1] < 0
    assert visible.tolist() == [True,True,True,False]
    assert lit.tolist() == [True,True,True,False]


def test_nasa_pole_position_angle_is_east_of_north():
    record = {"subearth": {"lat":0.,"lon":0.}, "subsolar": {"lat":0.,"lon":0.},
              "distance":384400, "posangle":30.}
    geometry = geometry_from_nasa(record, datetime(2026,1,1,tzinfo=timezone.utc))
    xy, _, _ = geometry.project([45],[0])
    # North pole has positive celestial-east angle: upper left in north-up image.
    assert xy[0,0] < 0 and xy[0,1] < 0
    assert xy[0,0] / xy[0,1] == pytest.approx(np.tan(np.radians(30)))
    assert np.dot(geometry.north,geometry.right) == pytest.approx(0,abs=1e-12)


def test_skyfield_documented_libration_and_site_parallax():
    cache = Path(__file__).parents[1] / ".cache/ephemeris"
    if not (cache / "de421.bsp").exists():
        pytest.skip("Integration check requires downloaded JPL kernels")
    utc = datetime(2019,12,20,11,5,tzinfo=timezone.utc)
    geometry = compute_geometry(utc,cache)
    # Published numerical example in Skyfield's planetary-frame documentation.
    assert geometry.libration == pytest.approx((-6.749,1.520),abs=.0006)
    topocentric = compute_geometry(utc,cache,31.2,121.5)
    assert np.linalg.norm(geometry.observer-topocentric.observer) > .001
    assert np.linalg.norm(topocentric.observer) == pytest.approx(1.)
