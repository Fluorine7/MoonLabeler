# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Traditional Chinese interface: widget texts convert, project values do not."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
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
    zoom_actions = {action.text(): action for action in window.actions
                    if action.text() in {"原始大小", "適合視窗", "+", "−"}}
    assert list(zoom_actions) == ["原始大小", "適合視窗", "+", "−"]
    assert zoom_actions["+"].toolTip() == "放大"
    assert zoom_actions["−"].toolTip() == "縮小"
    assert zoom_actions["原始大小"].toolTip() == "以原始大小顯示"


def test_combo_boxes_keep_simplified_project_values(traditional_window):
    window = traditional_window
    # Display text is Traditional, the stored project value stays the Simplified source value
    # so .moonlabel files remain compatible with upstream.
    assert window.kind.itemText(0) == "全部"
    assert window.kind.itemData(0) == "全部"
    labels = [window.language.itemText(i) for i in range(window.language.count())]
    values = [window.language.itemData(i) for i in range(window.language.count())]
    assert values == list(LANGUAGE_CHOICES)
    assert labels == ["雙語（簡體）", "雙語（繁體）", "簡體中文", "繁體中文", "英語"]
    window.language.setCurrentIndex(window.language.findData("繁体中文"))
    window.apply_label_settings()
    assert window.project.language == "繁体中文"
    assert window.project.kind == "全部"


@pytest.mark.parametrize('language,crater,chain,valley', [
    (i18n.SIMPLIFIED, '环形山', '坑链', '月谷'),
    (i18n.TRADITIONAL, '環形山', '坑鏈', '月谷'),
    (i18n.ENGLISH, 'Crater', 'Crater chain', 'Valley'),
])
def test_feature_types_follow_interface_language_without_changing_saved_filters(
        app, language_state, tmp_path, language, crater, chain, valley):
    import re
    from moonlabeler.app import MainWindow
    from moonlabeler.project import Project
    i18n.set_language(language)
    window = MainWindow()
    try:
        for kind, caption in [('Crater, craters', crater), ('Catena, catenae', chain), ('Vallis, valles', valley)]:
            index = window.kind.findData(kind)
            assert index >= 0 and window.kind.itemText(index) == caption
        for index in range(1, window.kind.count()):
            caption = window.kind.itemText(index)
            assert bool(re.search(r'[一-鿿]', caption)) == (language != i18n.ENGLISH)
        window.kind.setCurrentIndex(window.kind.findData('Crater, craters'))
        window.apply_label_settings()
        path = tmp_path/'地形类别.moonlabel'
        window.project.save(path)
        window.project = Project.load(path)
        window.sync_controls()
        assert window.project.kind == window.kind.currentData() == 'Crater, craters'
        assert window.kind.currentText() == crater
    finally:
        window.dirty = False
        window.close()


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
    import pickle
    restored = pickle.loads(pickle.dumps(failure))
    assert str(restored) == str(failure) and restored.candidate_count == 7
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
    assert [combo.itemText(i) for i in range(combo.count())] == ["简体中文", "繁體中文", "English"]
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


# Injected so the English tests do not depend on the state of ui_en.json.
EN_STRINGS = {
    "自动识别并标注": "Identify and Label",
    "全部": "All",
    "双语": "Bilingual",
    "英文": "English",
    "中文": "Chinese",
    "繁体中文": "Traditional Chinese",
    "双语（繁体）": "Bilingual (Traditional)",
    "双语（简体）": "Bilingual (Simplified)",
    "简体中文": "Simplified Chinese",
    "英语": "English",
    "请先打开照片。": "Please open a photo first.",
    "操作未完成。": "Operation not completed.",
    "检测到 {count} 个疑似坑缘；未通过自动配准验证。": "Found {count} possible crater rims; automatic registration failed.",
    "纹理参考：": "Texture reference: ",
    "没有可用的月盘轮廓。": "No usable lunar limb.",
}
EN_TEMPLATES = {"工程字段无效：{field}。": "Invalid project field: {field}."}


@pytest.fixture
def english_window(app, language_state, monkeypatch):
    from moonlabeler.app import MainWindow
    monkeypatch.setattr(i18n, "_english_table", lambda: (dict(EN_STRINGS), dict(EN_TEMPLATES)))
    i18n.set_language(i18n.ENGLISH)
    window = MainWindow()
    try:
        yield window
    finally:
        window.close()


def test_widgets_show_english_text(english_window):
    window = english_window
    assert window.identify_button.text() == "Identify and Label"
    assert "正七价的氟离子" in window.windowTitle(), "author's pen name must stay verbatim"
    # Strings without an English entry yet fall back to the Simplified source text.
    assert window.workspace_tabs.tabText(0) == "校准"


def test_english_combo_boxes_keep_simplified_project_values(english_window):
    window = english_window
    assert window.kind.itemText(0) == "All"
    assert window.kind.itemData(0) == "全部"
    labels = [window.language.itemText(i) for i in range(window.language.count())]
    values = [window.language.itemData(i) for i in range(window.language.count())]
    assert values == list(LANGUAGE_CHOICES)
    assert labels == ["Bilingual (Simplified)", "Bilingual (Traditional)", "Simplified Chinese", "Traditional Chinese", "English"]
    window.language.setCurrentIndex(window.language.findData("繁体中文"))
    window.apply_label_settings()
    assert window.project.language == "繁体中文"


def test_english_feature_selectors_show_official_names(english_window):
    """Search results and the DEM region picker show the USGS name alone in English."""
    import re
    window = english_window
    window.feature_search.setText("Copernicus")
    window.search_features("Copernicus")
    texts = [window.feature_list.item(i).text() for i in range(window.feature_list.count())]
    assert texts and all(re.search(r"[一-鿿]", text) is None for text in texts), texts
    assert any(text.startswith("Copernicus  (") for text in texts), texts
    window.search_terrain_features("Aristarchus")
    entries = [window.terrain_center.itemText(i) for i in range(window.terrain_center.count())]
    assert "Aristarchus" in entries, entries
    assert all(re.search(r"[一-鿿]", entry) is None for entry in entries), entries
    window.search_crater_features("Kepler")
    candidates = [window.crater_feature.item(i).text() for i in range(window.crater_feature.count())]
    assert "Kepler" in candidates
    assert all(re.search(r"[一-鿿]", entry) is None for entry in candidates), candidates


def test_chinese_feature_selectors_keep_the_bilingual_caption(traditional_window):
    window = traditional_window
    window.search_features("Copernicus")
    texts = [window.feature_list.item(i).text() for i in range(window.feature_list.count())]
    assert any(text.startswith("哥白尼  ·  Copernicus  (") for text in texts), texts


def test_english_error_dialog_text(english_window, monkeypatch):
    from moonlabeler import app as app_module
    shown = {}
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text: shown.update(text=text))
    english_window.error("请先打开照片。")
    assert shown["text"] == "Please open a photo first."
    assert english_window.statusBar().currentMessage() == "Operation not completed."
    # Formatted core messages are matched against templates.
    assert app_module.describe_error(ValueError("工程字段无效：utc。")) == "Invalid project field: utc."
    path = "C:/用户/工程/照片.png"
    english_window.error(FileNotFoundError(2, "No such file or directory", path))
    assert shown["text"] == "No such file or directory\n" + path


def test_english_recognition_failure_translates_the_summary_template(english_window, monkeypatch):
    from moonlabeler import app as app_module
    failure = app_module.RecognitionFailure(5, [("纹理参考：", ValueError("没有可用的月盘轮廓。"))])
    assert str(failure).splitlines()[0] == "检测到 5 个疑似坑缘；未通过自动配准验证。"
    assert app_module.describe_error(failure).splitlines() == [
        "Found 5 possible crater rims; automatic registration failed.",
        "Texture reference: No usable lunar limb.",
    ]


def test_simplified_window_is_unchanged(app, language_state):
    from moonlabeler.app import MainWindow
    i18n.set_language(i18n.SIMPLIFIED)
    window = MainWindow()
    assert window.identify_button.text() == "自动识别并标注"
    assert window.kind.itemData(0) == "全部"
    window.close()


def test_traditional_names_are_searchable_in_all_selectors(traditional_window):
    window = traditional_window
    window.search_features("靜海")
    assert any(window.feature_list.item(i).data(Qt.ItemDataRole.UserRole) == "3691"
               for i in range(window.feature_list.count()))
    window.search_terrain_features("靜海")
    assert window.terrain_center.findData("3691") >= 0
    window.search_crater_features("開普勒")
    assert any("Kepler" in window.crater_feature.item(i).text()
               for i in range(window.crater_feature.count()))


def test_external_oserror_without_filename_preserves_path(traditional_window, tmp_path):
    from PIL import UnidentifiedImageError
    from moonlabeler.app import describe_error
    from moonlabeler.sources import read_image
    path = tmp_path / "月球 文件" / "照片.png"
    path.parent.mkdir()
    path.write_bytes(b"invalid image")
    with pytest.raises(UnidentifiedImageError) as error:
        read_image(path)
    assert error.value.filename is None
    assert describe_error(error.value) == str(error.value)
    # Pillow quotes paths with repr(), which doubles Windows backslashes.
    assert path.parent.name in describe_error(error.value)
    assert path.name in describe_error(error.value)
