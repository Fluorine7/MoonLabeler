# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Run the independent documentation reader against real saved registrations."""
import json
from pathlib import Path
import re

import numpy as np
import pytest

from moonlabeler.geometry import Geometry, surface_vectors, unit
from moonlabeler.map_layers import photo_coordinates
from moonlabeler.project import PROJECT_COORDINATE_SYSTEM, Project


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def reader():
    document = (ROOT/'docs/project-format.md').read_text(encoding='utf-8')
    example = re.search(r'```python\n(.*?)\n```', document, re.S).group(1)
    namespace = {}
    exec(compile(example, 'docs/project-format.md', 'exec'), namespace)
    assert json.loads(re.search(r'```json\n(.*?)\n```', document, re.S).group(1)) == PROJECT_COORDINATE_SYSTEM
    return namespace


def make_project(tmp_path, latitude=4., longitude=-6., *, mirrored=False, k=None):
    observer = surface_vectors([latitude], [longitude])[0]
    north = unit(np.array([0., 0., 1.])-observer[2]*observer)
    right = np.cross(north, observer)
    utc = '2023-06-03T16:26:00+00:00'
    geometry = Geometry(observer, right, north, -observer, 384400., utc)
    matrix = np.array([[780., 180., 1024.], [-130., 830., 900.]])
    if mirrored:
        matrix[:, 0] *= -1
    distortion = {'center': [1000., 920.], 'scale': 1100., 'k': k} if k is not None else None
    return Project(image_path=str(tmp_path/'照片 folder'/'彩月.tif'), utc=utc,
                   geometry=geometry, matrix=matrix, image_size=(2048, 1800),
                   identification={'lens_distortion': distortion},
                   labels={'42': {'position': [400., 500.], 'text': '手工编辑'}})


def test_saved_registration_is_self_describing_and_preserves_old_project_fields(tmp_path, reader):
    project = make_project(tmp_path, mirrored=True, k=.2)
    project.art_style = 'manuscript'
    target = tmp_path/'彩月.moonlabel'
    project.save(target)
    data = reader['read_registration'](target)
    assert data['format'] == 'MoonLabeler' and data['version'] == 2
    assert data['coordinate_system'] == PROJECT_COORDINATE_SYSTEM
    assert data['image_size'] == [2048, 1800]
    assert data['image_path'] == '照片 folder/彩月.tif'
    loaded = Project.load(target)
    assert loaded.image_size == project.image_size
    assert loaded.geometry.to_dict() == project.geometry.to_dict()
    np.testing.assert_array_equal(loaded.matrix, project.matrix)
    assert loaded.labels == project.labels and loaded.identification == project.identification
    assert loaded.art_style == 'manuscript'
    loaded.save(target)
    assert json.loads(target.read_text(encoding='utf-8')) == data


def test_reader_and_application_accept_pre_metadata_projects(tmp_path, reader):
    project = make_project(tmp_path)
    target = tmp_path/'legacy.moonlabel'
    project.save(target)
    data = json.loads(target.read_text(encoding='utf-8'))
    data.pop('image_size')
    data.pop('coordinate_system')
    target.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    loaded = Project.load(target)
    assert loaded.image_size is None
    expected = project.photo_points(project.geometry.project([4.], [-6.])[0])[0]
    assert reader['moon_to_photo'](reader['read_registration'](target), 4., -6.) == pytest.approx(expected)


@pytest.mark.parametrize('view', [(4., -6.), (86., 40.), (-86., -45.), (2., 179.)])
@pytest.mark.parametrize('mirrored', [False, True])
@pytest.mark.parametrize('k', [None, 0., .2, .6])
def test_documented_reader_maps_photo_pixels_back_without_rotation_or_limb_errors(tmp_path, reader, view, mirrored, k):
    project = make_project(tmp_path, *view, mirrored=mirrored, k=k)
    path = tmp_path/'photo.moonlabel'
    project.save(path)
    data = reader['read_registration'](path)
    xs, ys = np.meshgrid(np.linspace(.5, 2047.5, 19), np.linspace(.5, 1799.5, 17))
    pixels = np.column_stack((xs.ravel(), ys.ravel()))
    lat, lon, disk = project.geometry.unproject(photo_coordinates(project, pixels))
    assert disk.any() and not disk.all(), 'Fixture must cover both the Moon and sky'
    for pixel, latitude, longitude, valid in zip(pixels, lat, lon, disk):
        actual = reader['photo_to_sphere'](data, *pixel)
        if not valid:
            assert actual is None
            continue
        np.testing.assert_allclose(actual, (latitude, longitude), atol=1e-6)
        np.testing.assert_allclose(reader['moon_to_photo'](data, *actual), pixel, atol=1e-5)
    # Sun faces away from the photo: coverage must not be confused with daylight.
    assert reader['moon_to_photo'](data, *view) is not None
    assert reader['moon_to_photo'](data, -view[0], view[1]+180) is None
    assert reader['photo_to_sphere'](data, -1, 900) is None


@pytest.mark.parametrize('filename', ['0807-registration.json', '1001-registration.json', '0708-sphere-registration.json'])
def test_documented_projection_matches_saved_real_photo_registrations(tmp_path, reader, filename):
    recorded = json.loads((ROOT/'tests/fixtures'/filename).read_text(encoding='utf-8'))
    geometry = Geometry.from_dict(recorded['geometry'])
    project = Project(image_path='moon.png', utc=geometry.utc, geometry=geometry,
                      matrix=np.array(recorded['matrix']))
    path = tmp_path/'registered.moonlabel'
    project.save(path)
    data = reader['read_registration'](path)
    lat, lon = np.meshgrid(np.linspace(-89, 89, 19), np.linspace(-179, 179, 23))
    lat, lon = lat.ravel(), lon.ravel()
    points, visible, _ = geometry.project(lat, lon)
    pixels = project.photo_points(points)
    for latitude, longitude, pixel, valid in zip(lat, lon, pixels, visible):
        actual = reader['moon_to_photo'](data, latitude, longitude)
        if valid:
            assert actual == pytest.approx(pixel, abs=1e-6)
        else:
            assert actual is None


def test_terrain_height_is_explicit_and_old_relief_projects_remain_terrain(tmp_path, reader):
    project = make_project(tmp_path)
    project.projection_surface = 'terrain'
    path = tmp_path/'terrain.moonlabel'
    project.save(path)
    data = reader['read_registration'](path)
    with pytest.raises(ValueError, match='requires DEM height'):
        reader['moon_to_photo'](data, 55., 40.)
    height = 4.2
    expected = project.photo_points(project.geometry.project([55.], [40.], [height])[0])[0]
    assert reader['moon_to_photo'](data, 55., 40., height) == pytest.approx(expected)
    data.pop('projection_surface')
    data['automatic_recognition']['refinement'] = {'relief_aware': True}
    with pytest.raises(ValueError, match='requires DEM height'):
        reader['moon_to_photo'](data, 55., 40.)


@pytest.mark.parametrize('update', [{'version': 3}, {'version': 2.0}, {'matrix': None}, {'geometry': None},
                                     {'coordinate_system': {'frame': 'IAU_MOON'}}])
def test_example_reader_rejects_unsupported_or_unregistered_data(tmp_path, reader, update):
    path = tmp_path/'bad.moonlabel'
    make_project(tmp_path).save(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    data.update(update)
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        reader['read_registration'](path)
