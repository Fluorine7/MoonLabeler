# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Choose a detected center and confirm its name through the visible UI."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler.craters import CraterCandidate, DetectionResult


def candidate_window():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.set_image(np.full((600, 600, 3), 40, dtype=np.uint8))
    window.registration_tabs.setCurrentWidget(window.crater_tab)
    window.accept_crater_candidates(DetectionResult(
        [CraterCandidate(350, 300, 29, 29, 0, None, "manual")],
        (0, 0, 600, 600), 1.))
    window.show()
    application.processEvents()
    return window, application


def test_click_single_hadley_result_then_confirm_adds_the_selected_center():
    window, application = candidate_window()
    try:
        window.crater_search.setText("hadley")
        application.processEvents()
        assert window.crater_feature.count() == 1
        target = window.crater_feature.viewport() if hasattr(window.crater_feature, "viewport") else window.crater_feature
        QTest.mouseClick(target, Qt.MouseButton.LeftButton,
                         pos=QPoint(window.crater_feature.width() // 2, 14))
        application.processEvents()
        assert QApplication.activePopupWidget() is None, \
            "Selecting the single search result must not leave a popup blocking confirmation"
        assert window.crater_anchor_button.isEnabled()
        QTest.mouseClick(window.crater_anchor_button, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert len(window.project.anchors) == 1
        anchor = window.project.anchors[0]
        assert window.catalog_by_id[anchor["id"]]["name"] == "Hadley C"
        assert anchor["pixel"] == [350, 300]
    finally:
        window.dirty = False
        window.close()


def test_search_requires_a_choice_and_cannot_keep_a_stale_name():
    window, application = candidate_window()
    try:
        window.crater_search.setText("hadley")
        assert not window.crater_anchor_button.isEnabled()
        QTest.keyClick(window.crater_search, Qt.Key.Key_Return)
        assert window.crater_anchor_button.isEnabled()
        window.crater_search.setText("rima ha")
        assert window.crater_feature.count() == 0
        assert not window.crater_anchor_button.isEnabled()
        window.crater_anchor_button.click()
        assert not window.project.anchors
        window.crater_search.setText("Copernicus")
        assert window.crater_feature.count() > 1
        assert not window.crater_anchor_button.isEnabled()
        QTest.keyClick(window.crater_search, Qt.Key.Key_Return)
        window.crater_list.setCurrentRow(-1)
        assert not window.crater_anchor_button.isEnabled()
    finally:
        window.dirty = False
        window.close()
