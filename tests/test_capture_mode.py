# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Capture selection constrains future searches without changing saved poses."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from moonlabeler.project import Project


@pytest.mark.parametrize('mode', ['auto', 'direct', 'afocal'])
def test_capture_mode_roundtrip_and_legacy_default(tmp_path, mode):
    path = tmp_path/'mode.moonlabel'
    project = Project(capture_mode=mode)
    project.save(path)
    assert Project.load(path).capture_mode == mode
    data = json.loads(path.read_text(encoding="utf-8"))
    del data['capture_mode']
    path.write_text(json.dumps(data), encoding="utf-8")
    assert Project.load(path).capture_mode == 'auto'


@pytest.mark.parametrize('mode, allowed', [('auto', True), ('direct', False), ('afocal', True)])
def test_selection_reaches_recognition_and_preserves_current_edits(monkeypatch, tmp_path, mode, allowed):
    from PIL import Image
    from moonlabeler import app as module
    from moonlabeler.geometry import Geometry
    application = QApplication.instance() or QApplication([])
    window = module.MainWindow()
    try:
        window.set_image(np.zeros((400, 600, 3), np.uint8))
        geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]),
                            np.array([0., 0., 1.]), np.array([1., 0., 0.]),
                            384400., '2023-05-27T11:51:00+00:00')
        window.project.geometry = geometry
        matrix = np.array([[150., 0., 300.], [0., 150., 200.]])
        window.project.matrix = matrix.copy()
        window.project.labels = {'custom': {'position': [50, 70], 'text': 'my edit'}}
        window.project.identification = {'method': 'previous validated fit',
                                         'lens_distortion': {'center': [300., 200.], 'scale': 300., 'k': .1}}
        window.capture_mode.setCurrentIndex(window.capture_mode.findData(mode))
        assert window.project.geometry is geometry
        assert np.array_equal(window.project.matrix, matrix)
        assert window.project.labels['custom']['position'] == [50, 70]
        assert window.project.identification['lens_distortion']['k'] == .1
        assert window.project.capture_mode == mode

        calls, results = [], []
        def identify(image, actual_geometry, *, allow_eyepiece):
            calls.append(allow_eyepiece)
            assert actual_geometry is geometry
            return 'accepted'
        monkeypatch.setattr(module, 'identify_from_atlas', identify)
        monkeypatch.setattr(module, 'detect_crater_rims', lambda *args: SimpleNamespace(candidates=[]))
        monkeypatch.setattr(window, 'accept_identification', results.append)
        monkeypatch.setattr(window, 'run_background', lambda title, work, success, failure: success(work()))
        window.identify_button.click()
        assert calls == [allowed] and results[0][1] == 'accepted'

        # Loading a project synchronizes the combo without invalidating its pose.
        path = tmp_path/'mode.moonlabel'
        photograph = tmp_path/'new.png'
        Image.new('RGB', (600, 400)).save(photograph)
        window.project.image_path = str(photograph)
        window.project.save(path)
        monkeypatch.setattr(window, 'confirm_discard', lambda: True)
        window.open_project(str(path))
        assert window.capture_mode.currentData() == mode
        assert window.project.labels['custom']['position'] == [50, 70]
        assert np.array_equal(window.project.matrix, matrix)
        assert not window.dirty
        previous_time = window.utc()
        window.open_image(str(photograph))
        assert window.project.capture_mode == window.capture_mode.currentData() == 'auto'
        assert window.utc() == previous_time
        assert window.workspace_tabs.currentIndex() == 0
        assert not window.manual_section_toggle.isChecked()
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('failure', ['limb', 'foreground'])
def test_direct_search_rejects_both_optical_failures_without_fitting(monkeypatch, failure):
    from moonlabeler import atlas, eyepiece
    from moonlabeler.identification import IdentificationError
    matrix = np.array([[1., 0., 0.], [0., 1., 0.]])
    match = SimpleNamespace(matrix=matrix, inliers=100, matches=100, coverage=.5)
    monkeypatch.setattr(atlas, 'render_atlas', lambda g: (None, matrix))
    monkeypatch.setattr(atlas, 'prepare_registration_photo', lambda image: None)
    monkeypatch.setattr(atlas, 'auto_register', lambda *args, **kwargs: match)
    monkeypatch.setattr(atlas, '_refine_atlas_pose', lambda *args: None)
    monkeypatch.setattr(atlas, '_photographed_limb', lambda *args: ([50, 50], 40, 0, 300))
    monkeypatch.setattr(atlas, '_limb_error', lambda *args: 100 if failure == 'limb' else 0)
    def forbidden(*args, **kwargs):
        pytest.fail('Direct capture must not invoke the optical solver')
    monkeypatch.setattr(eyepiece, 'identify_eyepiece', forbidden)
    image = np.full((100, 100, 3), 200, np.uint8)
    with pytest.raises(IdentificationError, match='相机直拍'):
        atlas.identify_from_atlas(image, None, allow_eyepiece=False)


def test_direct_mode_does_not_accept_phone_photo_by_bypassing_limb_validation():
    from moonlabeler.atlas import identify_from_atlas
    from moonlabeler.geometry import compute_geometry
    from moonlabeler.identification import IdentificationError
    from moonlabeler.sources import read_image
    root = Path(__file__).parents[1]
    if not (root/'2305271151.jpg').exists() or not (root/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local photographer image and ephemerides required')
    photo = read_image(root/'2305271151.jpg')
    geometry = compute_geometry(datetime(2023, 5, 27, 11, 51, tzinfo=timezone.utc), root/'.cache/ephemeris')
    with pytest.raises(IdentificationError, match='相机直拍'):
        identify_from_atlas(photo, geometry, allow_eyepiece=False)
