# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Traditional Chinese interface: widget texts convert, project values do not."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from moonlabeler import i18n, zh_variant
from moonlabeler.project import LANGUAGE_CHOICES

pytestmark = pytest.mark.skipif(not zh_variant.available(), reason="OpenCC port not installed")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def traditional_window(app):
    from moonlabeler.app import MainWindow
    previous = i18n.current_language()
    i18n.set_language(i18n.TRADITIONAL)
    window = MainWindow()
    try:
        yield window
    finally:
        window.close()
        i18n.set_language(previous)


def test_widgets_show_traditional_text(traditional_window):
    window = traditional_window
    assert "月面照片標註" in window.windowTitle()
    assert "正七价的氟离子" in window.windowTitle(), "author's pen name must stay verbatim"
    assert window.identify_button.text() == "自動辨識並標註"
    assert window.generate_labels_button.text() == "重新產生標註"
    assert window.identification_status.text() == "未辨識"
    assert window.workspace_tabs.tabText(0) == "校準"
    titles = [action.text() for action in window.toolbar.actions()]
    assert "開啟照片" in titles
    assert "儲存專案" in titles
    assert "介面語言" in titles


def test_combo_boxes_keep_simplified_project_values(traditional_window):
    window = traditional_window
    # Display text is Traditional, the stored project value stays the Simplified source value
    # so .moonlabel files remain compatible with upstream.
    assert window.kind.itemText(0) == "全部"
    assert window.kind.itemData(0) == "全部"
    labels = [window.language.itemText(i) for i in range(window.language.count())]
    values = [window.language.itemData(i) for i in range(window.language.count())]
    assert values == list(LANGUAGE_CHOICES)
    assert "繁體中文" in labels and "雙語（繁體）" in labels
    window.language.setCurrentIndex(window.language.findData("繁体中文"))
    window.apply_label_settings()
    assert window.project.language == "繁体中文"
    assert window.project.kind == "全部"


def test_error_dialog_text_is_translated(traditional_window, monkeypatch):
    from moonlabeler import app as app_module
    shown = {}
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text: shown.update(title=title, text=text))
    traditional_window.error("请先打开照片。")
    assert shown["text"] == "請先開啟照片。"
    assert traditional_window.statusBar().currentMessage() == "操作未完成。"


def test_language_dialog_lists_native_names(app):
    from moonlabeler.ui.language import LanguageDialog
    previous = i18n.current_language()
    i18n.set_language(i18n.TRADITIONAL)
    try:
        dialog = LanguageDialog(i18n.TRADITIONAL)
        combo = dialog.findChild(type(dialog.combo), "uiLanguage") or dialog.combo
        assert [combo.itemText(i) for i in range(combo.count())] == ["简体中文", "繁體中文"]
        assert [combo.itemData(i) for i in range(combo.count())] == list(i18n.LANGUAGES)
        assert dialog.selected() == i18n.TRADITIONAL
        assert dialog.windowTitle() == "介面語言"
    finally:
        i18n.set_language(previous)


def test_simplified_window_is_unchanged(app):
    from moonlabeler.app import MainWindow
    previous = i18n.current_language()
    i18n.set_language(i18n.SIMPLIFIED)
    try:
        window = MainWindow()
        assert window.identify_button.text() == "自动识别并标注"
        assert window.kind.itemData(0) == "全部"
        window.close()
    finally:
        i18n.set_language(previous)
