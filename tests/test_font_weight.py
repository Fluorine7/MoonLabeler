# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Label font families per platform and the project font-weight option."""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow, Annotation, label_font
from moonlabeler.project import Project, export_svg, label_font_families, DEFAULT_FONT_WEIGHT


def test_font_families_are_cjk_capable_on_every_platform():
    assert label_font_families("双语", platform="darwin")[0] == "PingFang SC"
    assert label_font_families("繁体中文", platform="darwin")[0] == "PingFang TC"
    windows = label_font_families("双语", platform="win32")
    assert windows[0] == "Microsoft YaHei" and "Microsoft JhengHei" in windows
    assert label_font_families("双语（繁体）", platform="win32")[0] == "Microsoft JhengHei"
    assert "PingFang SC" not in windows  # Qt would substitute Tahoma, which has no CJK glyphs.
    assert label_font_families("中文", platform="linux")[0].startswith("Noto Sans CJK")


def test_label_font_defaults_to_bold_and_honours_project_weight():
    QApplication.instance() or QApplication([])
    assert label_font(20).weight() == QFont.Weight.Bold
    assert label_font(20, Project(font_weight="normal")).weight() == QFont.Weight.Normal
    assert label_font(20, Project(font_weight="bold")).weight() == QFont.Weight.Bold
    project = Project(font_size=24)
    feature = dict(id="x", name="Tycho", kind="Crater, craters", diameter=85.)
    item = Annotation(feature, (10, 10), "第谷 · Tycho", project, lambda *a: None, lambda *a: None)
    assert item.font.weight() == QFont.Weight.Bold


def test_project_round_trips_font_weight_and_rejects_unknown(tmp_path):
    image = tmp_path/"moon.png"
    from PIL import Image
    Image.fromarray(np.zeros((40, 40, 3), np.uint8)).save(image)
    project = Project(image_path=str(image), font_weight="normal")
    path = tmp_path/"p.moonlabel"
    project.save(path)
    assert Project.load(path).font_weight == "normal"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["style"]["font_weight"] == "normal"
    data["style"]["font_weight"] = "heavy"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert Project.load(path).font_weight == DEFAULT_FONT_WEIGHT
    del data["style"]["font_weight"]  # Projects written before this option.
    path.write_text(json.dumps(data), encoding="utf-8")
    assert Project.load(path).font_weight == DEFAULT_FONT_WEIGHT


def test_svg_declares_cjk_families_and_weight(tmp_path):
    feature = dict(id="t", name="Tycho", kind="Crater, craters", diameter=85., lat=-43.3, lon=-11.4)
    for weight in ("bold", "normal"):
        project = Project(font_weight=weight, crater_outlines=False)
        path = tmp_path/f"{weight}.svg"
        export_svg(path, np.zeros((100, 100, 3), np.uint8), [(feature, [20, 20], [40, 40])], project)
        text = path.read_text(encoding="utf-8")
        assert f'font-weight="{weight}"' in text
        assert all(family in text for family in label_font_families(project.language))


def test_sidebar_weight_combo_applies_to_project():
    QApplication.instance() or QApplication([])
    window = MainWindow()
    window.error = lambda message: (_ for _ in ()).throw(AssertionError(message))
    try:
        window.open_project(str(Path(__file__).parents[1]/"examples/demo.moonlabel"))
        assert window.font_weight.currentData() == window.project.font_weight == "bold"
        window.font_weight.setCurrentIndex(window.font_weight.findData("normal"))
        assert window.style_pending
        window.apply_label_settings()
        assert window.project.font_weight == "normal"
        assert all(item.font.weight() == QFont.Weight.Normal for item in window.annotation_items)
    finally:
        window.dirty = False
        window.close()
        window.deleteLater()
