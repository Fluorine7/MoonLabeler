# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from types import SimpleNamespace
import numpy as np
import pytest
from moonlabeler.geometry import Geometry, MOON_RADIUS_KM
from moonlabeler.terrain_view import TerrainView
from moonlabeler.pose_refinement import shifted_geometry


@pytest.mark.parametrize('height', [-4., 0., 3.])
def test_relief_intersection_roundtrips_an_independent_constant_radius(height):
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                        np.array([0., 0., 1.]), np.array([1., 0., 0.]), 384400., 'test')
    dem = SimpleNamespace(sample=lambda lat, lon: np.full(np.broadcast(lat, lon).shape, height))
    view = TerrainView.from_geometry(geometry, dem)
    lat, lon = np.meshgrid(np.linspace(-65, 65, 13), np.linspace(-35, 35, 11))
    lat, lon = lat.ravel(), lon.ravel()
    v = np.column_stack((np.cos(np.radians(lat))*np.cos(np.radians(lon)),
                         np.cos(np.radians(lat))*np.sin(np.radians(lon)), np.sin(np.radians(lat))))
    s = 1+height/MOON_RADIUS_KM
    expected = s*v[:, [1, 2]]*[1, -1]/(1-s*MOON_RADIUS_KM/384400*v[:, 0])[:, None]
    pixels, visible, _ = view.project(lat, lon)
    assert np.allclose(pixels, expected, atol=1e-12) and visible.all()
    actual_lat, actual_lon, valid = view.unproject(expected)
    assert valid.all()
    assert np.max(abs(actual_lat-lat)) < .0002
    assert np.max(abs(actual_lon-lon)) < .0002
    # The mismatch between a sphere and a nonzero-height surface is real.
    if height:
        flat_lat, flat_lon, _ = geometry.unproject(expected)
        assert np.max(abs(flat_lat-lat)) > .1
    shifted = shifted_geometry(view, [.1, -.2])
    assert isinstance(shifted, TerrainView) and shifted.dem is dem


def test_relief_intersection_rejects_off_surface_and_missing_dem():
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                        np.array([0., 0., 1.]), np.array([1., 0., 0.]), 384400., 'test')
    view = TerrainView.from_geometry(geometry, SimpleNamespace(sample=lambda lat, lon: np.full(np.broadcast(lat, lon).shape, np.nan)))
    lat, lon, visible = view.unproject(np.array([[0., 0.], [1.1, 0.], [np.nan, 0.]]))
    assert not visible.any() and np.isnan(lat).all() and np.isnan(lon).all()
