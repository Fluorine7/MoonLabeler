# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Regression checks for application-state failures found in code review."""
import json
import os
import numpy as np
from PIL import Image

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow


def test_invalid_project_keeps_current_photo_labels_and_controls(monkeypatch, tmp_path):
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    monkeypatch.setattr(window, 'error', errors.append)
    try:
        window.open_example()
        previous_project, previous_image = window.project, window.image
        previous_path = window.project_path
        item = window.annotation_items[0]
        item.setPos(120, 180)
        previous_labels = json.loads(json.dumps(window.project.labels))
        path = tmp_path/'invalid.moonlabel'
        window.project.save(path)
        data = json.loads(path.read_text())
        data['style']['font_percent'] = 'bad'
        path.write_text(json.dumps(data))
        monkeypatch.setattr(window, 'confirm_discard', lambda: True)
        window.open_project(str(path))
        assert errors, 'Invalid project was accepted without an error'
        assert window.project is previous_project
        assert window.image is previous_image
        assert window.project_path == previous_path
        assert window.project.labels == previous_labels
        assert not window.rebuilding
        # Controls must still apply to the original editable project.
        window.maximum.setValue(210)
        window.apply_label_settings()
        assert window.project.max_labels == 210
        assert window.project.labels == previous_labels
    finally:
        window.dirty = False
        window.close()


def test_changing_label_limit_keeps_legacy_font_outside_default_ui_range(monkeypatch, tmp_path):
    from moonlabeler.project import Project
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    monkeypatch.setattr(window, 'error', lambda message: (_ for _ in ()).throw(AssertionError(message)))
    photo = tmp_path/'small.png'
    Image.fromarray(np.full((100, 100, 3), 100, np.uint8)).save(photo)
    path = tmp_path/'legacy.moonlabel'
    Project(image_path=str(photo), font_size=80).save(path)
    data = json.loads(path.read_text())
    data['style'].pop('font_percent')
    path.write_text(json.dumps(data))
    try:
        window.open_project(str(path))
        assert window.project.font_size == 80
        assert window.font_size.value() == window.project.font_percent
        window.maximum.setValue(210)
        window.apply_label_settings()
        assert window.project.font_size == 80
        assert window.project.font_percent == 80
    finally:
        window.dirty = False
        window.close()
