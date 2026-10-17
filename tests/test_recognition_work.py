# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Skip unused work without losing the crater or guided fallback evidence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from moonlabeler import app as module
from moonlabeler.craters import CraterCandidate, DetectionResult
from moonlabeler.geometry import Geometry
from moonlabeler.identification import IdentificationResult


@pytest.mark.parametrize('route', ['atlas', 'limb', 'craters', 'guided'])
def test_recognition_only_detects_craters_when_used_and_preserves_review(monkeypatch, route):
    application = QApplication.instance() or QApplication([])
    window = module.MainWindow()
    errors, stages = [], []
    window.error = errors.append
    try:
        window.set_image(np.zeros((400, 600, 3), np.uint8))
        geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                            np.array([0., 0., 1.]), np.array([1., 0., 0.]),
                            384400., '2023-05-27T11:51:00+00:00')
        window.project.geometry = geometry
        monkeypatch.setattr(module, 'compute_geometry', lambda *args: geometry)
        manual = CraterCandidate(123., 234., 15., 12., 0., None, 'manual')
        review = DetectionResult([manual], (0, 0, 600, 400), 1.)
        window.accept_crater_candidates(review)
        fresh = DetectionResult([CraterCandidate(320., 180., 30., 25., 0., None, 'edge-drawing')],
                                (0, 0, 600, 400), 1.)
        def detect(image):
            stages.append('detect')
            return fresh
        monkeypatch.setattr(module, 'detect_crater_rims', detect)
        result = IdentificationResult(np.array([[150., 0., 300.], [0., 150., 200.]]), [],
                                      1., 50., 0, method='test', image_inliers=50)
        def atlas(*args, **kwargs):
            stages.append('atlas')
            if route != 'atlas':
                raise ValueError('no atlas match')
            return result
        def limb(*args, **kwargs):
            stages.append('limb')
            if route != 'limb':
                raise ValueError('no limb match')
            return result
        def craters(candidates, *args, **kwargs):
            stages.append('craters')
            assert candidates is fresh.candidates
            return result
        monkeypatch.setattr(module, 'identify_from_atlas', atlas)
        monkeypatch.setattr(module, 'identify_from_limb', limb)
        monkeypatch.setattr(module, 'identify_from_candidates', craters)
        monkeypatch.setattr(module, 'refine_crater_identification', lambda recognition, *args: recognition)
        if route in ('craters', 'guided'):
            feature = next(f for f in window.catalog if f['name'] == 'Tycho')
            point = geometry.project([feature['lat']], [feature['lon']])[0]
            pixel = (point @ result.matrix[:, :2].T + result.matrix[:, 2])[0].tolist()
            if route == 'guided':
                window.project.anchors = [{'id': feature['id'], 'pixel': pixel, 'enabled': True}]
                def guided(image, actual_geometry, cache, anchors, catalog, candidates):
                    stages.append('guided')
                    assert candidates == [manual, *fresh.candidates]
                    return result
                monkeypatch.setattr(module, 'identify_from_reference_points', guided)
            else:
                result.matches = [SimpleNamespace(candidate_index=0, feature=feature)]
        def synchronous(title, work, success, failure):
            try:
                value = work()
            except ValueError as exc:
                failure(str(exc))
            else:
                success(value)
        monkeypatch.setattr(window, 'run_background', synchronous)
        window.identify_button.click()
        assert not errors
        expected = {'atlas': ['atlas'], 'limb': ['atlas', 'limb'],
                    'craters': ['atlas', 'limb', 'detect', 'craters'],
                    'guided': ['detect', 'guided']}
        assert stages == expected[route]
        if route in ('atlas', 'limb'):
            assert window.crater_result is review
            assert window.crater_candidates == [manual]
            assert window.crater_list.currentRow() == 0
            assert window.project.identification['candidate_count'] is None
        else:
            assert window.crater_candidates == fresh.candidates
            assert window.project.identification['candidate_count'] == 1
        if route == 'craters':
            assert window.project.anchors[0]['pixel'] == [320., 180.]
    finally:
        window.dirty = False
        window.close()
