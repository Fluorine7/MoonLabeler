# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""System fonts, label typography settings, and editable SVG export."""
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QFontMetricsF, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from moonlabeler.annotation_style import path_caption_rows
from moonlabeler.app import MainWindow, Annotation, label_font
from moonlabeler.project import Project, export_svg, label_font_families, DEFAULT_FONT_WEIGHT


def test_font_families_are_cjk_capable_on_every_platform():
    assert label_font_families("双语", platform="darwin")[0] == "PingFang SC"
    assert label_font_families("繁体中文", platform="darwin")[0] == "PingFang TC"
    windows = label_font_families("双语", platform="win32")
    assert windows == ["Microsoft YaHei", "Microsoft JhengHei", "Noto Sans SC", "Noto Sans TC", "Segoe UI"]
    assert label_font_families("双语（繁体）", platform="win32") == [
        "Microsoft JhengHei", "Microsoft YaHei", "Noto Sans TC", "Noto Sans SC", "Segoe UI"]
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


@pytest.fixture
def monospace_family():
    QApplication.instance() or QApplication([])
    installed = set(QFontDatabase.families())
    for name in ("Menlo", "Consolas", "DejaVu Sans Mono", "Courier New"):
        if name in installed:
            return name
    pytest.skip("No installed monospace test font")


def test_custom_font_is_applied_to_original_labels_and_exports(tmp_path, monospace_family):
    family = monospace_family
    window = MainWindow()
    window.error = lambda message: (_ for _ in ()).throw(AssertionError(message))
    try:
        assert window.font_family.findData(family) >= 0
        window.open_project(str(Path(__file__).parents[1]/"examples/demo.moonlabel"))
        assert window.font_family.currentData() == ""
        label = window.annotation_items[0]
        fid = label.feature["id"]
        caption = "月溪 · Moon"
        window.project.labels[fid] = {"text": caption, "position": list(label.pos().toTuple())}
        window.refresh_annotations()
        default_png = tmp_path/"default.png"
        window.render_png(default_png)

        window.font_family.setCurrentIndex(window.font_family.findData(family))
        assert window.style_pending and window.project.font_family == ""
        window.apply_label_settings()
        label = next(item for item in window.annotation_items if item.feature["id"] == fid)
        assert label.text == caption
        assert list(label.pos().toTuple()) == window.project.labels[fid]["position"]
        assert QFontInfo(label.font).family() == family
        units, _, _, _, faces = path_caption_rows(window.project, label.feature, caption, label.font_size)[0]
        assert {face for unit, face in zip(units, faces) if unit.isascii() and unit.isalpha()} == {family}

        custom_png = tmp_path/"custom.png"
        window.render_png(custom_png)
        assert custom_png.read_bytes() != default_png.read_bytes()
        svg = tmp_path/"custom.svg"
        export_svg(svg, window.image, window.annotation_entries(), window.project, window.annotation_leaders())
        ns = {"s": "http://www.w3.org/2000/svg"}
        root = ET.parse(svg).find('.//s:g[@id="annotations"]', ns)
        assert root.attrib["font-family"] == family
        text = root.find(f'.//s:g[@id="feature-{fid}"]//s:text', ns)
        assert "".join(text.itertext()) == caption
        # Some Windows installations lack an East Asian font. Require the
        # export to retain the fallback wherever Qt actually provides one.
        cjk_face = next(face for unit, face in zip(units, faces) if "月" in unit)
        if cjk_face != family:
            assert any("月" in span.text and span.get("font-family") == cjk_face for span in text.findall("s:tspan", ns))

        saved = tmp_path/"custom.moonlabel"
        window.project.save(saved)
        restored = Project.load(saved)
        assert restored.font_family == family
        restored.art_style = "manuscript"
        window.project = restored
        window.sync_controls()
        assert not window.font_family.isEnabled() and window.font_family.currentData() == family
        assert family not in label_font(24, restored).families()
    finally:
        window.dirty = False
        window.close()


def test_mixed_font_svg_keeps_native_separator_spacing(tmp_path, monospace_family):
    size = 46
    feature = dict(id="r", name="Rima Ariadaeus", kind="Rima, rimae", diameter=85.)
    project = Project(font_family=monospace_family, font_percent=None, font_size=size,
                      language="双语（繁体）", crater_outlines=False)
    x, y = 30, 65
    image = np.zeros((150, 960, 3), np.uint8)
    path = tmp_path/"bilingual.svg"
    native_right, svg_right = [], []
    for separator in (" · ", "—"):
        caption = f"月溪{separator}Rima Ariadaeus"
        project.labels["r"] = {"text": caption}
        label = Annotation(feature, (2, 2), caption, project, lambda *a: None, lambda *a: None)
        export_svg(path, image, [(feature, (2, 2), (x, y))], project, leaders={"r": (2, 2, 5, 5)})
        rendered = QImage(image.shape[1], image.shape[0], QImage.Format.Format_RGB32)
        rendered.fill(0xff000000)
        painter = QPainter(rendered)
        QSvgRenderer(str(path)).render(painter)
        painter.end()
        pixels = np.asarray(rendered.constBits()).reshape(*image.shape[:2], 4)
        _, ink_x = np.where(pixels[40:, :, :3].max(axis=2) > 160)
        bounds = label.path.boundingRect().translated(x, y)
        assert (ink_x.min(), ink_x.max()+1) == pytest.approx((bounds.left(), bounds.right()), abs=size/6)
        native_right.append(bounds.right())
        svg_right.append(ink_x.max()+1)
    # Qt SVG rasterizes text, while the preview paints vector outlines.
    # Comparing the same label with two separators cancels the platform's
    # common raster offset and still catches incorrect fallback spacing.
    assert svg_right[0]-svg_right[1] == pytest.approx(native_right[0]-native_right[1], abs=2)


def test_missing_font_uses_defaults_without_losing_project_choice(tmp_path):
    QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        missing = "MoonLabeler Missing Font 0459"
        path = tmp_path/"portable.moonlabel"
        Project(font_family=missing, language="双语（繁体）").save(path)
        window.project = Project.load(path)
        window.sync_controls()
        assert window.font_family.currentData() == missing
        assert missing in window.font_family.currentText() and window.font_family.currentText() != missing
        assert window.annotation_settings()["font_family"] == missing
        default = label_font(24, Project(language=window.project.language))
        unavailable = label_font(24, window.project)
        assert QFontInfo(unavailable).family() == QFontInfo(default).family()
        assert QFontMetricsF(unavailable).horizontalAdvance("月球 · Moon") == QFontMetricsF(default).horizontalAdvance("月球 · Moon")
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["style"]["font_family"]
        path.write_text(json.dumps(data), encoding="utf-8")
        window.project = Project.load(path)
        window.sync_controls()
        assert window.font_family.currentData() == window.project.font_family == ""
        assert window.font_family.findData(missing) < 0
    finally:
        window.dirty = False
        window.close()
