# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Pin the interface language to Simplified Chinese for the existing tests.

The GUI tests assert on the Simplified source strings. Without this default a
developer on a zh_TW / zh_HK system (or with a saved Traditional preference)
would see every widget text converted and dozens of unrelated tests fail.
Tests that exercise the Traditional interface call ``i18n.set_language``
explicitly and restore the previous value afterwards.
"""
import os

os.environ.setdefault("MOONLABELER_UI_LANG", "zh-CN")
