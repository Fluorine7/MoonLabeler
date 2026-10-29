# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Language switching stays reachable when translated toolbar captions overflow."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtWidgets import QToolButton
from time import monotonic
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
        action = window.ui_language_action
        button = window.settings_toolbar.widgetForAction(action)
        assert button.isVisible(), 'The language switch must stay visible when the toolbar overflows'
        assert button.mapTo(window, button.rect().center()).x() > window.width()/2
        assert window.toolbar.geometry().right() < window.settings_toolbar.geometry().left()
        settings = window.settings_toolbar.actions()
        assert [item.text() for item in settings] == [i18n.tr(text) for text in
            ('打开示例', '计算设置', '界面语言 / Language', '帮助', '致谢')]
        assert all(window.settings_toolbar.widgetForAction(item).isVisible() for item in settings)
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


def test_narrow_project_toolbar_expands_to_reveal_exports_and_preview_toggles(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    previous = i18n._language, i18n._explicit
    i18n.set_language(i18n.ENGLISH)
    monkeypatch.setattr(app_module, 'CACHE', tmp_path)
    window = app_module.MainWindow()
    window.resize(1100, 860)
    window.show()
    app.processEvents()
    try:
        extension = window.toolbar.findChild(QToolButton, 'qt_toolbar_ext_button')
        assert extension.isVisible()
        QTest.mouseClick(extension, Qt.MouseButton.LeftButton)
        deadline = monotonic()+2
        while not window.show_mask.isVisible() and monotonic() < deadline:
            QTest.qWait(10)
        assert window.show_annotations.isVisible() and window.show_mask.isVisible()
        for action in window.actions:
            if action.text() in ('Export PNG', 'Export SVG', 'Fit to window', '+', '−'):
                assert window.toolbar.widgetForAction(action).isVisible()
        language = window.settings_toolbar.widgetForAction(window.ui_language_action)
        assert language.isVisible()
        QTest.mouseClick(window.show_mask, Qt.MouseButton.LeftButton)
        assert window.show_mask.isChecked()
    finally:
        window.dirty = False
        window.close()
        i18n._language, i18n._explicit = previous
