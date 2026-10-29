# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""The real non-native colour picker and discoverable language action."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QAbstractButton, QColorDialog
from moonlabeler import i18n
from moonlabeler.app import MainWindow
from moonlabeler.ui.color import ColorDialog


@pytest.mark.parametrize('language,basic,confirm', [
    ('zh-CN', '基本颜色', '确定'), ('zh-TW', '基本顏色', '確定'), ('en', 'Basic colours', 'OK'),
])
def test_color_dialog_and_language_entry(tmp_path, monkeypatch, language, basic, confirm):
    app = QApplication.instance() or QApplication([])
    old = i18n._language, i18n._explicit
    i18n.set_language(language)
    from moonlabeler import app as app_module
    monkeypatch.setattr(app_module, 'CACHE', tmp_path)
    dialog, win = ColorDialog('#abcdef'), MainWindow()
    try:
        assert dialog.testOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        buttons = [button.text() for button in dialog.findChildren(QAbstractButton)]
        assert basic in labels and confirm in buttons
        assert dialog.currentColor().name() == '#abcdef'
        assert '&Basic colors' not in labels and '&Pick Screen Color' not in buttons
        actions = [action for action in win.toolbar.actions() if 'Language' in action.text()]
        assert len(actions) == 1 and actions[0].isEnabled()
    finally:
        dialog.close()
        win.dirty = False
        win.close()
        i18n._language, i18n._explicit = old
