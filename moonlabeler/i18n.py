# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""User-interface language: Simplified Chinese (source text) or Traditional Chinese.

All interface strings in the code base are written in Simplified Chinese and
passed through :func:`tr` at the point where they are shown. For Traditional
Chinese the lookup order is:

1. an exact entry in ``data/ui_zh_TW.json`` ``"strings"`` (hand-curated
   sentences whose wording differs from a mechanical conversion);
2. otherwise OpenCC ``s2tw`` character conversion (shared with the name
   language in :mod:`zh_variant`) followed by the ``"phrases"`` table, which
   swaps mainland software vocabulary for the Taiwan equivalents
   (保存→儲存, 導出→匯出, 文件→檔案 …). This path also covers f-strings and
   exception messages whose exact text is only known at run time.

The active language is resolved lazily from, in order: an explicit
:func:`set_language` call, the ``MOONLABELER_UI_LANG`` environment variable
(used by the test-suite to pin Simplified), the saved preference handed to
:func:`resolve`, and finally the system locale. Changing the preference takes
effect after the application restarts; widgets are not retranslated live.
"""
import json
import locale
import os
from functools import lru_cache
from pathlib import Path

from . import zh_variant

SIMPLIFIED = "zh-CN"
TRADITIONAL = "zh-TW"
LANGUAGES = (SIMPLIFIED, TRADITIONAL)
# Native-script names for the language picker; never passed through tr().
LANGUAGE_NAMES = {SIMPLIFIED: "简体中文", TRADITIONAL: "繁體中文"}
ENV_VARIABLE = "MOONLABELER_UI_LANG"
PREFERENCE_KEY = "ui/language"
DATA_PATH = Path(__file__).resolve().parent / "data" / "ui_zh_TW.json"

_ALIASES = {
    SIMPLIFIED: ("zh-cn", "zh_cn", "zh-hans", "zh_hans", "zh-sg", "zh_sg", "zh", "simplified", "简体中文", "簡體中文"),
    TRADITIONAL: ("zh-tw", "zh_tw", "zh-hant", "zh_hant", "zh-hk", "zh_hk", "zh-mo", "zh_mo", "traditional", "繁體中文", "繁体中文"),
}

_language = None


def normalize(code):
    """Map a language code or label to ``zh-CN`` / ``zh-TW``; ``None`` when unknown."""
    if not code:
        return None
    text = str(code).strip().lower()
    # Strip encodings such as ``zh_TW.UTF-8`` reported by locale.getlocale().
    text = text.split(".")[0].split("@")[0]
    for language, aliases in _ALIASES.items():
        if text in aliases:
            return language
    return None


def system_language():
    """Traditional for zh_TW / zh_HK / zh_MO system locales, Simplified otherwise."""
    name = None
    try:
        from PySide6.QtCore import QLocale
        name = QLocale.system().name()
    except Exception:  # pragma: no cover - Qt unavailable or not initialised
        name = None
    if not name:
        try:
            name = locale.getlocale()[0]
        except Exception:  # pragma: no cover
            name = None
    return normalize(name) if name and name.lower().startswith("zh") else SIMPLIFIED


def resolve(preference=None):
    """Pick the language from the environment, then ``preference``, then the system locale."""
    return normalize(os.environ.get(ENV_VARIABLE)) or normalize(preference) or system_language()


def set_language(code):
    """Fix the active interface language; unknown codes fall back to Simplified."""
    global _language
    _language = normalize(code) or SIMPLIFIED
    return _language


def current_language():
    global _language
    if _language is None:
        _language = resolve()
    return _language


def is_traditional():
    return current_language() == TRADITIONAL


@lru_cache(maxsize=None)
def _table():
    with open(DATA_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    strings = data.get("strings", {})
    # Longest phrases first so that e.g. 文件名→檔名 wins over 文件→檔案.
    phrases = sorted(((k, v) for k, v in data.get("phrases", {}).items()), key=lambda item: -len(item[0]))
    return strings, tuple(phrases)


@lru_cache(maxsize=8192)
def to_traditional(text):
    """Translate Simplified interface text to Traditional regardless of the active language."""
    strings, phrases = _table()
    exact = strings.get(text)
    if exact is not None:
        return exact
    converted = zh_variant.to_traditional(text)
    for source, target in phrases:
        converted = converted.replace(source, target)
    return converted


def tr(text):
    """Return ``text`` in the active interface language.

    ``text`` is the Simplified source string (static literal or an already
    formatted f-string). Empty values and non-strings are returned unchanged.
    """
    if not text or not isinstance(text, str) or current_language() != TRADITIONAL:
        return text
    return to_traditional(text)
