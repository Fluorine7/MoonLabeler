# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Reference-point priors must still require independent image evidence."""
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QDateTime, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler import __version__
from moonlabeler.geometry import Geometry
from moonlabeler.identification import IdentificationError
from moonlabeler.project import Project
from moonlabeler.registration import transform_points


def test_manual_point_enables_guided_action_but_does_not_enable_a_full_manual_fit():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert f'MoonLabeler {__version__}' in window.windowTitle()
        assert '©️Fluorine Zhu（正七价的氟离子）' in window.windowTitle()
        window.set_image(np.full((600, 600, 3), 40, np.uint8))
        feature = next(f for f in window.catalog if f['name'] == 'Hadley C')
        window.picking_id = feature['id']
        window.add_anchor(350, 300)
        assert window.guided_identify_button.isEnabled()
        assert not window.solve_button.isEnabled()
        assert '自动' in window.manual_guide.text()
        window.resize(1280, 800)
        window.show()
        application.processEvents()
        window.show_manual_points()
        application.processEvents()
        button = window.guided_identify_button
        rect = QRect(button.mapTo(window.scroll.viewport(), QPoint(0, 0)), button.size())
        assert button.isVisible() and window.scroll.viewport().rect().contains(rect)
        window.anchor_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        assert not window.guided_identify_button.isEnabled()
        window.project.anchors[0].update(enabled=True, source='automatic')
        window.update_manual_guide()
        assert not window.guided_identify_button.isEnabled()
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('mirrored', [False, True])
def test_one_point_guides_real_sift_and_dense_validation(monkeypatch, tmp_path, mirrored):
    import moonlabeler.guided_identification as guided
    rng = np.random.default_rng(18)
    reference = cv2.GaussianBlur(rng.integers(0, 256, (400, 400), np.uint8), (0, 0), .8)
    photograph = reference[80:320, 80:320].copy()
    if mirrored:
        photograph = cv2.flip(photograph, 1)
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                        np.array([0., 0., 1.]), np.array([1., 0., 0.]), 400000., '')
    feature = dict(id='known', name='Known crater', kind='Crater, craters', lat=0., lon=0., diameter=10.)
    anchor = dict(id='known', pixel=[119 if mirrored else 120, 120], enabled=True)
    matrices = []
    def render(dem, view, matrix, shape):
        matrices.append(matrix.copy())
        return reference
    monkeypatch.setattr(guided, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(guided.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guided, 'render_local_reference', render)
    result = guided.identify_from_reference_points(photograph, geometry, tmp_path, [anchor], [feature],
                                                  reference_size=400, refine=False)
    expected = matrices[0].copy()
    expected[:, 2] -= [80, 80]
    if mirrored:
        expected[0] = -expected[0]
        expected[0, 2] += 239
    probes = np.array([[-.01, -.02], [.02, .01], [0., 0.]])
    assert np.max(np.linalg.norm(transform_points(result.matrix, probes)-transform_points(expected, probes), axis=1)) < 1
    assert result.image_inliers >= 24 and result.coverage > .1
    assert result.reference_points['reference_ids'] == ['known']
    assert result.reference_points['reference_errors_px'][0] < 1
    assert len(matrices) == 1, 'A validated local result must not trigger more renders'
    assert not result.matches  # Image correspondences are not additional named crater centers.


def test_wrong_reference_point_rejects_even_an_image_match(monkeypatch, tmp_path):
    import moonlabeler.guided_identification as guided
    from moonlabeler.registration import MatchResult
    geometry = SimpleNamespace(project=lambda lat, lon: (np.zeros((1, 2)), np.ones(1, bool), np.ones(1, bool)))
    feature = dict(id='known', name='Known crater', kind='Crater, craters', lat=0., lon=0., diameter=10.)
    monkeypatch.setattr(guided, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(guided.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guided, 'render_local_reference', lambda *args: np.full((400, 400), 40, np.uint8))
    monkeypatch.setattr(guided, 'registration_candidates', lambda *args, **kwargs:
                        [MatchResult(np.array([[1., 0., 0.], [0., 1., 0.]]), 80, 90, 1., .6, False)])
    monkeypatch.setattr(guided, 'terrain_agreement', lambda *args, **kwargs: (.95, .95))
    with pytest.raises(IdentificationError, match='参考点'):
        guided.identify_from_reference_points(np.full((240, 240), 40, np.uint8), geometry, tmp_path,
                                              [dict(id='known', pixel=[30, 30])], [feature],
                                              reference_size=400, refine=False)


@pytest.mark.parametrize('mirrored', [False, True])
def test_two_points_guide_a_pose_with_real_image_evidence(monkeypatch, tmp_path, mirrored):
    import moonlabeler.guided_identification as guided
    rng = np.random.default_rng(27)
    base = cv2.GaussianBlur(rng.integers(0, 256, (600, 600), np.uint8), (0, 0), .7)
    photograph = base[180:420, 180:420].copy()
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                        np.array([0., 0., 1.]), np.array([1., 0., 0.]), 400000., '')
    features = [dict(id='a', name='Crater A', kind='Crater, craters', lat=1., lon=-1., diameter=10.),
                dict(id='b', name='Crater B', kind='Crater, craters', lat=-1., lon=1., diameter=10.)]
    basis = np.array([[2000., 0., 300.], [0., 2000., 300.]])
    truth = basis.copy()
    truth[:, 2] -= 180
    if mirrored:
        photograph = cv2.flip(photograph, 1)
        truth[0] = -truth[0]
        truth[0, 2] += 239
    points, _, _ = geometry.project([f['lat'] for f in features], [f['lon'] for f in features])
    anchors = [dict(id=f['id'], pixel=p.tolist()) for f, p in zip(features, transform_points(truth, points))]
    def render(dem, view, matrix, shape):
        warp = (np.vstack((matrix, [0, 0, 1])) @ np.linalg.inv(np.vstack((basis, [0, 0, 1]))))[:2]
        return cv2.warpAffine(base, warp, (shape[1], shape[0]))
    monkeypatch.setattr(guided, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(guided.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guided, 'render_local_reference', render)
    result = guided.identify_from_reference_points(photograph, geometry, tmp_path, anchors, features,
                                                  reference_size=400, refine=False)
    probes = np.array([[0., 0.], [.02, .03], [-.04, .02]])
    assert np.max(np.linalg.norm(transform_points(result.matrix, probes)-transform_points(truth, probes), axis=1)) < 2
    assert result.image_inliers >= 24
    assert result.reference_points['reference_ids'] == ['a', 'b']
    assert max(result.reference_points['reference_errors_px']) < 2


def test_one_point_cannot_resolve_two_equally_supported_mirror_poses(monkeypatch, tmp_path):
    import moonlabeler.guided_identification as guided
    from moonlabeler.identification import AmbiguousIdentificationError
    from moonlabeler.registration import MatchResult
    geometry = SimpleNamespace(project=lambda lat, lon: (np.zeros((1, 2)), np.ones(1, bool), np.ones(1, bool)))
    feature = dict(id='known', name='Known crater', kind='Crater, craters', lat=0., lon=0., diameter=10.)
    monkeypatch.setattr(guided, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(guided.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guided, 'render_local_reference', lambda *args: np.full((400, 400), 40, np.uint8))
    monkeypatch.setattr(guided, 'registration_candidates', lambda *args, **kwargs:
                        [MatchResult(np.array([[1., 0., -80.], [0., 1., -80.]]), 80, 90, 1., .6, False),
                         MatchResult(np.array([[-1., 0., 319.], [0., 1., -80.]]), 79, 90, 1., .6, True)])
    monkeypatch.setattr(guided, 'terrain_agreement', lambda *args, **kwargs: (.95, .95))
    with pytest.raises(AmbiguousIdentificationError, match='再确认'):
        guided.identify_from_reference_points(np.full((240, 240), 40, np.uint8), geometry, tmp_path,
                                              [dict(id='known', pixel=[120, 120])], [feature],
                                              reference_size=400, refine=False)


def test_confirmed_points_do_not_certify_a_featureless_photo(monkeypatch, tmp_path):
    import moonlabeler.guided_identification as guided
    geometry = SimpleNamespace(project=lambda lat, lon: (np.zeros((1, 2)), np.ones(1, bool), np.ones(1, bool)))
    feature = dict(id='known', name='Known crater', kind='Crater, craters', lat=0., lon=0., diameter=10.)
    monkeypatch.setattr(guided, 'download_basic_dem', lambda cache: tmp_path/'test.lbl')
    monkeypatch.setattr(guided.ElevationMap, 'load', lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guided, 'render_local_reference', lambda *args: np.full((400, 400), 40, np.uint8))
    with pytest.raises(IdentificationError, match='未找到'):
        guided.identify_from_reference_points(np.full((240, 240), 40, np.uint8), geometry, tmp_path,
                                              [dict(id='known', pixel=[120, 120])], [feature],
                                              reference_size=400, refine=False)


def test_guided_failure_keeps_confirmed_points_and_existing_registration(monkeypatch):
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    try:
        window.open_example()
        original_anchors = [dict(a, pixel=list(a['pixel'])) for a in window.project.anchors]
        original_matrix = window.project.matrix.copy()
        assert window.manual_reference_points()
        monkeypatch.setattr(window, 'run_background',
                            lambda title, work, success, failure=None: failure('参考点附近未找到可靠匹配'))
        window.guided_identify_button.click()
        assert errors == ['参考点附近未找到可靠匹配']
        assert window.project.anchors == original_anchors
        assert np.array_equal(window.project.matrix, original_matrix)
        assert window.guided_identify_button.isEnabled() and window.ui_manual_section_expanded()
    finally:
        window.dirty = False
        window.close()


def test_confirmed_hadley_c_candidate_guides_local_photo(monkeypatch, tmp_path):
    from moonlabeler.craters import CraterCandidate, DetectionResult
    root = Path(__file__).parents[1]
    if not (root/'0804-2.jpg').exists() or not (root/'.cache/terrain/LDEM_16.IMG').exists() or not (root/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local photograph and reference caches required')
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    def run_work(title, work, success, failure=None):
        try:
            result = work()
        except ValueError as exc:
            (failure or window.error)(str(exc))
        else:
            success(result)
    monkeypatch.setattr(window, 'run_background', run_work)
    # Guided retrieval should precede expensive blind global searches.
    def unexpected(*args, **kwargs):
        raise AssertionError('A confirmed point must be used before blind search')
    monkeypatch.setattr('moonlabeler.app.identify_from_atlas', unexpected)
    try:
        window.open_image(str(root/'0804-2.jpg'))
        window.date.setDateTime(QDateTime.fromString('2026-08-04T21:30:00Z', Qt.DateFormat.ISODate))
        feature = next(f for f in window.catalog if f['name'] == 'Hadley C')
        # Replay the candidate the user confirmed, then follow the helper's
        # return-to-points action. Detection accuracy is tested separately.
        window.show_crater_review()
        window.accept_crater_candidates(DetectionResult([
            CraterCandidate(918., 881., 29., 29., 0., None, 'hough'),
        ], (0, 0, 2000, 2112), 1.))
        window.crater_search.setText('Hadley C')
        window.crater_feature.setCurrentRow(0)
        window.crater_anchor_button.click()
        window.crater_finish_button.click()
        assert window.registration_tabs.currentWidget() is window.manual_tab
        assert window.guided_identify_button.isEnabled() and not window.solve_button.isEnabled()
        original = [a.copy() for a in window.project.anchors]
        window.guided_identify_button.click()
        assert not errors, errors
        assert window.project.matrix is not None and window.annotation_items
        assert 'reference-point' in window.project.identification['method']
        assert window.project.identification['reference_points']['reference_ids'] == [feature['id']]
        assert window.project.anchors == original
        item = next(item for item in window.annotation_items if item.feature['name'] == 'Hadley C')
        assert np.linalg.norm([item.anchor.x()-918, item.anchor.y()-881]) < 24
        assert any(item.feature['name'] == 'Rima Hadley' for item in window.annotation_items)
        assert window.anchor_table.item(0, 2).text() != '—'
        saved = tmp_path/'guided.moonlabel'
        window.project.save(saved)
        restored = Project.load(saved)
        assert restored.identification == window.project.identification
        assert restored.anchors == original and np.array_equal(restored.matrix, window.project.matrix)
        if os.environ.get('MOONLABELER_TEST_PREVIEW'):
            window.resize(1280, 800)
            window.show()
            application.processEvents()
            window.fit_canvas()
            application.processEvents()
            window.grab().save(os.environ['MOONLABELER_TEST_PREVIEW'])
    finally:
        window.dirty = False
        window.close()
