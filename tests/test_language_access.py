# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Language switching stays reachable when translated toolbar captions overflow."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from moonlabeler import app as app_module, i18n


@pytest.mark.parametrize('width', [1100, 1512])
@pytest.mark.parametrize('language', i18n.LANGUAGES)
@pytest.mark.parametrize('activation', ['click', 'shortcut'])
def test_language_switch_is_visible_and_can_return_to_chinese(tmp_path, monkeypatch, width, language, activation):
    app = QApplication.instance() or QApplication([])
    previous = i18n._language, i18n._explicit
    i18n.set_language(language)
    monkeypatch.setattr(app_module, 'CACHE', tmp_path)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    window = app_module.MainWindow()
    window.resize(width, 860)
    window.show()
    window.activateWindow()
    window.setFocus()
    app.processEvents()
    try:
        action = next(action for action in window.toolbar.actions() if 'Language' in action.text())
        button = window.toolbar.widgetForAction(action)
        assert button.isVisible(), 'The language switch must stay visible when the toolbar overflows'
        assert window.rect().contains(button.mapTo(window, QPoint(0, 0)))
        assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
        selected = []

        def choose_chinese():
            dialog = QApplication.activeModalWidget()
            dialog.combo.setCurrentIndex(dialog.combo.findData(i18n.SIMPLIFIED))
            selected.append(dialog.selected())
            dialog.accept()

        QTimer.singleShot(0, choose_chinese)
        if activation == 'shortcut':
            QTest.keyClick(window, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        else:
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert selected == [i18n.SIMPLIFIED]
        assert window.compute_preferences.value(i18n.PREFERENCE_KEY) == i18n.SIMPLIFIED
    finally:
        window.dirty = False
        window.close()
        i18n._language, i18n._explicit = previous
