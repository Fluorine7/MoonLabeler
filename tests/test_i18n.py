# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Interface language resolution, Simplified→Traditional and Simplified→English interface text."""
import ast
import json
import os
import re
from pathlib import Path

import pytest

from moonlabeler import i18n
from moonlabeler import zh_variant
from moonlabeler.project import LANGUAGE_CHOICES

pytestmark = pytest.mark.skipif(not zh_variant.available(), reason="OpenCC port not installed")


@pytest.fixture
def traditional():
    previous = (i18n._language, i18n._explicit)
    i18n.set_language(i18n.TRADITIONAL)
    yield
    i18n._language, i18n._explicit = previous


@pytest.fixture
def simplified():
    previous = (i18n._language, i18n._explicit)
    i18n.set_language(i18n.SIMPLIFIED)
    yield
    i18n._language, i18n._explicit = previous


def test_normalize_accepts_common_codes_and_labels():
    for code in ("zh-TW", "zh_TW", "zh_TW.UTF-8", "zh-Hant", "zh-HK", "繁體中文", "繁体中文"):
        assert i18n.normalize(code) == i18n.TRADITIONAL, code
    for code in ("zh-CN", "zh_CN", "zh-Hans", "zh", "简体中文"):
        assert i18n.normalize(code) == i18n.SIMPLIFIED, code
    for code in ("en", "EN", "en_US", "en-US", "en_GB", "en-gb", "en_AU", "en_US.UTF-8", "English", "English_United States"):
        assert i18n.normalize(code) == i18n.ENGLISH, code
    for code in ("fr_FR", "ja_JP", "de", "eng", "enx", "nonsense"):
        assert i18n.normalize(code) is None, code
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
    previous = (i18n._language, i18n._explicit)
    try:
        assert i18n.set_language("fr") == i18n.SIMPLIFIED
        assert i18n.set_language("zh-TW") == i18n.TRADITIONAL
        assert i18n.is_traditional()
    finally:
        i18n._language, i18n._explicit = previous


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
    assert i18n.tr("无法读取 /home/用户/文件.fits") == "無法讀取 /home/用户/文件.fits"
    assert i18n.tr(r"无法读取 \\nas\月面\文件.tif") == "無法讀取 \\\\nas\\月面\\文件.tif"


def test_slashes_between_words_are_not_treated_as_paths(traditional):
    assert i18n.tr("长/短半轴 12.0 / 10.0 px；方向 20.0°") == "長/短半軸 12.0 / 10.0 px；方向 20.0°"
    assert i18n.tr("着陆点（阿波罗 / 嫦娥）") == "著陸點（阿波羅 / 嫦娥）"
    assert i18n.tr("导出 PNG / SVG 或保存工程") == "匯出 PNG / SVG 或儲存專案"
    assert i18n.tr("大 / 中 / 小：1.80% / 1.50% / 1.20%") == "大 / 中 / 小：1.80% / 1.50% / 1.20%"


def test_system_language_defaults_to_simplified_for_unknown_regions(monkeypatch):
    monkeypatch.setattr(i18n, "_system_locale_name", lambda: "zh_MY")
    assert i18n.system_language() == i18n.SIMPLIFIED
    monkeypatch.setattr(i18n, "_system_locale_name", lambda: "zh_HK")
    assert i18n.system_language() == i18n.TRADITIONAL
    monkeypatch.setattr(i18n, "_system_locale_name", lambda: None)
    assert i18n.system_language() == i18n.SIMPLIFIED


def test_system_language_is_english_for_other_known_locales(monkeypatch):
    for name in ("en_US", "en_GB", "en_AU", "fr_FR", "de_DE", "ja_JP", "ko_KR", "English_United States"):
        monkeypatch.setattr(i18n, "_system_locale_name", lambda name=name: name)
        assert i18n.system_language() == i18n.ENGLISH, name
    # Chinese locales stay Chinese; a locale without any language falls back to the source text.
    for name in ("zh_SG", "zh_MY", "Chinese (Simplified)_China", "C", "POSIX", ""):
        monkeypatch.setattr(i18n, "_system_locale_name", lambda name=name: name)
        assert i18n.system_language() == i18n.SIMPLIFIED, name
    for name in ("zh_TW", "zh_MO.UTF-8"):
        monkeypatch.setattr(i18n, "_system_locale_name", lambda name=name: name)
        assert i18n.system_language() == i18n.TRADITIONAL, name


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


# --- English ---------------------------------------------------------------------------------

# A small stand-in table, so these tests do not depend on the translations in ui_en.json.
EN_STRINGS = {
    "保存工程": "Save Project",
    "已保存 {name}": "Saved {name}",
    "{count} 个候选": "{count} candidates",
    "根节点": "root node",
    "纹理配准与照片月缘不一致，未采用配准。": "Texture registration disagrees with the photo's limb; not used.",
    "连接或读取超时": "connection or read timed out",
}
EN_TEMPLATES = {
    "工程字段无效：{field}。": "Invalid project field: {field}.",
    "{message}\n相机直拍模式未启用目镜畸变校正。": "{message}\nEyepiece distortion correction is off in direct-camera mode.",
    "无法下载 {host} 的参考数据：{detail}。": "Could not download reference data from {host}: {detail}.",
    "无法下载 {host} 的参考数据：数据不完整（收到 {received} 字节，应为 {expected} 字节）。请重试。":
        "Could not download reference data from {host}: incomplete ({received} of {expected} bytes). Please retry.",
}


@pytest.fixture
def english(monkeypatch):
    previous = (i18n._language, i18n._explicit)
    monkeypatch.setattr(i18n, "_english_table", lambda: (dict(EN_STRINGS), dict(EN_TEMPLATES)))
    i18n.set_language(i18n.ENGLISH)
    yield
    i18n._language, i18n._explicit = previous


def test_english_is_a_selectable_language():
    assert i18n.LANGUAGES == (i18n.SIMPLIFIED, i18n.TRADITIONAL, i18n.ENGLISH)
    assert i18n.LANGUAGE_NAMES[i18n.ENGLISH] == "English"
    previous = (i18n._language, i18n._explicit)
    try:
        assert i18n.set_language("en_US") == i18n.ENGLISH
        assert i18n.is_english() and not i18n.is_traditional()
    finally:
        i18n._language, i18n._explicit = previous


def test_tr_english_uses_exact_strings(english):
    assert i18n.tr("保存工程") == "Save Project"
    assert i18n.tr("根节点") == "root node"
    assert i18n.tr("") == "" and i18n.tr(None) is None


def test_tr_english_returns_unknown_text_unchanged(english):
    assert i18n.tr("尚未翻译的句子") == "尚未翻译的句子"
    assert i18n.tr("No such file or directory") == "No such file or directory"


def test_tr_english_matches_formatted_messages_against_templates(english):
    assert i18n.tr("工程字段无效：utc。") == "Invalid project field: utc."
    # Captured pieces are looked up once more.
    assert i18n.tr("工程字段无效：根节点。") == "Invalid project field: root node."
    assert i18n.tr("纹理配准与照片月缘不一致，未采用配准。\n相机直拍模式未启用目镜畸变校正。") == (
        "Texture registration disagrees with the photo's limb; not used.\n"
        "Eyepiece distortion correction is off in direct-camera mode.")
    assert i18n.tr("无法下载 svs.gsfc.nasa.gov 的参考数据：连接或读取超时。") == \
        "Could not download reference data from svs.gsfc.nasa.gov: connection or read timed out."
    # The template with the most literal text wins over the generic one that also matches.
    assert i18n.tr("无法下载 example.org 的参考数据：数据不完整（收到 10 字节，应为 20 字节）。请重试。") == \
        "Could not download reference data from example.org: incomplete (10 of 20 bytes). Please retry."
    # The whole message must match; a template never rewrites part of a longer sentence.
    assert i18n.tr("前言 工程字段无效：utc。") == "前言 工程字段无效：utc。"


def test_template_pieces_are_translated_only_one_level_deep(monkeypatch, english):
    templates = {"外层：{inner}": "Outer: {inner}", "内层：{piece}": "Inner: {piece}"}
    monkeypatch.setattr(i18n, "_english_table", lambda: ({"根节点": "root node"}, templates))
    assert i18n.tr("外层：内层：根节点") == "Outer: Inner: 根节点"


def test_trf_translates_the_template_before_inserting_values(english):
    assert i18n.trf("已保存 {name}", name="文件名-计算工程.png") == "Saved 文件名-计算工程.png"
    assert i18n.trf("{count} 个候选", count=3) == "3 candidates"
    assert i18n.trf("还没有译文 {count}", count=3) == "还没有译文 3"


def test_trf_in_chinese_interfaces(simplified):
    assert i18n.trf("已保存 {name}", name="文件名.png") == "已保存 文件名.png"
    assert i18n.trf("拟合偏差 {rms:.2f} px", rms=1.234) == "拟合偏差 1.23 px"


def test_trf_traditional_keeps_inserted_file_names(traditional):
    # The template is converted, the file name is inserted afterwards and never rewritten.
    assert i18n.trf("已保存 {name}", name="文件名 备份") == "已儲存 文件名 备份"
    assert i18n.trf("{count} 个有效参考点", count=3) == "3 個有效參考點"


def test_trf_falls_back_to_the_source_template_when_fields_do_not_match(monkeypatch, english):
    monkeypatch.setattr(i18n, "_english_table", lambda: ({"{count} 个候选": "{number} candidates"}, {}))
    assert i18n.trf("{count} 个候选", count=3) == "3 个候选"


def test_english_table_skips_entries_still_waiting_for_translation(monkeypatch, tmp_path):
    path = tmp_path / "ui_en.json"
    path.write_text(json.dumps({"strings": {"保存工程": "Save Project", "打开照片": ""},
                                "templates": {"工程字段无效：{field}。": ""}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "EN_DATA_PATH", path)
    i18n._english_table.cache_clear()
    try:
        assert i18n.to_english("保存工程") == "Save Project"
        assert i18n.to_english("打开照片") == "打开照片"
        assert i18n.to_english("工程字段无效：utc。") == "工程字段无效：utc。"
    finally:
        i18n._english_table.cache_clear()


# --- English coverage: every interface string has an entry in ui_en.json ---------------------------

PACKAGE = Path(i18n.__file__).resolve().parent
CJK = re.compile(r"[㐀-鿿豈-﫿]")
# Helpers whose literal arguments end up inside a raised message (or in a template field of one).
MESSAGE_HELPERS = {"_eyepiece_or_raise", "_mapping", "_invalid_field"}
# Functions whose return value is shown through tr(); every Chinese literal in them is a key.
MESSAGE_FUNCTIONS = {("compute.py", "status"), ("sources.py", "download_error_message"), ("app.py", "summary")}
# Messages assembled from several pieces at run time, which the scan cannot derive.
EXTRA_TEMPLATES = {
    "{message}\n{original_error}",  # atlas._eyepiece_or_raise
    "无法下载 {host} 的参考数据：{detail}。{advice}",  # sources.download_error_message for the NASA host
}


def _python_files():
    return sorted(PACKAGE.rglob("*.py"))


def _expression_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _expression_name(node.func)
    return "value"


def template_key(joined):
    """``f"无法下载 {host} 的…"`` → ``"无法下载 {host} 的…"`` (format specs dropped, text verbatim)."""
    parts = []
    for value in joined.values:
        if isinstance(value, ast.Constant):
            parts.append(value.value)
        else:
            parts.append("{" + _expression_name(value.value) + "}")
    return "".join(parts)


def _call_name(node):
    return _expression_name(node.func) if isinstance(node, ast.Call) else None


def _has_cjk(text):
    return isinstance(text, str) and CJK.search(text) is not None


def english_source_keys():
    """Scan the package for every text that reaches tr().

    Returns ``(strings, templates)``, each mapping a key to a list of
    ``(relative path, line, where)`` locations; ``where`` names the call or
    construct the text was found in.
    """
    strings, templates = {}, {}

    def add(table, key, path, node, where):
        table.setdefault(key, []).append((path.relative_to(PACKAGE.parent).as_posix(), node.lineno, where))

    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def enclosing_call(node):
            node = parents.get(node)
            while node is not None:
                if isinstance(node, ast.Call) and _call_name(node) not in ("tr", "trf"):
                    return _call_name(node)
                if isinstance(node, (ast.Assign, ast.AugAssign)):
                    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    return "=" + _expression_name(target)
                if isinstance(node, ast.stmt):
                    return type(node).__name__.lower()
                node = parents.get(node)
            return None

        def literals(root):
            """Chinese string constants under ``root`` that are not part of an f-string."""
            inside_fstring = {id(sub) for node in ast.walk(root) if isinstance(node, ast.JoinedStr) for sub in ast.walk(node)}
            for node in ast.walk(root):
                if isinstance(node, ast.Constant) and _has_cjk(node.value) and id(node) not in inside_fstring:
                    yield node

        def fstrings(root):
            for node in ast.walk(root):
                if isinstance(node, ast.JoinedStr) and any(
                        isinstance(part, ast.Constant) and _has_cjk(part.value) for part in node.values):
                    yield node

        for node in ast.walk(tree):
            # (a) tr("…") / trf("…") literals.
            if isinstance(node, ast.Call) and _call_name(node) in ("tr", "trf") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value:
                    add(strings, first.value, path, node, enclosing_call(node))
            # (b) project-value captions shown with tr(choice).
            if path.name == "project.py" and isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "LANGUAGE_CHOICES" for target in node.targets):
                for element in node.value.elts:
                    add(strings, element.value, path, element, "LANGUAGE_CHOICES")
            # (c) constant messages raised, (d) formatted ones as templates.
            if isinstance(node, ast.Raise) and node.exc is not None:
                for constant in literals(node.exc):
                    add(strings, constant.value, path, constant, "raise")
                for joined in fstrings(node.exc):
                    add(templates, template_key(joined), path, joined, "raise")
            if isinstance(node, ast.Call) and _call_name(node) in MESSAGE_HELPERS:
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and _has_cjk(argument.value):
                        add(strings, argument.value, path, argument, _call_name(node))
            if isinstance(node, ast.FunctionDef) and (path.name, node.name) in MESSAGE_FUNCTIONS:
                body = ast.Module(body=node.body[1:] if ast.get_docstring(node) else node.body, type_ignores=[])
                for constant in literals(body):
                    add(strings, constant.value, path, constant, node.name + "()")
                for joined in fstrings(body):
                    add(templates, template_key(joined), path, joined, node.name + "()")
    return strings, templates


def _english_data():
    return json.loads(i18n.EN_DATA_PATH.read_text(encoding="utf-8"))


def test_english_table_is_well_formed():
    data = _english_data()
    assert isinstance(data.get("strings"), dict) and isinstance(data.get("templates"), dict)
    for table in ("strings", "templates"):
        for key, value in data[table].items():
            assert isinstance(key, str) and key and isinstance(value, str), (table, key)
    for key in data["templates"]:
        assert re.search(r"\{\w+\}", key), f"template {key!r} has no {{placeholder}}; put it in strings"
    for key in data["strings"]:
        assert key not in data["templates"], f"{key!r} is in both tables"


def test_scan_finds_the_known_sources():
    strings, templates = english_source_keys()
    assert "保存工程" in strings
    assert "已保存 {name}" in strings, "trf templates are exact strings"
    assert set(LANGUAGE_CHOICES) <= set(strings)
    assert "请先打开照片。" in strings
    assert "纹理配准与照片月缘不一致，未采用配准。" in strings, "_eyepiece_or_raise message argument"
    assert "根节点" in strings, "field name inserted into a template"
    assert "CPU · GPU 加速已关闭" in strings, "compute.status() return value"
    assert "检测到 {count} 个疑似坑缘；未通过自动配准验证。" in strings, "RecognitionFailure.summary()"
    assert "工程字段无效：{field}。" in templates
    assert "{message}\n相机直拍模式未启用目镜畸变校正。" in templates
    assert "DEM 标签缺少 {key}。" in templates
    assert "可用设备：{detail}\n加速高程与阴影参考；其余步骤使用 CPU。" in templates
    assert "无法下载 {host} 的参考数据：数据不完整（收到 {received} 字节，应为 {expected} 字节）。请重试。" in templates


def test_no_tr_call_receives_an_fstring():
    """Variable messages use trf("template", name=value) so the template is the lookup key."""
    offenders = []
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _call_name(node) in ("tr", "trf") and node.args \
                    and isinstance(node.args[0], ast.JoinedStr):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_every_interface_string_has_an_english_entry():
    strings, templates = english_source_keys()
    data = _english_data()
    missing_strings = sorted(set(strings) - set(data["strings"]))
    missing_templates = sorted((set(templates) | EXTRA_TEMPLATES) - set(data["templates"]))
    assert missing_strings == [], f"add to ui_en.json strings: {missing_strings[:10]}"
    assert missing_templates == [], f"add to ui_en.json templates: {missing_templates[:10]}"


def test_english_table_has_no_stale_entries():
    strings, templates = english_source_keys()
    data = _english_data()
    assert sorted(set(data["strings"]) - set(strings)) == []
    assert sorted(set(data["templates"]) - set(templates) - EXTRA_TEMPLATES) == []


def _format_fields(text):
    """``[(field, conversion, spec), …]`` as str.format sees them; raises on malformed syntax."""
    import string
    return sorted((name, conversion or "", spec or "")
                  for _, name, spec, conversion in string.Formatter().parse(text) if name is not None)


def test_english_templates_keep_their_placeholders():
    """Same fields, conversions and format specs as the key (order may differ); no broken syntax."""
    data = _english_data()
    for table in ("strings", "templates"):
        for key, value in data[table].items():
            if value:
                assert _format_fields(value) == _format_fields(key), (key, value)


def test_placeholder_check_rejects_broken_translations():
    assert _format_fields("{count} 个候选") != _format_fields("{{count}} candidates"), "escaped field drops the count"
    assert _format_fields("偏差 {rms:.2f}") != _format_fields("Deviation {rms:d}"), "changed spec would raise at run time"
    assert _format_fields("{a} / {a}") != _format_fields("{a}"), "repeated fields are counted"
    assert _format_fields("{name} · {w}") == _format_fields("{w} · {name}"), "field order may change"
    with pytest.raises(ValueError):
        _format_fields("保存 {name!")


# tr()/trf() calls whose first argument is not a literal, keyed file:function:expression. Each one
# is listed with the reason its value is already covered; a new call site needs its own entry.
DYNAMIC_ARGUMENTS = {
    "app.py:describe_error:detail": "OSError.strerror, shown as-is when no entry exists",
    "app.py:describe_error:str(problem)": "constant exception messages are scanned from their raise sites",
    "app.py:feature_caption:feature.get('name_zh') or feature['name']": "catalogue Chinese caption or official name",
    "app.py:accept_identification:name": "recognised feature names from the catalogue",
    "app.py:solve_manual:features[report.suspect_index]['name']": "suspect reference point: catalogue feature name",
    "i18n.py:trf:template": "the template is translated by tr() inside i18n itself",
    "ui/compute.py:__init__:compute.status()": "compute.status() literals are scanned (MESSAGE_FUNCTIONS)",
    "ui/compute.py:__init__:compute.status(self.mode.currentData())": "same",
    "ui/window.py:build_sidebar:choice": "name-language picker: LANGUAGE_CHOICES are scanned",
    "ui/window.py:ui_refresh_crater_review:item.text()": "crater feature list: catalogue feature names",
}


def _enclosing_functions(tree):
    """``id(node) → name of the innermost function containing it`` (module level: ``<module>``)."""
    owner = {}
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(function):
                owner[id(child)] = function.name  # ast.walk is outer-first, so inner functions win
    return owner


def dynamic_tr_arguments():
    """``"file:function:expression" → [line, …]`` for every non-literal tr()/trf() first argument."""
    found = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in ("tr", "trf") and node.args \
                    and not isinstance(node.args[0], ast.Constant):
                key = f"{path.relative_to(PACKAGE).as_posix()}:{owner.get(id(node), '<module>')}:{ast.unparse(node.args[0])}"
                found.setdefault(key, []).append(node.lineno)
    return found


def test_dynamic_tr_arguments_are_registered():
    """Non-literal tr()/trf() arguments bypass the literal scan, so each call site must be accounted for.

    Keys are file:function:expression, so a new ``tr(name)`` elsewhere needs its own justification.
    """
    found = dynamic_tr_arguments()
    unregistered = {key: lines for key, lines in found.items() if key not in DYNAMIC_ARGUMENTS}
    assert unregistered == {}, f"register in DYNAMIC_ARGUMENTS or pass a literal template: {unregistered}"
    assert sorted(set(DYNAMIC_ARGUMENTS) - set(found)) == [], "stale DYNAMIC_ARGUMENTS entry"


def test_nasa_download_failure_is_fully_translated():
    """The advice-bearing template must win over the generic one (same literal text, more fields).

    Uses the shipped ui_en.json, not the fixture table, because the collision is between two real entries.
    """
    from moonlabeler.sources import download_error_message
    i18n._english_table.cache_clear()
    try:
        message = download_error_message("https://svs.gsfc.nasa.gov/5587/a.png", TimeoutError("timed out"))
        result = i18n.to_english(message)
        assert result.startswith("Could not download reference data from svs.gsfc.nasa.gov: connection or read timed out.")
        assert not _has_cjk(result), result
        assert result.count("\n\n") == message.count("\n\n"), "every advice paragraph is kept"
        plain = download_error_message("https://pds.example.org/x", TimeoutError("timed out"))
        assert i18n.to_english(plain) == "Could not download reference data from pds.example.org: connection or read timed out."
    finally:
        i18n._english_table.cache_clear()


def test_every_english_entry_is_translated():
    data = _english_data()
    empty = [key for table in ("strings", "templates") for key, value in data[table].items() if not value]
    assert empty == [], f"{len(empty)} entries still empty"
