# SPDX-License-Identifier: GPL-3.0-or-later
"""Higher-order afocal calibration must share one reversible photo geometry."""
import json
from pathlib import Path
import numpy as np
import pytest

from moonlabeler.eyepiece import distort_points, distortion_jacobian
from moonlabeler.map_layers import photo_coordinates
from moonlabeler.project import Project


def test_second_radial_term_moves_the_edge_and_uses_its_actual_differential():
    lens = dict(center=[500., 400.], scale=500., k=.2, k2=-.06)
    # At x=900: delta=.8; (k*r²+k2*r⁴)*400 = 41.3696 pixels.
    assert distort_points([[900., 400.]], lens)[0] == pytest.approx([941.3696, 400.])
    jacobian = distortion_jacobian(np.array([[900., 400.]]), lens)[0]
    assert jacobian == pytest.approx(np.diag([1.26112, 1.103424]))


@pytest.mark.parametrize('mirror', [False, True])
def test_second_radial_term_is_inverted_before_the_saved_camera(mirror, tmp_path):
    matrix = np.array([[400.*(-1 if mirror else 1), -100., 500.],
                       [100.*(-1 if mirror else 1), 400., 400.]])
    project = Project(matrix=matrix)
    project.identification['lens_distortion'] = dict(center=[500., 400.], scale=500., k=.2, k2=-.06)
    probes = np.array([[.8, 0.], [.1, -.9], [-.7, .4], [0., 0.]])
    ideal_probe = np.linalg.solve(matrix[:, :2], [400., 0.])
    assert photo_coordinates(project, [[941.3696, 400.]])[0] == pytest.approx(ideal_probe, abs=1e-8)
    pixels = project.photo_points(probes)
    assert photo_coordinates(project, pixels) == pytest.approx(probes, abs=1e-8)
    path = tmp_path/'edge.moonlabel'
    project.save(path)
    loaded = Project.load(path)
    assert loaded.identification['lens_distortion']['k2'] == -.06
    assert loaded.photo_points(probes) == pytest.approx(pixels)
    assert photo_coordinates(loaded, pixels) == pytest.approx(probes, abs=1e-8)


@pytest.mark.parametrize('value', [-1., float('nan'), '0.1', True])
def test_saved_second_radial_term_is_validated(tmp_path, value):
    path = tmp_path/'invalid.moonlabel'
    project = Project()
    project.identification['lens_distortion'] = dict(center=[500., 400.], scale=500., k=.2, k2=-.06)
    project.save(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['automatic_recognition']['lens_distortion']['k2'] = value
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='lens_distortion'):
        Project.load(path)


@pytest.mark.parametrize('k2', [-1e-250, 1e-250])
def test_negligible_second_term_does_not_overflow_the_inverse(k2):
    project = Project(matrix=np.array([[500., 0., 500.], [0., 500., 400.]]))
    project.identification['lens_distortion'] = dict(center=[500., 400.], scale=500., k=.2, k2=k2)
    assert photo_coordinates(project, [[951.2, 400.]])[0] == pytest.approx([.8, 0.], abs=1e-8)


def test_rays_outside_the_injective_optical_field_are_not_folded_back_onto_the_moon():
    project = Project(matrix=np.eye(2, 3))
    project.identification['lens_distortion'] = dict(center=[0., 0.], scale=1., k=.2, k2=-.06)
    assert np.isnan(photo_coordinates(project, [[3., 0.]])).all()


@pytest.mark.parametrize('lens,error', [(None, 6.), (dict(k=.03, scale=500.), 6.), (dict(k=.2, scale=500.), 1.)])
def test_ordinary_successes_do_not_load_terrain_or_prepare_more_photo_features(monkeypatch, lens, error):
    from types import SimpleNamespace
    from moonlabeler import eyepiece_refinement as module
    def forbidden(*args, **kwargs):
        pytest.fail('A normal success must keep its fast path')
    monkeypatch.setattr(module, 'download_basic_dem', forbidden)
    monkeypatch.setattr(module, 'prepare_registration_photo', forbidden)
    result = SimpleNamespace(lens_distortion=lens, refinement={'limb_p95_px': error})
    assert module.refine_eyepiece_edges(None, None, None, None, result, '/unused') is result


def test_cancelled_edge_refinement_does_not_start_a_download(monkeypatch):
    from threading import Event
    from types import SimpleNamespace
    from moonlabeler import eyepiece_refinement as module
    from moonlabeler.tasks import cancellable_task, TaskCancelled
    result = SimpleNamespace(lens_distortion=dict(k=.2, scale=500.), refinement={'limb_p95_px': 6.})
    geometry = SimpleNamespace(observer=np.array([1., 0., 0.]), sun=np.array([0., 1., 0.]))
    monkeypatch.setattr(module, 'download_basic_dem', lambda *args: pytest.fail('Cancelled task downloaded data'))
    event, returned = Event(), []
    with pytest.raises(TaskCancelled):
        with cancellable_task(event):
            event.set()
            module.refine_eyepiece_edges(None, geometry, None, None, result, '/unused')
            returned.append(True)
    assert not returned


def test_rejected_edge_candidate_keeps_the_accepted_pose_and_closes_the_map(monkeypatch):
    from types import SimpleNamespace
    from moonlabeler import eyepiece_refinement as module
    from moonlabeler.identification import IdentificationResult, IdentificationError
    closed = []
    dem = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(module, 'download_basic_dem', lambda *args: '/cached')
    monkeypatch.setattr(module.ElevationMap, 'load', lambda *args: dem)
    def reject(*args):
        raise IdentificationError('目镜校正的分区预测不稳定。')
    monkeypatch.setattr(module, '_refine', reject)
    geometry = SimpleNamespace(observer=np.array([1., 0., 0.]), sun=np.array([0., 1., 0.]))
    accepted = IdentificationResult(np.eye(2, 3), [], 1., 100., 0, projection_geometry=geometry,
        lens_distortion=dict(center=[0., 0.], k=.2, scale=500.), refinement={'limb_p95_px': 6.})
    result = module.refine_eyepiece_edges(None, geometry, None, None, accepted, '/unused')
    assert np.array_equal(result.matrix, accepted.matrix)
    assert result.lens_distortion == accepted.lens_distortion
    assert result.projection_geometry is geometry
    assert result.refinement['edge_refinement']['status'] == 'not_adopted'
    assert 'edge_refinement' not in accepted.refinement
    assert closed == [True]


def test_cached_polar_details_fix_moretus_in_the_identify_button_workflow(monkeypatch):
    from datetime import datetime, timezone
    from PySide6.QtWidgets import QApplication
    from moonlabeler import app as module
    from moonlabeler.geometry import compute_geometry
    from moonlabeler.sources import read_image
    root = Path(__file__).parents[1]
    required = ['2507041216.jpg', '.cache/ephemeris/de421.bsp',
                '.cache/terrain/LDEM_16.LBL', '.cache/terrain/LDEM_16.IMG']
    if not all((root/name).exists() for name in required):
        pytest.skip('Private afocal image and cached ephemerides/LOLA required')
    application = QApplication.instance() or QApplication([])
    window = module.MainWindow()
    results, errors = [], []
    monkeypatch.setattr(module, 'CACHE', root/'.cache')
    try:
        photo = read_image(root/'2507041216.jpg')
        original = photo.copy()
        window.set_image(photo)
        window.project.geometry = compute_geometry(datetime(2025, 7, 4, 12, 16, tzinfo=timezone.utc), root/'.cache/ephemeris')
        monkeypatch.setattr(window, 'accept_identification', results.append)
        monkeypatch.setattr(window, 'error', errors.append)
        monkeypatch.setattr(window, 'run_background', lambda title, work, success, failure=None: success(work()))
        window.identify_photo()
        assert not errors
        result = results[0][1]
        assert result.refinement['edge_refinement']['status'] == 'accepted'
        assert result.refinement['edge_refinement']['limb_validation_points'] >= 100
        assert len(result.refinement['validation_folds']) >= 4
        assert all(f['within_4px'] >= .8 for f in result.refinement['validation_folds'])
        project = Project(geometry=result.projection_geometry, matrix=result.matrix,
                          identification={'lens_distortion': result.lens_distortion})
        moretus = next(f for f in window.catalog if f['name'] == 'Moretus')
        pixel = project.photo_points(project.geometry.project([moretus['lat']], [moretus['lon']])[0])[0]
        assert np.linalg.norm(pixel-[1595., 422.]) < 5.
        assert np.array_equal(photo, original)
    finally:
        window.dirty = False
        window.close()
