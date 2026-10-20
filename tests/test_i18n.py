# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Interface language resolution and Simplified→Traditional interface text."""
import json
import os

import pytest

from moonlabeler import i18n
from moonlabeler import zh_variant

pytestmark = pytest.mark.skipif(not zh_variant.available(), reason="OpenCC port not installed")


@pytest.fixture
def traditional():
    previous = i18n.current_language()
    i18n.set_language(i18n.TRADITIONAL)
    yield
    i18n.set_language(previous)


@pytest.fixture
def simplified():
    previous = i18n.current_language()
    i18n.set_language(i18n.SIMPLIFIED)
    yield
    i18n.set_language(previous)


def test_normalize_accepts_common_codes_and_labels():
    for code in ("zh-TW", "zh_TW", "zh_TW.UTF-8", "zh-Hant", "zh-HK", "繁體中文", "繁体中文"):
        assert i18n.normalize(code) == i18n.TRADITIONAL, code
    for code in ("zh-CN", "zh_CN", "zh-Hans", "zh", "简体中文"):
        assert i18n.normalize(code) == i18n.SIMPLIFIED, code
    assert i18n.normalize("en_US") is None
    assert i18n.normalize(None) is None
    assert i18n.normalize("") is None


def test_resolve_prefers_environment_then_preference(monkeypatch):
    monkeypatch.setenv(i18n.ENV_VARIABLE, "zh-TW")
    assert i18n.resolve("zh-CN") == i18n.TRADITIONAL
    monkeypatch.delenv(i18n.ENV_VARIABLE)
    assert i18n.resolve("zh-TW") == i18n.TRADITIONAL
    assert i18n.resolve("zh-CN") == i18n.SIMPLIFIED
    # Garbage in the preference file falls through to the system locale, never raises.
    assert i18n.resolve("nonsense") in i18n.LANGUAGES


def test_set_language_falls_back_to_simplified_for_unknown_codes():
    previous = i18n.current_language()
    try:
        assert i18n.set_language("fr") == i18n.SIMPLIFIED
        assert i18n.set_language("zh-TW") == i18n.TRADITIONAL
        assert i18n.is_traditional()
    finally:
        i18n.set_language(previous)


def test_tr_is_identity_in_simplified(simplified):
    assert i18n.tr("保存工程") == "保存工程"
    assert i18n.tr("") == ""
    assert i18n.tr(None) is None


def test_tr_converts_characters_and_software_vocabulary(traditional):
    assert i18n.tr("保存工程") == "儲存專案"
    assert i18n.tr("导出 PNG") == "匯出 PNG"
    assert i18n.tr("打开照片") == "開啟照片"
    assert i18n.tr("尚未选择高程数据") == "尚未選擇高程資料"
    assert i18n.tr("恢复默认 15:00:00 UTC") == "還原預設 15:00:00 UTC"
    assert i18n.tr("计算设置") == "計算設定"
    # Longest phrase wins: 文件名→檔名, not 檔案名.
    assert i18n.tr("文件名时间") == "檔名時間"


def test_tr_keeps_domain_terms_and_names(traditional):
    # Character conversion must not turn registration/mirror jargon into mainland IT phrases.
    assert i18n.tr("镜像") == "鏡像"
    assert i18n.tr("未通过自动配准验证") == "未通過自動配準驗證"
    assert i18n.tr("着陆点（阿波罗 / 嫦娥）") == "著陸點（阿波羅 / 嫦娥）"
    # Latin text and numbers pass through untouched.
    assert i18n.tr("MoonLabeler (*.moonlabel)") == "MoonLabeler (*.moonlabel)"


def test_tr_handles_formatted_runtime_strings(traditional):
    count = 3
    assert i18n.tr(f"{count} 个有效参考点 · 最少 3 个") == "3 個有效參考點 · 最少 3 個"
    assert i18n.tr(f"已保存 {'demo.moonlabel'}") == "已儲存 demo.moonlabel"


def test_exact_strings_override_mechanical_conversion(traditional):
    strings = json.loads(i18n.DATA_PATH.read_text(encoding="utf-8"))["strings"]
    for source, target in strings.items():
        assert i18n.tr(source) == target
        assert source != target, f"redundant exact entry {source!r}"


def test_phrase_table_is_keyed_on_traditional_text():
    """Phrases are applied after OpenCC, so their keys must already be Traditional."""
    # OpenCC leaves 采 unconverted inside some sentences (没有采用 → 沒有采用), so those two
    # keys are deliberately the Simplified residue that the phrase pass cleans up.
    residue = {"采用", "采樣"}
    data = json.loads(i18n.DATA_PATH.read_text(encoding="utf-8"))
    for source in data["phrases"]:
        if source in residue:
            continue
        assert zh_variant.to_traditional(source) == source, f"phrase key {source!r} is not Traditional"


def test_environment_pin_used_by_the_test_suite():
    assert os.environ.get(i18n.ENV_VARIABLE) == "zh-CN"


def test_phrase_pass_is_single_longest_match(traditional):
    # A replacement is never re-scanned by a shorter key; identity entries protect longer words.
    assert i18n.tr("最低 6 原图像素") == "最低 6 原圖像素"
    assert i18n.tr("边缘支持度 0.80，用于排序") == "邊緣支持度 0.80，用於排序"
    assert i18n.tr("点击选中；请核对坑缘和地名。") == "點選以選取；請核對坑緣和地名。"
    assert i18n.tr("按公开坐标标注，使用小档字号。") == "按公開座標標註，使用最小字級。"
    assert i18n.tr("可检查代理中此域名的线路") == "可檢查代理伺服器中此網域的線路"


def test_file_names_and_paths_are_never_rewritten(traditional):
    assert i18n.tr("已保存 文件名-计算工程.png") == "已儲存 文件名-计算工程.png"
    assert i18n.tr("已打开 demo.moonlabel") == "已開啟 demo.moonlabel"
    assert i18n.tr("[Errno 2] No such file or directory: 'C:/用户/工程/照片.png'") == \
        "[Errno 2] No such file or directory: 'C:/用户/工程/照片.png'"
    assert i18n.tr("无法读取 D:\\月面\\文件\\raw.tif 的像素") == "無法讀取 D:\\月面\\文件\\raw.tif 的像素"
    assert i18n.tr("原始照片已移动，请重新选择 ./照片/文件.jpg") == "原始照片已移動，請重新選擇 ./照片/文件.jpg"


def test_system_language_defaults_to_simplified_for_unknown_regions(monkeypatch):
    monkeypatch.setattr(i18n, "_system_locale_name", lambda: "zh_MY")
    assert i18n.system_language() == i18n.SIMPLIFIED
    monkeypatch.setattr(i18n, "_system_locale_name", lambda: "zh_HK")
    assert i18n.system_language() == i18n.TRADITIONAL
    monkeypatch.setattr(i18n, "_system_locale_name", lambda: None)
    assert i18n.system_language() == i18n.SIMPLIFIED


@pytest.fixture
def pristine_state(monkeypatch):
    """Run with no language resolved yet and restore the module state afterwards."""
    previous = (i18n._language, i18n._explicit)
    monkeypatch.setattr(i18n, "_language", None)
    monkeypatch.setattr(i18n, "_explicit", False)
    yield
    i18n._language, i18n._explicit = previous


def test_initialize_respects_explicit_choice_but_applies_startup_order_otherwise(pristine_state, monkeypatch):
    monkeypatch.setenv(i18n.ENV_VARIABLE, "zh-CN")
    i18n.set_language("zh-TW")
    assert i18n.initialize("zh-CN") == i18n.TRADITIONAL, "explicit set_language wins over main()"
    monkeypatch.setattr(i18n, "_language", None)
    monkeypatch.setattr(i18n, "_explicit", False)
    assert i18n.initialize("zh-TW") == i18n.SIMPLIFIED, "environment beats the saved preference"
    monkeypatch.delenv(i18n.ENV_VARIABLE)
    monkeypatch.setattr(i18n, "_explicit", False)
    assert i18n.initialize("zh-TW") == i18n.TRADITIONAL, "saved preference beats the locale"
    assert i18n.current_language() == i18n.TRADITIONAL
