import json

import pytest

from moonlabeler import zh_variant
from moonlabeler.project import Project, LANGUAGE_CHOICES


pytestmark = pytest.mark.skipif(not zh_variant.available(), reason="opencc port not installed")


def test_to_traditional_converts_and_applies_overrides():
    assert zh_variant.to_traditional("哥白尼环形山") == "哥白尼環形山"
    assert zh_variant.to_traditional("湿海") == "濕海"
    assert zh_variant.to_traditional("北杂岩体") == "北雜岩體"
    assert zh_variant.to_traditional("") == ""
    assert zh_variant.to_traditional("Copernicus") == "Copernicus"


def _project(language):
    project = Project(image_path="demo.png")
    project.language = language
    return project


FEATURE = {"id": "copernicus", "name": "Copernicus", "name_zh": "哥白尼环形山"}
NO_ZH = {"id": "hadley-c", "name": "Hadley C", "name_zh": ""}


@pytest.mark.parametrize("language, expected", [
    ("双语", "哥白尼环形山 · Copernicus"),
    ("英文", "Copernicus"),
    ("中文", "哥白尼环形山"),
    ("繁体中文", "哥白尼環形山"),
    ("双语（繁体）", "哥白尼環形山 · Copernicus"),
])
def test_label_text_per_language(language, expected):
    assert _project(language).label_text(FEATURE) == expected


@pytest.mark.parametrize("language", ["繁体中文", "双语（繁体）"])
def test_traditional_falls_back_to_official_name(language):
    assert _project(language).label_text(NO_ZH) == "Hadley C"


def test_user_override_is_not_converted():
    project = _project("繁体中文")
    project.labels[FEATURE["id"]] = {"text": "我的标注"}
    assert project.label_text(FEATURE) == "我的标注"


def test_project_round_trips_traditional_language(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"")
    project = Project(image_path=str(image))
    project.language = "双语（繁体）"
    path = tmp_path / "demo.moonlabel"
    project.save(path)
    assert Project.load(path).language == "双语（繁体）"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["style"]["language"] = "粤语"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        Project.load(path)


def test_language_choices_are_shared_with_validator():
    assert LANGUAGE_CHOICES == ("双语", "英文", "中文", "繁体中文", "双语（繁体）")


def test_gui_offers_traditional_and_regenerates_labels():
    import os
    from pathlib import Path
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from moonlabeler.app import MainWindow

    QApplication.instance() or QApplication([])
    window = MainWindow()
    window.error = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.open_project(str(Path(__file__).parents[1] / "examples/demo.moonlabel"))
    assert [window.language.itemText(i) for i in range(window.language.count())] == list(LANGUAGE_CHOICES)
    window.language.setCurrentText("双语（繁体）")
    window.generate_labels_button.click()
    assert window.project.language == "双语（繁体）"
    shown =[window.project.label_text(item.feature) for item in window.annotation_items]
    assert shown and all(" · " in text for text in shown if any("一" <= ch <= "鿿" for ch in text))
    assert all(zh_variant.to_traditional(text) == text for text in shown), shown[:5]


def test_new_photo_defaults_to_traditional_names_under_traditional_interface(tmp_path):
    import os
    import numpy as np
    from PIL import Image
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from moonlabeler import i18n
    from moonlabeler.app import MainWindow, default_name_language

    QApplication.instance() or QApplication([])
    photo = tmp_path / "moon.png"
    Image.fromarray(np.zeros((64, 64, 3), np.uint8)).save(photo)
    previous = i18n.current_language()
    try:
        i18n.set_language(i18n.TRADITIONAL)
        assert default_name_language() == "双语（繁体）"
        window = MainWindow()
        window.error = lambda message: (_ for _ in ()).throw(AssertionError(message))
        assert window.project.language == window.language.currentData() == "双语（繁体）"
        window.open_image(str(photo))
        assert window.project.language == window.language.currentData() == "双语（繁体）"
        window.dirty = False
        window.close()
        i18n.set_language(i18n.SIMPLIFIED)
        assert default_name_language() == "双语"
        assert MainWindow().project.language == "双语"
    finally:
        i18n.set_language(previous)
