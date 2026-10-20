"""Simplified-to-Traditional Chinese conversion for label names.

The bundled nomenclature snapshot stores Simplified Chinese names. Users in
Taiwan, Hong Kong and Macau can pick a Traditional name language; names are
converted on the fly with OpenCC (pure-Python port) and cached. The optional
dependency is guarded so the rest of the application keeps working without it,
in which case Simplified names are shown unchanged.
"""
from functools import lru_cache

try:
    import opencc
except ImportError:  # pragma: no cover - exercised only when the extra is missing
    opencc = None

# OpenCC's Taiwan variant table picks a few characters that are not the
# customary spelling in lunar nomenclature; override them after conversion.
# Checked against the full 10,431-record snapshot: these are the only two.
OVERRIDES = {"溼": "濕", "巖": "岩"}

_converter = None


def available():
    """Return True when the OpenCC port is importable."""
    return opencc is not None


def _get_converter():
    global _converter
    if _converter is None and opencc is not None:
        _converter = opencc.OpenCC("s2tw")
    return _converter


@lru_cache(maxsize=None)
def to_traditional(text):
    """Convert ``text`` to Traditional Chinese; return it unchanged if OpenCC is missing."""
    if not text:
        return text
    converter = _get_converter()
    if converter is None:
        return text
    converted = converter.convert(text)
    for source, target in OVERRIDES.items():
        converted = converted.replace(source, target)
    return converted
