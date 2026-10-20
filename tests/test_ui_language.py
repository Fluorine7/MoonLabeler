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


class _FakePreferences:
    def __init__(self, **values):
        self.values = dict(values)

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


def test_language_dialog_preselects_pending_saved_preference(traditional_window, monkeypatch):
    """A saved-but-not-yet-active choice must not be reverted by reopening the dialog."""
    from moonlabeler.ui import language as language_module
    from PySide6.QtWidgets import QDialog
    seen = []

    class FakeDialog:
        def __init__(self, current, parent=None):
            seen.append(current)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(language_module, "LanguageDialog", FakeDialog)
    window = traditional_window
    window.compute_preferences = _FakePreferences(**{i18n.PREFERENCE_KEY: "zh-CN"})
    window.choose_ui_language()
    assert seen == ["zh-CN"], "dialog shows the saved preference, not the language currently running"
    window.compute_preferences = _FakePreferences()
    window.choose_ui_language()
    assert seen[-1] == i18n.TRADITIONAL, "without a saved preference it falls back to the active language"


def test_restart_failure_keeps_the_window_open(traditional_window, monkeypatch):
    from moonlabeler import app as app_module
    from PySide6.QtGui import QCloseEvent
    shown = {}
    monkeypatch.setattr(app_module.QProcess, "startDetached", staticmethod(lambda *args: (False, 0)))
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text: shown.update(text=text))
    window = traditional_window
    window.confirm_discard = lambda: True
    window.restart_requested = True
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert window.restart_requested is False
    assert "無法自動重新啟動" in shown["text"]


def test_restart_relaunches_module_from_repository_root(traditional_window, monkeypatch, tmp_path):
    from moonlabeler import app as app_module
    from PySide6.QtGui import QCloseEvent
    calls = []
    monkeypatch.setattr(app_module.QProcess, "startDetached", staticmethod(lambda *args: (calls.append(args), (True, 4242))[1]))
    photo = tmp_path / "moon.png"
    photo.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app_module.sys, "argv", ["run_app.py", "moon.png"])
    window = traditional_window
    window.confirm_discard = lambda: True
    window.restart_requested = True
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    program, arguments, cwd = calls[0]
    assert program == app_module.sys.executable
    assert arguments[:2] == ["-m", "moonlabeler"]
    assert arguments[2] == str(photo.resolve()), "relative photo path is made absolute before the cwd changes"
    assert cwd == str(app_module.ROOT)


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
