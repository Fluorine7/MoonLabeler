# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler.project import Project, export_svg
from moonlabeler.sources import load_catalog, read_image
from moonlabeler.geometry import Geometry


def test_style_edits_wait_for_generate_and_preserve_dragged_label(monkeypatch):
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.error = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.open_project(str(Path(__file__).parents[1]/"examples/demo.moonlabel"))
    assert f"{window.project.font_size} px" in window.font_pixels_hint.text()
    item = window.annotation_items[0]
    fid = item.feature["id"]
    item.setPos(122, 234)
    previous = window.project.language, window.project.max_labels, window.project.font_size
    refreshes = []
    refresh = window.refresh_annotations
    monkeypatch.setattr(window, "refresh_annotations", lambda: (refreshes.append(True), refresh()))
    window.language.setCurrentText("中文")
    window.maximum.setValue(240)
    window.font_size.setValue(1.8)
    assert not refreshes, "Editing settings regenerated every label before Apply"
    assert (window.project.language, window.project.max_labels, window.project.font_size) == previous
    window.generate_labels_button.click()
    assert len(refreshes) == 1
    assert window.project.language == "中文" and window.project.max_labels == 240
    assert window.project.font_size == round(min(window.image.shape[:2])*.018)
    assert window.project.labels[fid]["position"] == [122, 234]
    assert not window.style_pending
    window.dirty = False
    window.close()


def test_relative_font_scales_with_photo_and_survives_save(tmp_path):
    project = Project()
    project.update_font_size((4864, 3811, 3))
    small = project.font_size
    project.update_font_size((9728, 7622, 3))
    assert abs(project.font_size-2*small) <= 1
    project.font_percent = 1.8
    project.update_font_size((8412, 6512, 3))
    assert project.font_size == 117
    project.image_path = str(tmp_path/"photo.png")
    project.save(tmp_path/"photo.moonlabel")
    loaded = Project.load(tmp_path/"photo.moonlabel")
    assert loaded.font_percent == 1.8 and loaded.font_size == 117
    image = np.zeros((400, 600, 3), np.uint8)
    loaded.update_font_size(image.shape)
    export_svg(tmp_path/"photo.svg", image, [({"id": "a", "name": "A"}, [50, 60], [80, 90])], loaded)
    assert f'font-size="{loaded.font_size}"' in (tmp_path/"photo.svg").read_text()


def test_legacy_project_keeps_original_pixel_font_size(tmp_path):
    path = tmp_path/"legacy.moonlabel"
    project = Project(image_path=str(tmp_path/"photo.png"), font_size=80)
    project.save(path)
    data = json.loads(path.read_text())
    data["style"].pop("font_percent", None)
    path.write_text(json.dumps(data))
    loaded = Project.load(path)
    loaded.update_font_size((4864, 3811, 3))
    assert loaded.font_size == 80
    loaded.update_font_size((9728, 7622, 3))
    assert loaded.font_size == 160


def test_chinese_translation_overlays_existing_cached_catalog(tmp_path):
    rows = [{"id": str(i), "name": name, "name_zh": ""} for i, name in
            enumerate(("Mare Insularum", "Copernicus", "Copernicus D", "Unknown A"))]
    (tmp_path/"catalog.json").write_text(json.dumps({"features": rows}))
    translated = load_catalog(tmp_path)
    assert translated[0]["name_zh"] == "岛海"
    assert translated[1]["name_zh"] == "哥白尼"
    assert translated[2]["name_zh"] == "哥白尼 D"
    assert translated[3]["name_zh"] == ""
    assert json.loads((tmp_path/"catalog.json").read_text())["features"] == rows


def test_previous_chinese_names_remain_searchable():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    feature = next(f for f in window.catalog if f["name"] == "Aristarchus")
    assert feature["name_zh"] == "阿利斯塔克"
    window.search_features("阿里斯塔克斯")
    assert window.feature_list.count() and "Aristarchus" in window.feature_list.item(0).text()
    window.search_crater_features("阿里斯塔克斯")
    assert window.crater_feature.findData(feature["id"]) >= 0
    window.search_terrain_features("阿里斯塔克斯")
    assert window.terrain_center.findData(feature["id"]) >= 0
    window.dirty = False
    window.close()


def test_photo_lighting_keeps_visible_shadowed_crater_and_rejects_black_region():
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([-1., 0, 0]), 384400, "2026-08-07T15:00:00+00:00")
    project = Project(geometry=geometry, matrix=np.array([[200., 0, 200], [0, 200., 200]]), min_diameter=0)
    catalog = [dict(id="visible", name="Bright rim", lat=0, lon=0, diameter=180, kind="Crater, craters"),
               dict(id="dark", name="Black region", lat=0, lon=25, diameter=10, kind="Crater, craters")]
    # An unlit center with a clearly illuminated rim. Dates cannot describe
    # local terrain shadows; a genuinely black patch must remain excluded.
    image = np.zeros((400, 400, 3), np.uint8)
    yy, xx = np.ogrid[:400, :400]
    radius = np.hypot(xx-200, yy-200)
    image[(radius > 9) & (radius < 14)] = 180
    assert not project.visible_features(catalog, image.shape)
    assert [f["id"] for f, xy in project.visible_features(catalog, image.shape, image=image)] == ["visible"]


def test_real_copernicus_photo_includes_main_crater_with_lighting_filter():
    source = Path(__file__).parents[1]
    photograph = source/"0807.jpg"
    if not photograph.exists():
        import pytest
        pytest.skip("User's photograph is unavailable")
    pose = json.loads((Path(__file__).parent/"fixtures/0807-registration.json").read_text())
    image = read_image(photograph)
    project = Project(geometry=Geometry.from_dict(pose["geometry"]), matrix=np.array(pose["matrix"]), min_diameter=5)
    features = project.visible_features(load_catalog(source/".cache"), image.shape, image=image)
    names = {f["name"] for f, xy in features}
    assert {"Copernicus", "Reinhold", "Gambart"} <= names
    center = next(xy for f, xy in features if f["name"] == "Copernicus")
    assert 1550 < center[0] < 1720 and 2300 < center[1] < 2530


def test_default_label_count_supports_whole_moon():
    assert Project().max_labels >= 200


def test_large_projected_crater_has_elliptical_outline_and_svg_path(tmp_path):
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400, "2026-08-07T15:00:00+00:00")
    project = Project(geometry=geometry, matrix=np.array([[1500., 0, 600], [0, 1500., 600]]))
    shape = (1200, 1200, 3)
    project.update_font_size(shape)
    big = dict(id="big", name="Big", lat=0, lon=45, diameter=240, kind="Crater, craters")
    small = dict(big, id="small", name="Small", diameter=8)
    outline = project.crater_outline(big, shape)
    assert outline and not project.crater_outline(small, shape)
    points = np.array(outline[0])
    assert .65 < np.ptp(points[:, 0])/np.ptp(points[:, 1]) < .8
    export_svg(tmp_path/"rings.svg", np.zeros(shape, np.uint8), [(big, [400, 400], [500, 500])], project)
    assert 'class="crater-outline"' in (tmp_path/"rings.svg").read_text()
    project.crater_outlines = False
    assert not project.crater_outline(big, shape)
