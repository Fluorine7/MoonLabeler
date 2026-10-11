# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Exercise the review footer through real window sizing and business updates."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, Qt, QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDateTimeEdit

from moonlabeler.app import MainWindow
from moonlabeler.craters import CraterCandidate, DetectionResult


@pytest.fixture
def visible_window():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    application.processEvents()
    yield window, application
    window.dirty = False
    window.close()


@pytest.mark.parametrize('size', [(1100, 720), (1440, 930)])
def test_review_keeps_detection_and_confirmation_reachable(visible_window, size):
    window, application = visible_window
    window.resize(*size)
    window.show_crater_review()

    def check_controls():
        for _ in range(3):
            application.processEvents()
        viewport = window.scroll.viewport()
        top = window.crater_button.mapTo(viewport, QPoint(0, 0)).y()
        assert top >= 0 and top + window.crater_button.height() <= viewport.height()
        assert viewport.height() >= 140, 'The review footer crowds out detection settings'
        assert window.registration_tabs.height() < 230
        panel = window.crater_action_panel
        confirm = window.crater_anchor_button.mapTo(panel, QPoint(0, 0)).y()
        assert confirm >= 0 and confirm + window.crater_anchor_button.height() <= panel.height()

    check_controls()
    result = DetectionResult([CraterCandidate(100+i*20, 100, 15, 12, 0, .8, 'test')
                              for i in range(10)], (0, 0, 500, 500), 1.)
    window.accept_crater_candidates(result)
    window.crater_search.setText('Hadley C')
    check_controls()
    assert window.crater_feature.isVisible()
    # Typing a single matching name still requires an explicit choice.
    assert not window.crater_anchor_button.isEnabled()
    QTest.keyClick(window.crater_search, Qt.Key.Key_Return)
    assert window.crater_anchor_button.isEnabled()


def test_business_search_refresh_shows_and_clears_name_results(visible_window):
    window, application = visible_window
    window.show_crater_review()
    # The catalogue and project-sync paths also invoke this callback directly.
    window.search_crater_features('Hadley C')
    application.processEvents()
    assert window.crater_feature.count() == 1
    assert not window.crater_feature.isHidden()
    assert window.crater_feature.currentRow() == -1
    window.search_crater_features('')
    assert window.crater_feature.count() == 0 and window.crater_feature.isHidden()


def test_compact_time_entry_and_direct_sync_keep_seconds(visible_window):
    window, application = visible_window
    window.capture_time_toggle.setChecked(True)
    window.capture_time.setTime(QTime(12, 34, 56))
    window.sync_capture_time()
    assert window.capture_time_toggle.text() == '具体时间'
    window.capture_time.setFocus()
    window.capture_time.setCurrentSection(QDateTimeEdit.Section.HourSection)
    window.capture_time.setSelectedSection(QDateTimeEdit.Section.HourSection)
    QTest.keyClicks(window.capture_time, '2132')
    assert window.capture_time.time() == QTime(21, 32, 56)
    assert window.utc().strftime('%H:%M:%S') == '21:32:56'
    window.capture_time_toggle.setChecked(False)
    assert '21:32:56' in window.capture_time_toggle.text()
