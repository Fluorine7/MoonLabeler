# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Independent catalogue patterns, distractors and competing regions."""
import numpy as np
import pytest

from moonlabeler.craters import CraterCandidate
from moonlabeler.identification import identify_from_candidates, IdentificationError
from moonlabeler.geometry import MOON_RADIUS_KM
from moonlabeler.registration import transform_points


class Plane:
    def project(self, latitudes, longitudes):
        points = np.column_stack((longitudes, latitudes))
        return points, np.ones(len(points), bool), np.ones(len(points), bool)


def fixture(mirrored=False):
    points = np.array([[-.38,.10],[-.22,.12],[-.31,.27],[-.40,.24],[-.19,.23],[-.27,.19],[-.35,.18],[-.24,.30],[-.43,.15]])
    diameters = np.array([42,35,18,12,24,9,15,20,11])
    catalog = [dict(id=str(i),name=f'Crater {i}',kind='Crater, craters',lat=p[1],lon=p[0],diameter=float(d)) for i,(p,d) in enumerate(zip(points,diameters))]
    theta = np.radians(17)
    linear = np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]]) @ np.diag([-6500 if mirrored else 6500,6500])
    matrix = np.column_stack((linear,np.array([1300,950])-linear@points.mean(axis=0)))
    pixels = transform_points(matrix,points)
    pixels += np.random.default_rng(47).normal(0,.6,pixels.shape)
    candidates = [CraterCandidate(float(p[0]),float(p[1]),float(d/(2*MOON_RADIUS_KM)*6500),float(d/(2*MOON_RADIUS_KM)*5000),0,None,'edge-drawing') for p,d in zip(pixels,diameters)]
    candidates += [CraterCandidate(100,100,40,30,0,None,'edge-drawing'),CraterCandidate(1400,1100,22,15,0,None,'edge-drawing')]
    return catalog, candidates, matrix


@pytest.mark.parametrize('mirrored',[False,True])
def test_unknown_region_rotation_scale_and_handedness_are_recovered(mirrored):
    catalog,candidates,expected = fixture(mirrored)
    # Add unrelated catalogue entries, without telling the search a region/name.
    rng = np.random.default_rng(123)
    catalog += [dict(id=f'noise{i}',name=f'Unrelated {i}',kind='Crater, craters',lat=float(y),lon=float(x),diameter=float(d)) for i,(x,y,d) in enumerate(rng.uniform([-.6,-.5,8],[.6,.5,80],(80,3)))]
    result = identify_from_candidates(candidates,catalog,Plane(),(1900,2600))
    assert {m.feature['id'] for m in result.matches} == {str(i) for i in range(9)}
    assert result.rms_px < 2
    probes = np.array([[-.3,.2],[-.4,.1]])
    assert np.max(np.linalg.norm(transform_points(result.matrix,probes)-transform_points(expected,probes),axis=1)) < 2


def test_identical_patterns_in_two_regions_are_rejected():
    catalog,candidates,_ = fixture()
    duplicates = [f | dict(id='other'+f['id'],name='Other '+f['name'],lon=f['lon']+.6) for f in catalog]
    with pytest.raises(IdentificationError,match='多个接近'):
        identify_from_candidates(candidates,catalog+duplicates,Plane(),(1900,2600))


def test_too_few_or_unrelated_observations_do_not_produce_names():
    catalog,candidates,_ = fixture()
    with pytest.raises(IdentificationError,match='不足七处'):
        identify_from_candidates(candidates[:6],catalog,Plane(),(1900,2600))
    rng = np.random.default_rng(3)
    unrelated = [CraterCandidate(float(x),float(y),float(r),float(r*.7),0,None,'edge-drawing') for x,y,r in rng.uniform([0,0,10],[1800,1600,120],(30,3))]
    with pytest.raises(IdentificationError):
        identify_from_candidates(unrelated,catalog,Plane(),(1600,1800))


def test_satellite_chain_is_searchable_without_four_independent_named_craters():
    catalog,candidates,expected = fixture()
    for i, feature in enumerate(catalog):
        if i:
            feature['kind'] = 'Satellite Feature'
            feature['name'] = f'Parent {chr(64+i)}'
    result = identify_from_candidates(candidates,catalog,Plane(),(1900,2600))
    assert {m.feature['id'] for m in result.matches} == {str(i) for i in range(9)}
    assert 'satellite' in result.method
    assert result.rms_px < 2
    probes = np.array([[-.3,.2],[-.4,.1]])
    assert np.max(np.linalg.norm(transform_points(result.matrix,probes)-transform_points(expected,probes),axis=1)) < 2


def test_small_fragments_cannot_create_satellite_consensus():
    catalog,candidates,_ = fixture()
    for feature in catalog:
        feature['kind'] = 'Satellite Feature'
    # A perfect but tiny pattern is outweighed by the twenty large observations.
    from dataclasses import replace
    candidates = [replace(candidate, major=candidate.major*.1, minor=candidate.minor*.1) for candidate in candidates]
    for feature in catalog:
        feature['diameter'] *= .1
    rng = np.random.default_rng(124)
    large = [CraterCandidate(float(x),float(y),float(r),float(r*.8),0,None,'edge-drawing')
             for x,y,r in rng.uniform([0,0,30],[2500,1800,120],(20,3))]
    with pytest.raises(IdentificationError):
        identify_from_candidates(candidates+large,catalog,Plane(),(1900,2600))
