# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""User-interface language: Simplified Chinese (source text) or Traditional Chinese.

All interface strings in the code base are written in Simplified Chinese and
passed through :func:`tr` at the point where they are shown. For Traditional
Chinese the lookup order is:

1. an exact entry in ``data/ui_zh_TW.json`` ``"strings"`` (hand-curated
   sentences whose wording differs from a mechanical conversion);
2. otherwise OpenCC ``s2tw`` character conversion (shared with the name
   language in :mod:`zh_variant`) followed by one longest-match pass over the
   ``"phrases"`` table, which swaps mainland software vocabulary for the
   Taiwan equivalents (保存→儲存, 導出→匯出, 文件→檔案 …). Keys are matched
   against the OpenCC output, and replaced text is never re-processed, so an
   identity entry such as 原圖像素→原圖像素 protects a longer word from the
   shorter 圖像→影像 rule. This path also covers f-strings and exception
   messages whose exact text is only known at run time. File names and
   filesystem paths embedded in such text are left untouched.

The active language is resolved from, in order: an explicit
:func:`set_language` call, the ``MOONLABELER_UI_LANG`` environment variable
(used by the test-suite to pin Simplified), the saved preference handed to
:func:`initialize` by ``main()``, and finally the system locale. Changing the
preference takes effect after the application restarts; widgets are not
retranslated live.
"""
import json
import locale
import os
import re
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

# Windows / POSIX paths and bare file names (with a known extension) are kept verbatim
# when a formatted message is converted; a file is not renamed by the interface language.
_PROTECTED = re.compile(
    r"(?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|[\\/])[^\s'\"“”「」()（）：:；;，,。]+"
    r"|[^\s'\"“”「」()（）：:；;，,。\\/]+\.(?:png|jpe?g|tiff?|fits?|fts|svg|csv|moonlabel|lbl|img|npz|json|ini|txt|md|py|log)\b",
    re.IGNORECASE,
)

_language = None
_explicit = False


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


def _system_locale_name():
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
    return name


def system_language():
    """Traditional for zh_TW / zh_HK / zh_MO system locales, Simplified otherwise (incl. zh_MY)."""
    return normalize(_system_locale_name()) or SIMPLIFIED


def resolve(preference=None):
    """Pick the language from the environment, then ``preference``, then the system locale."""
    return normalize(os.environ.get(ENV_VARIABLE)) or normalize(preference) or system_language()


def set_language(code):
    """Fix the active interface language explicitly; unknown codes fall back to Simplified.

    An explicit choice is never overridden by :func:`initialize`.
    """
    global _language, _explicit
    _language = normalize(code) or SIMPLIFIED
    _explicit = True
    return _language


def initialize(preference=None):
    """Apply the start-up resolution (environment, saved preference, locale) unless set explicitly."""
    global _language
    if not _explicit:
        _language = resolve(preference)
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
    phrases = dict(data.get("phrases", {}))
    # One alternation, longest key first: a single pass means a replacement is never
    # re-scanned by a shorter key, and identity entries act as protected words.
    pattern = re.compile("|".join(re.escape(key) for key in sorted(phrases, key=len, reverse=True))) if phrases else None
    return strings, phrases, pattern


def _apply_phrases(text):
    _, phrases, pattern = _table()
    if pattern is None:
        return text
    return pattern.sub(lambda match: phrases[match.group(0)], text)


def _convert_segment(text):
    if not text:
        return text
    return _apply_phrases(zh_variant.to_traditional(text))


@lru_cache(maxsize=8192)
def to_traditional(text):
    """Translate Simplified interface text to Traditional regardless of the active language."""
    strings, _, _ = _table()
    exact = strings.get(text)
    if exact is not None:
        return exact
    pieces = []
    cursor = 0
    for match in _PROTECTED.finditer(text):
        pieces.append(_convert_segment(text[cursor:match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(_convert_segment(text[cursor:]))
    return "".join(pieces)


def tr(text):
    """Return ``text`` in the active interface language.

    ``text`` is the Simplified source string (static literal or an already
    formatted f-string). Empty values and non-strings are returned unchanged.
    """
    if not text or not isinstance(text, str) or current_language() != TRADITIONAL:
        return text
    return to_traditional(text)
