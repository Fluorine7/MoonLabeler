# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Exercise crater review through real focus, sizing and business updates."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
import numpy as np
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


def review_candidates(window):
    window.show_crater_review()
    window.accept_crater_candidates(DetectionResult([
        CraterCandidate(918, 881, 32, 26, 0, .8, 'test'),
        CraterCandidate(1100, 1200, 15, 12, 0, .8, 'test'),
    ], (0, 0, 2000, 2112), 1.))


def test_selected_crater_and_name_remain_visible_after_search_and_scroll(visible_window):
    window, application = visible_window
    review_candidates(window)
    window.crater_search.setFocus()
    QTest.keyClicks(window.crater_search, 'hadley')
    QTest.keyClick(window.crater_search, Qt.Key.Key_Return)
    window.scroll.verticalScrollBar().setValue(0)
    application.processEvents()
    assert window.crater_list.currentRow() == 0
    context = getattr(window, 'ui_crater_selection', None)
    assert context is not None, 'Searching a name needs a persistent selected-candidate indicator'
    assert context.isVisible() and '01' in context.text()
    assert 'Hadley C' in window.ui_crater_name.text()
    assert window.crater_anchor_button.isEnabled()
    window.crater_list.setCurrentRow(1)
    assert '02' in context.text()
    assert not window.crater_anchor_button.isEnabled(), 'A new candidate must not inherit the previous name'


def test_review_footer_keeps_context_without_taking_over_the_sidebar(visible_window):
    window, application = visible_window
    window.resize(1100, 720)
    review_candidates(window)
    window.crater_search.setText('Hadley')
    for _ in range(3):
        application.processEvents()
    assert window.crater_action_panel.height() <= 150, 'Only context and confirmation should be pinned'
    assert window.scroll.viewport().height() > 350
    for control in (window.crater_list, window.crater_search, window.crater_feature):
        assert window.crater_tab.isAncestorOf(control), 'Selection and search belong in one scrolling flow'


@pytest.mark.parametrize('size', [(1100, 720), (1440, 930)])
def test_review_keeps_detection_and_confirmation_reachable(visible_window, size):
    window, application = visible_window
    window.resize(*size)
    window.show_crater_review()

    def check_controls():
        for _ in range(3):
            application.processEvents()
        viewport = window.scroll.viewport()
        assert viewport.height() >= 350, 'The footer crowds out selection and search'
        for control in (window.crater_button, window.crater_list, window.crater_search):
            if not control.isVisible():
                continue
            # Scroll the outer page as a user would, without relying on Qt's
            # ensureWidgetVisible (which targets an item view's focus rect).
            position = control.mapTo(window.scroll.widget(), QPoint(0, 0)).y()
            window.scroll.verticalScrollBar().setValue(position-12)
            top = control.mapTo(viewport, QPoint(0, 0)).y()
            assert top >= 0 and top + control.height() <= viewport.height()
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


def test_typing_does_not_reset_the_users_scroll_position(visible_window):
    window, application = visible_window
    window.resize(1100, 720)
    review_candidates(window)
    window.crater_search.setFocus()
    for _ in range(3):
        application.processEvents()
    bar = window.scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    QTest.keyClicks(window.crater_search, 'Hadley C')
    for _ in range(3):
        application.processEvents()
    assert bar.value() == 0, 'Search-result resizing must not recenter the page'
    assert window.crater_action_panel.height() <= 150


def test_confirmation_and_repick_use_the_visible_candidate_name_pair(visible_window):
    import numpy as np
    window, application = visible_window
    window.image = np.zeros((2112, 2000, 3), dtype=np.uint8)
    review_candidates(window)
    window.crater_list.setCurrentRow(1)
    window.crater_search.setText('Hadley C')
    window.scroll.ensureWidgetVisible(window.crater_feature)
    application.processEvents()
    # A single result still needs a real mouse choice, not automatic assignment.
    assert not window.crater_anchor_button.isEnabled()
    QTest.mouseClick(window.crater_feature.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.crater_feature.visualItemRect(window.crater_feature.item(0)).center())
    assert '02' in window.ui_crater_selection.text()
    assert 'Hadley C' in window.ui_crater_name.text()
    window.ui_crater_tools_toggle.click()
    window.crater_repick.click()
    window.canvas_point_clicked(1150, 1210)
    # Repositioning the same crater retains the deliberately chosen name.
    assert window.crater_list.currentRow() == 1
    assert window.crater_anchor_button.isEnabled()
    assert '(1150, 1210)' in window.ui_crater_selection.text()
    QTest.mouseClick(window.crater_anchor_button, Qt.MouseButton.LeftButton)
    fid = next(f['id'] for f in window.catalog if f['name'] == 'Hadley C')
    assert window.project.anchors == [{'id': fid, 'pixel': [1150, 1210], 'enabled': True}]
    confirmed = next(f for f in window.catalog if f['id'] == fid)
    assert '02' in window.crater_status.text()
    assert (confirmed.get('name_zh') or confirmed['name']) in window.crater_status.text()
    assert '（1）' in window.crater_finish_button.text()


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
    assert '12:34:56' in window.capture_time_toggle.text()
    window.ui_hour.setFocus()
    QTest.keyClicks(window.ui_hour, '21')
    assert window.ui_minute.hasFocus()
    QTest.keyClicks(window.ui_minute, '32')
    assert window.capture_time.time() == QTime(21, 32, 56)
    assert window.utc().strftime('%H:%M:%S') == '21:32:56'
    window.capture_time_toggle.setChecked(False)
    assert '21:32:56' in window.capture_time_toggle.text()


def test_reference_action_is_reachable_after_detection_in_small_window(visible_window):
    window, application = visible_window
    window.resize(1100, 720)
    window.set_image(np.zeros((2112, 2000, 3), np.uint8))
    review_candidates(window)
    window.crater_search.setText('Hadley C')
    window.crater_feature.setCurrentRow(0)
    window.crater_anchor_button.click()
    for _ in range(3):
        application.processEvents()
    window.crater_finish_button.click()
    for _ in range(4):
        application.processEvents()
    button = window.guided_identify_button
    assert button.isEnabled()
    top = button.mapTo(window.scroll.viewport(), QPoint(0, 0)).y()
    assert 0 <= top and top + button.height() <= window.scroll.viewport().height()
    assert window.ui_reference_toggle.isChecked()
    assert not window.ui_manual_pick_toggle.isChecked()
