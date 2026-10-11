# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from moonlabeler.geometry import Geometry, MOON_RADIUS_KM, surface_vectors
from moonlabeler.terrain_rims import trace_crater_rim
from moonlabeler.project import Project, export_svg


def test_terrain_trace_recovers_a_non_circular_crest_and_saved_relief(tmp_path):
    radius = 40.
    def height(lat, lon):
        vectors = surface_vectors(np.asarray(lat), np.asarray(lon))
        distance = np.arccos(np.clip(vectors[:, 0], -1, 1))*MOON_RADIUS_KM
        angle = np.arctan2(vectors[:, 1], vectors[:, 2])
        ridge = radius*(1+.08*np.cos(3*angle))
        return 2*np.exp(-((distance-ridge)/3)**2) - 2/(1+np.exp(np.clip((distance-ridge+5)/2, -100, 100)))
    dem = SimpleNamespace(sample=height, resolution_km=.5, name='Independent synthetic crest')
    feature = dict(id='crest', name='Crest', lat=0., lon=0., diameter=2*radius, kind='Crater, craters')
    rim = trace_crater_rim(dem, feature)
    assert rim is not None and rim['source'] == dem.name
    coordinates = np.asarray(rim['coordinates'])
    vectors = surface_vectors(coordinates[:, 0], coordinates[:, 1])
    distance = np.arccos(np.clip(vectors[:, 0], -1, 1))*MOON_RADIUS_KM
    angle = np.arctan2(vectors[:, 1], vectors[:, 2])
    assert np.max(abs(distance-radius*(1+.08*np.cos(3*angle)))) < 1.2
    assert np.ptp(distance) > 5 and np.allclose(coordinates[0], coordinates[-1])
    g = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]),
                 np.array([1., 0., 0.]), 384400., 'test')
    p = Project(image_path=str(tmp_path/'photo.png'), geometry=g,
                matrix=np.array([[5000., 0., 200.], [0., 5000., 200.]]), terrain_rims={'crest': rim}, font_size=10)
    outline = p.crater_outline(feature, (400, 400))
    assert len(outline[0]) == 129
    # An independently non-circular crest must become a smooth ellipse by
    # default, while the optional contour retains the actual projected shape.
    def conic_error(points):
        points = np.asarray(points)
        center, axes, degrees = cv2.fitEllipse(points[:-1].astype(np.float32))
        angle = np.radians(degrees)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        normalized = ((points-center) @ rotation)/(np.asarray(axes)/2)
        return np.max(abs(np.sum(normalized**2, axis=1)-1))
    assert p.crater_outline_shape == 'ellipse' and conic_error(outline[0]) < 1e-6
    p.crater_outline_shape = 'terrain'
    raw = p.crater_outline(feature, (400, 400))
    assert conic_error(raw[0]) > .05
    assert np.allclose(raw[0], p._project_crater_rim(feature)[0])
    p.save(tmp_path/'contour.moonlabel')
    contour = Project.load(tmp_path/'contour.moonlabel')
    assert contour.crater_outline_shape == 'terrain'
    assert np.allclose(contour.crater_outline(feature, (400, 400)), raw)
    p.crater_outline_shape = 'ellipse'
    p.save(tmp_path/'crest.moonlabel')
    restored = Project.load(tmp_path/'crest.moonlabel')
    assert restored.terrain_rims == p.terrain_rims
    assert np.allclose(restored.crater_outline(feature, (400, 400)), outline)
    export_svg(tmp_path/'crest.svg', np.zeros((400, 400, 3), np.uint8),
               [(feature, [200, 200], [340, 300])], restored)
    tree = ET.parse(tmp_path/'crest.svg')
    path = tree.find('.//{http://www.w3.org/2000/svg}path[@class="crater-outline"]')
    svg_points = np.array([[float(v) for v in pair.split(',')]
                           for pair in path.attrib['d'].replace('M ', '').split(' L ')])
    assert np.allclose(svg_points, outline[0], atol=.00051)


def test_smoothed_ellipse_retains_occulted_limb_arc():
    from moonlabeler.project import _ellipse_outline
    g = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]),
                 np.array([1., 0., 0.]), 384400., 'test')
    # Explicit legacy pixel sizing isolates arc clipping from the modern
    # percentage-font rule that intentionally hides very narrow outlines.
    p = Project(geometry=g, matrix=np.array([[15000., 0., 200.], [0., 15000., 200.]]),
                font_size=1, font_percent=None)
    feature = dict(id='limb', lat=0., lon=89.8, diameter=200., kind='Crater, craters')
    pixels, visible = p._project_crater_rim(feature)
    assert visible.any() and not visible.all()
    smooth = _ellipse_outline(pixels)
    # Shape smoothing must not render the back of a crater across the lunar limb.
    outline = p.crater_outline(feature, (400, 400))
    assert outline and sum(map(len, outline)) == visible.sum()
    assert np.allclose(np.concatenate(outline), smooth[visible])


def test_flat_or_unresolved_terrain_does_not_invent_a_rim():
    dem = SimpleNamespace(sample=lambda lat, lon: np.zeros(np.asarray(lat).shape), resolution_km=2., name='Flat')
    assert trace_crater_rim(dem, dict(lat=0., lon=0., diameter=80.)) is None
    assert trace_crater_rim(dem, dict(lat=0., lon=0., diameter=8.)) is None


def test_physical_small_crater_keeps_short_leader_even_in_a_close_up():
    g = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]),
                 np.array([1., 0., 0.]), 384400., 'test')
    p = Project(geometry=g, matrix=np.array([[14000., 0., 300.], [0., 14000., 300.]]), font_size=10)
    # Large on screen, but only 23 km across: the user's arrowed satellite crater.
    small = dict(id='small', lat=0., lon=0., diameter=23., kind='Satellite Feature')
    large = small | dict(id='large', diameter=50., kind='Crater, craters')
    assert not p.crater_outline(small, (600, 600))
    assert p.crater_outline(large, (600, 600))


def test_optional_dem_download_failure_keeps_verified_crater_registration(monkeypatch, tmp_path):
    from moonlabeler.identification import IdentificationResult
    from moonlabeler.terrain_refinement import refine_crater_identification
    matrix = np.array([[2000., 0., 300.], [0., 2000., 300.]])
    result = IdentificationResult(matrix, [object() for _ in range(7)], 3., 10., 0, coverage=.2)
    def unavailable(cache):
        raise OSError('offline')
    monkeypatch.setattr('moonlabeler.terrain.download_basic_dem', unavailable)
    assert refine_crater_identification(result, np.zeros((600, 600, 3), np.uint8), None, tmp_path, []) is result
