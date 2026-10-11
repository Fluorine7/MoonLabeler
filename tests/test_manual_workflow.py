# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Exercise the visible manual workflow, including deferred ephemeris work."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from moonlabeler.app import MainWindow
from moonlabeler.registration import transform_points


def select_feature(window, name):
    window.feature_search.setText(name)
    feature = next(f for f in window.catalog if f["name"] == name)
    for row in range(window.feature_list.count()):
        if window.feature_list.item(row).data(Qt.ItemDataRole.UserRole) == feature["id"]:
            window.feature_list.setCurrentRow(row)
            break
    return feature


def test_click_three_points_then_calibrate_computes_geometry_and_shows_labels(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    try:
        assert not window.pick_button.isEnabled() and not window.solve_button.isEnabled()
        window.open_example()
        geometry, truth = window.project.geometry, window.project.matrix.copy()
        window.clear_anchors()
        window.project.geometry = None
        window.show()
        app.processEvents()
        window.fit_canvas()
        calls = []

        def compute(utc, cache, lat, lon):
            calls.append((utc.isoformat(), lat, lon))
            return geometry

        monkeypatch.setattr("moonlabeler.app.compute_geometry", compute)
        # Drive the same callback boundary without downloading or waiting on a thread.
        monkeypatch.setattr(window, "run_background", lambda title, work, success, failure=None: success(work()))
        for i, name in enumerate(("Copernicus", "Plato", "Tycho"), 1):
            feature = select_feature(window, name)
            window.pick_button.click()
            assert window.canvas.picking and window.cancel_pick_button.isVisible()
            assert (feature.get("name_zh") or name) in window.manual_guide.text()
            xy, _, _ = geometry.project([feature["lat"]], [feature["lon"]])
            pixel = transform_points(truth, xy)[0]
            QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.canvas.mapFromScene(QPointF(*pixel)))
            assert len(window.project.anchors) == i
            assert not window.canvas.picking and window.picking_id is None
            assert not window.cancel_pick_button.isVisible()
            assert str(i) in window.anchor_count.text()
            assert window.solve_button.isEnabled() == (i >= 3)
            assert not calls, "Adding reference points must not require ephemerides"
        window.solve_button.click()
        assert not errors
        assert len(calls) == 1 and calls[0] == (geometry.utc, None, None)
        assert window.workspace_tabs.currentIndex() == 1
        assert window.annotation_items
        assert np.max(np.abs(window.project.matrix - truth)) < 3.0  # viewport click quantization
        assert window.project.geometry is geometry
    finally:
        window.dirty = False
        window.close()


def test_changed_selection_and_escape_cannot_add_a_stale_named_point():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.open_example()
        window.clear_anchors()
        window.project.geometry = None
        window.show()
        app.processEvents()
        select_feature(window, "Copernicus")
        window.pick_button.click()
        select_feature(window, "Tycho")
        assert not window.canvas.picking and window.picking_id is None
        window.canvas_point_clicked(500, 500)
        assert not window.project.anchors
        window.pick_button.click()
        QTest.keyClick(window.canvas, Qt.Key.Key_Escape)
        assert not window.canvas.picking and window.picking_id is None
        window.canvas_point_clicked(500, 500)
        assert not window.project.anchors
        # Repicking also works before geometry exists, and replaces the same name.
        feature = select_feature(window, "Tycho")
        window.pick_button.click()
        window.canvas_point_clicked(500, 500)
        window.repick_anchor(0)
        window.canvas_point_clicked(520, 510)
        assert window.project.anchors == [{"id": feature["id"], "pixel": [520, 510], "enabled": True}]
        window.anchor_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        assert "0 个有效" in window.anchor_count.text()
        assert not window.solve_button.isEnabled()
    finally:
        window.dirty = False
        window.close()


def test_geometry_failure_preserves_collected_reference_points(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.open_example()
        window.clear_anchors()
        window.project.geometry = None
        for i, name in enumerate(("Copernicus", "Plato", "Tycho")):
            select_feature(window, name)
            window.pick_button.click()
            window.canvas_point_clicked(300 + i * 100, 500)
        before = list(window.project.anchors)
        errors = []
        window.error = errors.append
        monkeypatch.setattr(window, "run_background", lambda *args, **kwargs: window.error("星历下载失败"))
        window.solve_button.click()
        assert errors == ["星历下载失败"]
        assert window.project.anchors == before and window.project.geometry is None
        assert window.solve_button.isEnabled()
    finally:
        window.dirty = False
        window.close()


def test_registration_failures_reveal_manual_calibration_without_losing_fit(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    try:
        window.open_example()
        matrix = window.project.matrix.copy()
        anchors = list(window.project.anchors)
        window.ui_set_manual_section_expanded(False)
        # Exercise the actual failure callback without rerunning recognition.
        monkeypatch.setattr(window, 'run_background',
                            lambda title, work, success, failure=None: failure('No validated region'))
        window.identify_photo()
        assert window.ui_manual_section_expanded()
        assert window.workspace_tabs.currentIndex() == 0
        assert np.array_equal(window.project.matrix, matrix) and window.project.anchors == anchors
        window.ui_set_manual_section_expanded(False)
        window.nasa_failed('Connection timed out')
        assert window.ui_manual_section_expanded()
        assert errors == ['No validated region', 'Connection timed out']
        window.ui_set_manual_section_expanded(False)
        window.show_manual_points()
        assert window.ui_manual_section_expanded()
    finally:
        window.dirty = False
        window.close()


def test_failure_without_confirmed_points_opens_candidate_detection_before_manual_picking(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    try:
        window.set_image(np.full((500, 600, 3), 50, np.uint8))
        window.show()
        app.processEvents()
        assert not window.ui_manual_section_expanded()
        monkeypatch.setattr(window, 'run_background',
                            lambda title, work, success, failure=None: failure('No validated region'))
        window.identify_button.click()
        app.processEvents()
        assert errors == ['No validated region']
        assert window.registration_tabs.currentWidget() is window.crater_tab
        assert window.ui_manual_section_expanded() and window.crater_action_panel.isVisible()
        assert window.crater_button.isVisible()
        window.crater_finish_button.click()
        app.processEvents()
        assert window.registration_tabs.currentWidget() is window.crater_tab
        assert window.ui_reference_toggle.isChecked()
        assert not window.ui_manual_pick_toggle.isChecked() and window.crater_action_panel.isVisible()
    finally:
        window.dirty = False
        window.close()
