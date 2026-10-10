# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
import numpy as np
from moonlabeler.geometry import Geometry
from moonlabeler.registration import transform_points, fit_similarity
from moonlabeler.pose_refinement import refine_view, refine_camera


def scene():
    g = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                 np.array([0., 0., 1.]), np.array([1., 0., 0.]), 390000., '2025-09-14T15:00:00+00:00')
    matrix = np.array([[3000., 0., 600.], [0., 3000., 2700.]])
    x, y = np.meshgrid(np.linspace(100, 1100, 12), np.linspace(150, 850, 12))
    source = np.column_stack((x.ravel(), y.ravel()))
    xy = (source-matrix[:, 2])/3000
    lat, lon, visible = g.unproject(xy)
    assert visible.all()
    return g, matrix, source, lat, lon


def test_view_refinement_recovers_independent_projection_and_held_out_points():
    g, matrix, source, lat, lon = scene()
    observer = np.array([1., np.tan(np.radians(.4)), np.tan(np.radians(-.25))])
    observer /= np.linalg.norm(observer)
    north = np.array([0., 0., 1.])-observer[2]*observer
    north /= np.linalg.norm(north)
    changed = Geometry(observer, np.cross(north, observer), north, g.sun, g.distance_km, g.utc)
    xy = changed.project(lat, lon)[0]
    truth, _ = fit_similarity(xy, source)
    target = transform_points(truth, xy)
    target += np.random.default_rng(52).normal(0, .12, target.shape)
    result = refine_view(g, matrix, source, target, (1000, 1200))
    assert result is not None
    assert np.allclose(result.details['view_offset_deg'], [.4, -.25], atol=.035)
    assert result.details['validation_after_px'] < result.details['validation_before_px']*.3
    check_lat, check_lon = lat[::7]+.15, lon[::7]+.15
    expected = transform_points(truth, changed.project(check_lat, check_lon)[0])
    actual = transform_points(result.matrix, result.geometry.project(check_lat, check_lon)[0])
    assert np.max(np.linalg.norm(actual-expected, axis=1)) < .3


def test_no_direction_change_does_not_overfit_noise():
    g, matrix, source, lat, lon = scene()
    target = source + np.random.default_rng(72).normal(0, .25, source.shape)
    assert refine_view(g, matrix, source, target, (1000, 1200)) is None


def test_clustered_points_cannot_certify_whole_photo():
    g, matrix, source, lat, lon = scene()
    source = source*.15+[300, 300]
    assert refine_view(g, matrix, source, source+[2, 1], (1000, 1200)) is None


def test_incompatible_local_warp_fails_spatial_validation():
    g, matrix, source, lat, lon = scene()
    target = source.copy()
    target[source[:, 0] < 400] += [7, -5]
    target[source[:, 1] > 700] += [-5, 8]
    assert refine_view(g, matrix, source, target, (1000, 1200)) is None


def test_camera_alignment_recovers_small_bias_at_independent_points():
    g, matrix, source, lat, lon = scene()
    angle = np.radians(.3)
    camera = 1.004*np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    target = source@camera.T + [8., -5.]
    target += np.random.default_rng(11).normal(0, .15, target.shape)
    result = refine_camera(g, matrix, source, target, (1000, 1200))
    assert result is not None
    assert result.geometry is g  # Camera fitting cannot invent libration.
    assert result.details['validation_after_px'] < .3
    probes = np.array([[190., 220.], [850., 650.], [470., 830.]])
    inverse = np.linalg.inv(np.vstack((matrix, [0., 0., 1.])))[:2]
    actual = transform_points(result.matrix, transform_points(inverse, probes))
    assert np.max(np.linalg.norm(actual-(probes@camera.T+[8., -5.]), axis=1)) < .1


def test_camera_alignment_rejects_noise_clusters_and_excessive_correction():
    g, matrix, source, lat, lon = scene()
    assert refine_camera(g, matrix, source, source + np.random.default_rng(17).normal(0, .15, source.shape), (1000, 1200)) is None
    cluster = source*.1 + [400, 300]
    assert refine_camera(g, matrix, cluster, cluster + [7, -4], (1000, 1200)) is None
    assert refine_camera(g, matrix, source, source + [60, 40], (1000, 1200)) is None


def test_camera_alignment_rejects_a_better_average_with_a_worse_region():
    g, matrix, source, lat, lon = scene()
    target = source + [12., -7.]
    target[source[:, 0] < 400] = source[source[:, 0] < 400]
    assert refine_camera(g, matrix, source, target, (1000, 1200)) is None
