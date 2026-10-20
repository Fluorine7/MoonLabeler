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
def language_state():
    """Restore both the resolved language and the explicit-choice flag afterwards."""
    previous = (i18n._language, i18n._explicit)
    yield
    i18n._language, i18n._explicit = previous


@pytest.fixture
def traditional_window(app, language_state):
    from moonlabeler.app import MainWindow
    i18n.set_language(i18n.TRADITIONAL)
    window = MainWindow()
    try:
        yield window
    finally:
        window.close()


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


def test_status_messages_keep_file_names_verbatim(traditional_window, monkeypatch, tmp_path):
    """Display points translate the template first and insert the file name afterwards."""
    from moonlabeler import app as app_module
    window = traditional_window
    project_path = tmp_path / "月球（原图） 文件 备份.moonlabel"
    monkeypatch.setattr(app_module.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(project_path), "")))
    window.project.image_path = str(tmp_path / "照片.png")
    window.image = app_module.np.zeros((4, 4, 3), dtype=app_module.np.uint8)
    window.save_project()
    assert window.statusBar().currentMessage() == "已儲存 月球（原图） 文件 备份.moonlabel"
    assert project_path.exists()


def test_error_dialog_text_is_translated(traditional_window, monkeypatch):
    from moonlabeler import app as app_module
    shown = {}
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text: shown.update(title=title, text=text))
    traditional_window.error("请先打开照片。")
    assert shown["text"] == "請先開啟照片。"
    assert traditional_window.statusBar().currentMessage() == "操作未完成。"
    # Exceptions raised by MoonLabeler itself are translated whole, like strings.
    traditional_window.error(ValueError("参考工程未配准"))
    assert shown["text"] == "參考專案未配準"


def test_os_error_paths_are_shown_verbatim(traditional_window, monkeypatch):
    from moonlabeler import app as app_module
    shown = {}
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text: shown.update(text=text))
    path = "C:/用户/文件 备份/月球（原图）.png"
    traditional_window.error(FileNotFoundError(2, "No such file or directory", path))
    assert shown["text"] == "No such file or directory\n" + path
    posix = "/用户/工程/照片.png"
    traditional_window.error(PermissionError(13, "拒绝访问", posix))
    assert shown["text"].endswith("\n" + posix), "a POSIX path with a Chinese first directory stays verbatim"
    assert shown["text"].splitlines()[0] == "拒絕訪問", "the description itself is still translated"
    # Rename-style errors carry two paths; both stay untouched.
    traditional_window.error(FileExistsError(17, "File exists", path, None, posix))
    assert shown["text"] == "File exists\n" + path + "\n" + posix


def test_recognition_failure_keeps_nested_os_error_paths(traditional_window, monkeypatch):
    """The all-strategies-failed error renders each cause separately; nested paths stay verbatim."""
    from moonlabeler import app as app_module
    shown = {}
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text: shown.update(text=text))
    posix = "/用户/工程/照片.png"
    failure = app_module.RecognitionFailure(7, [
        ("纹理参考：", ValueError("纹理对应点太少或过于集中，未采用配准。")),
        ("轮廓参考：", ValueError("没有可用的月盘轮廓。")),
        ("坑群参考：", ValueError("可用坑缘不足七处，无法独立验证自动识别。")),
        ("高程参考：", PermissionError(13, "Permission denied", posix)),
    ])
    # Logs and tracebacks keep the Simplified summary with the raw causes.
    assert str(failure).splitlines()[0] == "检测到 7 个疑似坑缘；未通过自动配准验证。"
    assert posix in str(failure)
    traditional_window.error(failure)
    lines = shown["text"].splitlines()
    assert lines[0] == "偵測到 7 個疑似坑緣；未通過自動配準驗證。"
    assert lines[1] == "紋理參考：紋理對應點太少或過於集中，未採用配準。"
    assert lines[3] == "坑群參考：可用坑緣不足七處，無法獨立驗證自動辨識。"
    assert lines[4] == "高程參考：Permission denied"
    assert lines[5] == posix


def test_background_failure_delivers_the_exception_object(traditional_window, monkeypatch):
    from moonlabeler import app as app_module
    received = []
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text: received.append(text))
    worker = app_module.Worker(lambda: (_ for _ in ()).throw(FileNotFoundError(2, "No such file or directory", "D:/月面/文件 1.png")))
    worker.signals.error.connect(traditional_window.error)
    worker.run()
    assert received == ["No such file or directory\nD:/月面/文件 1.png"]


def test_language_dialog_lists_native_names(app, language_state):
    from moonlabeler.ui.language import LanguageDialog
    i18n.set_language(i18n.TRADITIONAL)
    dialog = LanguageDialog(i18n.TRADITIONAL)
    combo = dialog.findChild(type(dialog.combo), "uiLanguage") or dialog.combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["简体中文", "繁體中文"]
    assert [combo.itemData(i) for i in range(combo.count())] == list(i18n.LANGUAGES)
    assert dialog.selected() == i18n.TRADITIONAL
    assert dialog.windowTitle() == "介面語言"


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


def test_simplified_window_is_unchanged(app, language_state):
    from moonlabeler.app import MainWindow
    i18n.set_language(i18n.SIMPLIFIED)
    window = MainWindow()
    assert window.identify_button.text() == "自动识别并标注"
    assert window.kind.itemData(0) == "全部"
    window.close()
