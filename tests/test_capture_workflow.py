# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Capture entry and assisted registration must retain the user's workflow."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import cv2
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from moonlabeler.app import MainWindow


def test_guided_failure_keeps_candidate_review_and_the_confirmed_point(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.set_image(np.zeros((2112, 2000, 3), np.uint8))
        window.show()
        feature = next(f for f in window.catalog if f['name'] == 'Hadley C')
        window.picking_id = feature['id']
        window.add_anchor(918, 881)
        window.show_crater_review()
        errors = []
        window.error = errors.append
        monkeypatch.setattr(window, 'run_background',
                            lambda title, work, success, failure=None: failure('参考点附近未找到通过验证的匹配'))
        window.identify_button.click()
        app.processEvents()
        assert errors and window.project.anchors[0]['id'] == feature['id']
        assert window.registration_tabs.currentWidget() is window.crater_tab, 'A failed match must not change input modes'
    finally:
        window.dirty = False
        window.close()


def test_capture_uses_separate_date_and_time_inputs():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.date.setDateTime(QDateTime.fromString('2026-10-10T21:30:56Z', Qt.DateFormat.ISODate))
        assert all(hasattr(window, name) for name in ('ui_year', 'ui_month', 'ui_day', 'ui_hour', 'ui_minute'))
        assert window.ui_year.text() == '2026'
        assert window.ui_month.text() == '10' and window.ui_day.text() == '10'
        assert window.ui_hour.text() == '21' and window.ui_minute.text() == '30'
    finally:
        window.dirty = False
        window.close()


def test_typing_advances_between_fields_and_preserves_saved_seconds():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.date.setDateTime(QDateTime.fromString('2026-10-10T12:34:56Z', Qt.DateFormat.ISODate))
        window.show()
        window.capture_time_toggle.setChecked(True)
        app.processEvents()
        window.ui_year.setFocus()
        QTest.keyClicks(window.ui_year, '2024')
        assert window.ui_month.hasFocus()
        QTest.keyClicks(window.ui_month, '02')
        assert window.ui_day.hasFocus()
        QTest.keyClicks(window.ui_day, '29')
        assert window.ui_hour.hasFocus()
        QTest.keyClicks(window.ui_hour, '21')
        assert window.ui_minute.hasFocus()
        QTest.keyClicks(window.ui_minute, '32')
        assert window.utc().isoformat() == '2024-02-29T21:32:56+00:00'
        # A non-leap-year February 29 must not silently become another date.
        window.ui_year.setFocus()
        QTest.keyClicks(window.ui_year, '2025')
        assert window.ui_capture_error.isVisible()
        assert window.date.date().year() == 2024
        QTest.keyClicks(window.ui_month, '03')
        assert window.utc().isoformat() == '2025-03-29T21:32:56+00:00'
        assert window.ui_capture_error.isHidden()
    finally:
        window.dirty = False
        window.close()


def test_new_photo_returns_to_calibration_collapses_assistance_and_keeps_timestamp(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.date.setDateTime(QDateTime.fromString('2026-08-04T21:30:56Z', Qt.DateFormat.ISODate))
        window.set_image(np.zeros((400, 400, 3), np.uint8))
        window.show()
        window.show_crater_review()
        for toggle in (window.ui_reference_toggle, window.ui_manual_pick_toggle,
                       window.ui_crater_tools_toggle, window.crater_settings_toggle):
            toggle.setChecked(True)
        window.workspace_tabs.setCurrentIndex(1)
        path = tmp_path/'new-photo.png'
        assert cv2.imwrite(str(path), np.zeros((500, 600, 3), np.uint8))
        window.dirty = False
        window.open_image(str(path))
        app.processEvents()
        assert window.workspace_tabs.currentIndex() == 0
        assert window.registration_tabs.currentWidget() is window.crater_tab
        assert all(not toggle.isChecked() for toggle in (
            window.manual_section_toggle, window.ui_reference_toggle,
            window.ui_manual_pick_toggle, window.ui_crater_tools_toggle, window.crater_settings_toggle))
        assert window.scroll.verticalScrollBar().value() == 0
        assert window.utc().isoformat() == '2026-08-04T21:30:56+00:00'
        assert window.project.utc == window.utc().isoformat()
        assert window.ui_hour.text() == '21' and window.ui_minute.text() == '30'
        assert not window.crater_action_panel.isVisible()
    finally:
        window.dirty = False
        window.close()


def test_reference_points_share_the_candidate_page_and_manual_picking_is_a_fold():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.set_image(np.zeros((400, 400, 3), np.uint8))
        window.show()
        window.show_manual_points()
        app.processEvents()
        assert window.registration_tabs.count() == 1
        assert window.registration_tabs.currentWidget() is window.crater_tab
        assert window.ui_reference_toggle.isChecked()
        assert window.crater_tab.isAncestorOf(window.anchor_table)
        assert window.ui_manual_pick_block.isAncestorOf(window.feature_search)
        assert not window.ui_manual_pick_toggle.isChecked()
    finally:
        window.dirty = False
        window.close()


def test_incomplete_or_invalid_date_cannot_start_registration(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    try:
        window.set_image(np.zeros((400, 400, 3), np.uint8))
        window.date.setDateTime(QDateTime.fromString('2026-10-10T15:00:00Z', Qt.DateFormat.ISODate))
        started = []
        monkeypatch.setattr(window, 'run_background', lambda *args, **kwargs: started.append(args))
        window.ui_month.setText('02')
        window.ui_day.setText('31')
        window.identify_button.click()
        assert errors and not started
        window.ui_year.setText('202')
        window.calculate_geometry()
        assert len(errors) == 2 and not started
        assert window.utc().isoformat() == '2026-10-10T15:00:00+00:00'
    finally:
        window.dirty = False
        window.close()
