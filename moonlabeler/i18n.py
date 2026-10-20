# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""User-interface language: Simplified Chinese (source text), Traditional Chinese or English.

All interface strings in the code base are written in Simplified Chinese and
passed through :func:`tr` at the point where they are shown. Messages with
variable parts are written as one template and shown with :func:`trf`, which
translates the template first and inserts the values afterwards, so file
names and numbers are never rewritten and every language sees one sentence.

For Traditional Chinese the lookup order is:

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

English has no mechanical conversion, so every sentence is looked up in
``data/ui_en.json``:

1. ``"strings"``: exact source text → English. This covers static ``tr()``
   literals, :func:`trf` templates (keyed on the template with its ``{name}``
   placeholders), project-value captions and constant exception messages.
2. ``"templates"``: only for text that is already formatted before it reaches
   :func:`tr`, i.e. f-string exception messages raised by the core modules and
   :func:`moonlabeler.compute.status`. Each key's ``{name}`` placeholders match
   any text; the whole message must match, and the captured pieces are looked
   up once more (one level) before being inserted into the English template.
   Keys with more literal text are tried first.
3. Otherwise, or while an entry's value is still empty, the source text is
   shown unchanged.

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
ENGLISH = "en"
LANGUAGES = (SIMPLIFIED, TRADITIONAL, ENGLISH)
# Native-script names for the language picker; never passed through tr().
LANGUAGE_NAMES = {SIMPLIFIED: "简体中文", TRADITIONAL: "繁體中文", ENGLISH: "English"}
ENV_VARIABLE = "MOONLABELER_UI_LANG"
PREFERENCE_KEY = "ui/language"
DATA_PATH = Path(__file__).resolve().parent / "data" / "ui_zh_TW.json"
EN_DATA_PATH = Path(__file__).resolve().parent / "data" / "ui_en.json"

_ALIASES = {
    SIMPLIFIED: ("zh-cn", "zh_cn", "zh-hans", "zh_hans", "zh-sg", "zh_sg", "zh", "simplified", "简体中文", "簡體中文"),
    TRADITIONAL: ("zh-tw", "zh_tw", "zh-hant", "zh_hant", "zh-hk", "zh_hk", "zh-mo", "zh_mo", "traditional", "繁體中文", "繁体中文"),
    ENGLISH: ("en", "en-us", "en_us", "en-gb", "en_gb", "english"),
}
# Any other English locale (en_AU, en-IN …) and Windows names such as "English_United States".
_ENGLISH_LOCALE = re.compile(r"en(?:[-_]|$)|english")
# Chinese locales without a Traditional region (zh_MY, Windows "Chinese (Simplified)_…") keep the
# Simplified source text, as before; so do "C" / "POSIX", which carry no language at all.
_SOURCE_LOCALES = re.compile(r"zh|chinese|c$|posix$")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Windows / POSIX paths and bare file names (with a known extension) are kept verbatim
# when a formatted message is converted; a file is not renamed by the interface language.
_PROTECTED = re.compile(
    # Drive-letter, dot-relative, UNC and POSIX-absolute paths. A bare slash between Chinese
    # words (长/短半轴, 阿波罗 / 嫦娥) is ordinary punctuation, so a leading slash only counts
    # when an ASCII path segment follows it.
    r"(?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|[\\/]{2}|/(?=[A-Za-z0-9_.~-]))[^\s'\"“”「」()（）：:；;，,。]+"
    r"|[^\s'\"“”「」()（）：:；;，,。\\/]+\.(?:png|jpe?g|tiff?|fits?|fts|svg|csv|moonlabel|lbl|img|npz|json|ini|txt|md|py|log)\b",
    re.IGNORECASE,
)

_language = None
_explicit = False


def _locale_text(code):
    text = str(code).strip().lower()
    # Strip encodings such as ``zh_TW.UTF-8`` reported by locale.getlocale().
    return text.split(".")[0].split("@")[0]


def normalize(code):
    """Map a language code or label to ``zh-CN`` / ``zh-TW`` / ``en``; ``None`` when unknown."""
    if not code:
        return None
    text = _locale_text(code)
    for language, aliases in _ALIASES.items():
        if text in aliases:
            return language
    if _ENGLISH_LOCALE.match(text):
        return ENGLISH
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
    """Language for the system locale.

    Traditional for zh_TW / zh_HK / zh_MO, Simplified for every other Chinese locale
    (incl. zh_MY) and when no locale is reported, English for any other language.
    """
    name = _system_locale_name()
    if not name:
        return SIMPLIFIED
    language = normalize(name)
    if language:
        return language
    if _SOURCE_LOCALES.match(_locale_text(name)):
        return SIMPLIFIED
    return ENGLISH


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


def is_english():
    return current_language() == ENGLISH


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


@lru_cache(maxsize=None)
def _english_table():
    """``(strings, templates)`` from ``ui_en.json``; entries still empty are left out."""
    try:
        with open(EN_DATA_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        data = {}
    strings = {key: value for key, value in data.get("strings", {}).items() if value}
    templates = {key: value for key, value in data.get("templates", {}).items() if value}
    return strings, templates


@lru_cache(maxsize=None)
def _template_pattern(key):
    """Compile a template key: ``{name}`` matches any text, everything else literally."""
    parts = []
    seen = set()
    cursor = 0
    for match in _PLACEHOLDER.finditer(key):
        parts.append(re.escape(key[cursor:match.start()]))
        name = match.group(1)
        parts.append(f"(?P={name})" if name in seen else f"(?P<{name}>.+?)")
        seen.add(name)
        cursor = match.end()
    parts.append(re.escape(key[cursor:]))
    return re.compile("".join(parts), re.DOTALL)


def _literal_length(key):
    return len(_PLACEHOLDER.sub("", key))


def to_english(text, _nested=False):
    """Translate Simplified interface text to English regardless of the active language.

    Exact ``strings`` entries first, then ``templates`` (most literal text first) whose
    captured pieces are translated once more; unknown text is returned unchanged.
    """
    strings, templates = _english_table()
    exact = strings.get(text)
    if exact is not None:
        return exact
    for key in sorted(templates, key=_literal_length, reverse=True):
        match = _template_pattern(key).fullmatch(text)
        if match is None:
            continue
        values = match.groupdict()
        if not _nested:
            values = {name: to_english(value, _nested=True) for name, value in values.items()}
        try:
            return templates[key].format(**values)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def tr(text):
    """Return ``text`` in the active interface language.

    ``text`` is the Simplified source string (static literal, a :func:`trf`
    template or an already formatted exception message). Empty values and
    non-strings are returned unchanged.
    """
    if not text or not isinstance(text, str):
        return text
    language = current_language()
    if language == TRADITIONAL:
        return to_traditional(text)
    if language == ENGLISH:
        return to_english(text)
    return text


def trf(template, *args, **kwargs):
    """Translate ``template`` and then fill in its ``{…}`` fields.

    Values are inserted after translation, so numbers, file names and paths are
    never rewritten; pass Chinese values through :func:`tr` before handing them in.
    A translation whose fields do not match falls back to the source template.
    """
    translated = tr(template)
    try:
        return translated.format(*args, **kwargs)
    except (KeyError, IndexError, ValueError):
        return template.format(*args, **kwargs)
