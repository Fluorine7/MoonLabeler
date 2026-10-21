# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Pin the interface language to Simplified Chinese for the test-suite.

The GUI tests assert on the Simplified source strings. Without this pin a
developer on a zh_TW / zh_HK system, or with a saved Traditional preference
or ``MOONLABELER_UI_LANG`` in the shell, would see every widget text
converted and dozens of unrelated tests fail. Tests that exercise the
Traditional interface call ``i18n.set_language`` explicitly and restore the
previous value afterwards; tests of the resolution order patch the variable
themselves with ``monkeypatch``.
"""
import os

os.environ["MOONLABELER_UI_LANG"] = "zh-CN"
