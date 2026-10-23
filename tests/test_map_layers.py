# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Projection, alpha masks, backward compatibility and reusable presentation layers."""
import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QSlider, QStyle, QStyleOptionSlider
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtSvg import QSvgRenderer

from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry, surface_vectors
from moonlabeler.map_layers import (photo_coordinates, grid_lines, sample_elevation, colorize_elevation,
                                    MapLayers, ElevationRaster, build_map_layers, legend_rect)
from moonlabeler.project import Project, export_svg
from moonlabeler.terrain import ElevationMap


def project(**options):
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([.6, .8, 0]), 384400., "2026-01-01T00:00:00+00:00")
    return Project(geometry=geometry, matrix=np.array([[240., 0, 300.], [0, 240., 300.]]), **options)


def dem():
    # A linear geographic field permits exact bilinear height expectations.
    lat = 90-(np.arange(360)+.5)/2
    lon = -180+(np.arange(720)+.5)/2
    return ElevationMap((lat[:, None]*.03+lon[None, :]*.015).astype(np.float32), 90, -180, 2)


@pytest.mark.parametrize("mirrored", [False, True])
def test_grid_and_inverse_follow_rotated_mirrored_distorted_photo(mirrored):
    p = project(grid_spacing=15, map_lit_only=False)
    angle = .7
    p.matrix[:, :2] = 210*np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    if mirrored:
        p.matrix[:, 0] *= -1
    p.identification = {"lens_distortion": {"center": [280., 310.], "scale": 250., "k": .2}}
    xy, _, _ = p.geometry.project([-35, 0, 42], [20, -15, 35])
    assert np.allclose(photo_coordinates(p, p.photo_points(xy)), xy, atol=1e-10)
    curves = grid_lines(p, (600, 600, 3))
    meridian = next(c for c in curves if c.label == "30°E")
    points = np.concatenate(meridian.segments)
    lat, lon, visible = p.geometry.unproject(photo_coordinates(p, points))
    assert visible.all() and np.max(abs(lon-30)) < .003
    for curve in curves:
        points = np.concatenate(curve.segments)
        assert np.isfinite(points).all() and (points >= -1e-8).all() and (points <= 600+1e-8).all()


def test_grid_clips_to_cropped_photo_and_sunlit_front_hemisphere():
    p = project(grid_spacing=10)
    p.matrix[:, 2] = [80, 50]
    curves = grid_lines(p, (140, 200, 3))
    assert curves
    for curve in curves:
        points = np.concatenate(curve.segments)
        lat, lon, visible = p.geometry.unproject(photo_coordinates(p, points))
        assert visible.all()
        assert (surface_vectors(lat, lon) @ p.geometry.sun >= -1e-5).all()
        assert (points[:, 0] >= -1e-8).all() and (points[:, 0] <= 200+1e-8).all()
        assert (points[:, 1] >= -1e-8).all() and (points[:, 1] <= 140+1e-8).all()


def test_photo_lighting_overrides_wrong_solar_geometry_for_grid():
    p = project(grid_spacing=15)
    p.geometry.sun = np.array([-1., 0, 0])
    image = np.zeros((600, 600, 3), np.uint8)
    image[200:500, 100:500] = 180
    matrix = p.matrix.copy()
    curves = grid_lines(p, image.shape, image=image)
    assert curves, "Visible photographed terrain must not be clipped by an incorrect date"
    for curve in curves:
        points = np.concatenate(curve.segments)
        assert points[:, 1].min() >= 199 and points[:, 1].max() <= 501
        assert points[:, 0].min() >= 99 and points[:, 0].max() <= 501
    assert np.array_equal(p.matrix, matrix) and np.array_equal(p.geometry.sun, [-1., 0, 0])


def test_photo_lighting_keeps_bright_ground_and_enclosed_shadow_but_excludes_dark_region():
    p = project(elevation_enabled=True)
    p.matrix = np.array([[26., 0, 32.], [0, 26., 32.]])
    p.geometry.sun = np.array([-1., 0, 0])
    image = np.zeros((64, 64, 3), np.uint8)
    image[12:52, 12:52] = 180
    image[25:39, 25:39] = 0  # A shadowed floor enclosed by a visible bright rim.
    original = image.copy()
    raster = sample_elevation(p, image.shape, dem(), image=image)
    assert not raster.sunlit.any(), "The test's date intentionally places the visible disk in darkness"
    rgba = colorize_elevation(raster, p, image=image)
    assert rgba[20, 32, 3] > 0 and rgba[32, 32, 3] > 0
    assert np.isfinite(raster.heights[32, 8]) and rgba[32, 8, 3] == 0
    p.map_lit_only = False
    assert colorize_elevation(raster, p)[32, 8, 3] > 0
    assert np.array_equal(image, original)


def test_real_clavius_photo_does_not_lose_bright_ground_to_example_date():
    root = Path(__file__).parents[1]
    p = Project.load(root/"examples/auto-clavius.moonlabel")
    source = Path(p.image_path)
    dem_path = root/".cache/terrain/LDEM_16.LBL"
    if not source.exists() or not dem_path.exists() or not dem_path.with_suffix(".IMG").exists():
        pytest.skip("Local Clavius photo and LOLA cache are unavailable")
    with Image.open(source) as photo:
        image = np.array(photo.convert("RGB"))
    elevation = ElevationMap.load(dem_path)
    try:
        raster = sample_elevation(p, image.shape, elevation, image=image, max_edge=256)
    finally:
        elevation.close()
    h, w = raster.heights.shape
    luminance = np.asarray(Image.fromarray(image).convert("L").resize((w, h), Image.Resampling.BILINEAR))
    bright = (luminance > max(20, np.percentile(luminance, 95)*.25)) & np.isfinite(raster.heights)
    assert (bright & ~raster.sunlit).any(), "The real example must exercise the model/photo disagreement"
    rgba = colorize_elevation(raster, p, image=image)
    assert (rgba[bright, 3] > 0).all(), "Clearly photographed bright ground must remain visible"


@pytest.mark.parametrize("terrain", [False, True])
def test_elevation_uses_registered_surface_and_preserves_missing_pixels(terrain):
    p = project(elevation_enabled=True, map_lit_only=False)
    p.matrix = np.array([[26., 0, 32.], [0, -26., 32.]])
    p.identification = {"lens_distortion": {"center": [32., 32.], "scale": 30., "k": .18}}
    p.projection_surface = "terrain" if terrain else "sphere"
    elevation = dem()
    raster = sample_elevation(p, (64, 64, 3), elevation)
    assert np.isnan(raster.heights[0, 0])
    # Pixel-centre coordinates are independently projected back from the known
    # geographic test field. Terrain intersection must use the sampled height.
    y, x = np.mgrid[20:40, 20:40]
    pixels = np.column_stack((x.ravel()+.5, y.ravel()+.5))
    view_xy = photo_coordinates(p, pixels)
    if not terrain:
        lat, lon, _ = p.geometry.unproject(view_xy)
        expected = lat*.03+lon*.015
        assert np.allclose(raster.heights[20:40, 20:40].ravel(), expected, atol=1e-6)
    else:
        from moonlabeler.terrain_view import TerrainView
        lat, lon, valid = TerrainView.from_geometry(p.geometry, elevation).unproject(view_xy)
        back, _, _ = p.geometry.project(lat, lon, raster.heights[20:40, 20:40].ravel())
        assert valid.all() and np.max(abs(p.photo_points(back)-pixels)) < .001
    rgba = colorize_elevation(raster, p)
    assert rgba[0, 0, 3] == 0 and rgba[32, 32, 3] == round(255*p.elevation_opacity)
    p.map_lit_only = True
    assert not colorize_elevation(raster, p)[~raster.sunlit, 3].any()


def test_regional_dem_has_transparent_uncovered_area_and_rejects_no_coverage():
    p = project(elevation_enabled=True, map_lit_only=False)
    p.matrix = np.array([[26., 0, 32.], [0, 26., 32.]])
    regional = ElevationMap(np.ones((20, 20)), 10, -10, 1)
    raster = sample_elevation(p, (64, 64, 3), regional)
    rgba = colorize_elevation(raster, p)
    assert rgba[32, 32, 3] and not rgba[32, 45, 3]
    backside = ElevationMap(np.ones((20, 20)), 10, 170, 1)
    with pytest.raises(ValueError, match="覆盖"):
        sample_elevation(p, (64, 64, 3), backside)


def test_elevation_colours_keep_photo_relief_at_high_opacity():
    p = project(elevation_enabled=True, elevation_opacity=.85, map_lit_only=False)
    heights = np.zeros((20, 20), np.float32)
    heights[0, 0] = np.nan
    raster = ElevationRaster(heights, np.ones((20, 20), bool), "test", 1.)
    photo = np.full((80, 80, 3), 220, np.uint8)
    photo[:, :40] = 45
    before = photo.copy()
    colours = colorize_elevation(raster, p, image=photo)
    assert colours[10, 5, :3].mean() < colours[10, 15, :3].mean()*.6
    assert colours[0, 0, 3] == 0 and colours[10, 5, 3] == round(255*.85)
    assert np.array_equal(photo, before)


def test_optional_settings_roundtrip_and_legacy_defaults(tmp_path):
    p = project(art_style="manuscript", grid_spacing=15, grid_opacity=.2, elevation_enabled=True,
                elevation_palette="antique", elevation_opacity=.55, map_lit_only=False,
                image_path=str(tmp_path/"image.png"), color="#aabbcc", font_weight="bold",
                labels={"42": {"text": "A & B", "position": [30, 40], "hidden": True}})
    path = tmp_path/"map.moonlabel"
    p.save(path)
    loaded = Project.load(path)
    fields = ("art_style", "grid_spacing", "grid_opacity", "elevation_enabled", "elevation_palette",
              "elevation_opacity", "map_lit_only")
    assert all(getattr(p, f) == getattr(loaded, f) for f in fields)
    assert loaded.labels == p.labels and loaded.color == p.color and loaded.font_weight == "bold"
    data = json.loads(path.read_text())
    for f in fields:
        del data["style"][f]
    path.write_text(json.dumps(data))
    legacy = Project.load(path)
    assert legacy.art_style == "standard" and legacy.grid_spacing == 0 and not legacy.elevation_enabled


@pytest.mark.parametrize("key,value", [("grid_spacing", True), ("grid_spacing", 20), ("grid_spacing", "15"),
    ("grid_opacity", 1.1), ("elevation_opacity", float("nan")), ("elevation_opacity", True),
    ("elevation_enabled", "false"), ("map_lit_only", 1), ("art_style", []), ("elevation_palette", None)])
def test_invalid_layer_settings_rejected_before_open(tmp_path, key, value):
    path = tmp_path/"invalid.moonlabel"
    Project(image_path=str(tmp_path/"image.png")).save(path)
    data = json.loads(path.read_text())
    data["style"][key] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="style"):
        Project.load(path)


@pytest.fixture
def window():
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.error = lambda e: (_ for _ in ()).throw(AssertionError(str(e)))
    win.open_project(str(Path(__file__).parents[1]/"examples/demo.moonlabel"))
    yield win
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(5)
    win.dirty = False
    win.close()


def test_art_toggle_preserves_edits_calibration_and_original_pixels(window, tmp_path):
    win = window
    item = win.annotation_items[0]
    item.setPos(120, 240)
    win.project.labels[item.feature["id"]]["text"] = "月面 · A  &  B"
    win.project.color, win.project.font_weight = "#abcded", "bold"
    win.sync_controls()
    win.refresh_annotations()
    edits, anchors = deepcopy(win.project.labels), deepcopy(win.project.anchors)
    matrix = win.project.matrix.copy()
    original = tmp_path/"before.png"
    win.render_png(original)
    win.art_style.setCurrentIndex(1)
    assert win.project.art_style == "standard" and win.style_pending
    win.apply_label_settings()
    assert win.project.art_style == "manuscript" and not win.font_weight.isEnabled()
    assert win.project.color == "#abcded" and win.project.font_weight == "bold"
    assert all(item.boundingRect().contains(item.ornament.boundingRect()) for item in win.annotation_items)
    for item in win.annotation_items:
        if item.outline_segments:
            assert not item.marker.isVisible()
    win.art_style.setCurrentIndex(0)
    win.apply_label_settings()
    win.render_png(tmp_path/"after.png")
    assert np.array_equal(np.array(Image.open(original)), np.array(Image.open(tmp_path/"after.png")))
    assert win.project.labels == edits and win.project.anchors == anchors and np.array_equal(win.project.matrix, matrix)


def test_async_elevation_cache_and_png_svg_layer_contract(window, tmp_path, monkeypatch):
    from moonlabeler import app as app_module
    win = window
    data = dem()
    dem_path = tmp_path/"test.npz"
    np.savez(dem_path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    win.dem_path = str(dem_path)
    calls = []
    def sample(p, shape, data, *, image=None):
        calls.append(True)
        return sample_elevation(p, shape, data, max_edge=128, image=image)
    monkeypatch.setattr(app_module, "sample_elevation", sample)
    win.art_style.setCurrentIndex(1)
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(30))
    win.elevation_toggle.setChecked(True)
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
    assert not win.busy and win.map_layers.elevation is not None and len(calls) == 1
    items, positions = list(win.annotation_items), [item.pos() for item in win.annotation_items]
    map_items = list(win.map_items)
    with monkeypatch.context() as fast:
        fast.setattr(app_module, "colorize_elevation", lambda *a, **k: pytest.fail("Opacity must reuse existing colours"))
        for value in (0, 85, 100):
            win.elevation_opacity.setValue(value)
            assert win.project.elevation_opacity == value/100
            assert win.map_layers.elevation[:, :, 3].max() == round(255*value/100)
            item = next(item for item in map_items if getattr(item, "map_layer", None) == "elevation")
            displayed = item.pixmap().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            alpha = np.asarray(displayed.constBits()).reshape(displayed.height(), displayed.width(), 4)[:, :, 3]
            assert np.array_equal(alpha, win.map_layers.elevation[:, :, 3])
    assert len(calls) == 1 and win.map_items == map_items
    assert win.annotation_items == items and [item.pos() for item in items] == positions
    assert not win.style_pending
    win.elevation_opacity.setValue(60)
    win.elevation_palette.setCurrentIndex(1)
    win.apply_label_settings()
    assert len(calls) == 1, "Cosmetic changes must reuse the sampled geographic raster"
    assert win.map_layers.elevation[:, :, 3].max() == 153
    # A changed registration must never export the previous geographic raster.
    win.project.matrix[:, 2] += [3, 0]
    with pytest.raises(ValueError, match="尚未生成"):
        win.render_png(tmp_path/"stale.png")
    win.refresh_annotations()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
    assert not win.busy and len(calls) == 2
    before = win.image.copy()
    win.render_png(tmp_path/"layers.png")
    svg = tmp_path/"layers.svg"
    export_svg(svg, win.image, win.annotation_entries(), win.project, win.annotation_leaders(), layers=win.map_layers)
    assert QSvgRenderer(str(svg)).isValid()
    root = ET.parse(svg)
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert root.find('.//s:g[@id="selenographic-grid"]', ns) is not None
    assert root.find('.//s:g[@id="elevation-legend"]', ns) is not None
    assert len(root.findall('.//s:path[@class="caption-ornament"]', ns)) == len(win.annotation_items)
    node = root.find('.//s:image[@id="elevation-overlay"]', ns)
    encoded = node.get("{http://www.w3.org/1999/xlink}href").split(",", 1)[1]
    assert np.array_equal(np.array(Image.open(io.BytesIO(base64.b64decode(encoded)))), win.map_layers.elevation)
    assert np.array_equal(win.image, before)
    assert Image.open(tmp_path/"layers.png").size == (win.image.shape[1], win.image.shape[0])
    assert not np.array_equal(np.array(Image.open(tmp_path/"layers.png")).astype(np.uint8), before)
    assert win.project.terrain_path == str(dem_path)


def test_opacity_sliders_apply_once_then_update_without_layout_or_other_pending_edits(window, tmp_path, monkeypatch):
    win = window
    assert isinstance(win.grid_opacity, QSlider) and isinstance(win.elevation_opacity, QSlider)
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(15))
    win.grid_opacity.setValue(60)
    assert win.project.grid_spacing == 0 and win.project.grid_opacity == .45 and win.style_pending
    win.apply_label_settings()
    assert win.project.grid_spacing == 15 and win.project.grid_opacity == .6
    items, positions = list(win.annotation_items), [item.pos() for item in win.annotation_items]
    map_items = list(win.map_items)
    old_font = win.project.font_percent
    win.font_size.setValue(2.4)
    assert win.style_pending
    monkeypatch.setattr(win, "refresh_annotations", lambda: pytest.fail("Opacity must not regenerate labels"))
    for value in (0, 35, 85, 100):
        win.grid_opacity.setValue(value)
        assert win.project.grid_opacity == value/100 and win.map_items == map_items
        assert all(item.opacity() == value/100 for item in map_items)
        assert win.annotation_items == items and [item.pos() for item in items] == positions
    assert win.style_pending and win.project.font_percent == old_font and win.dirty
    path = tmp_path/"live-opacity.moonlabel"
    win.project.save(path)
    assert Project.load(path).grid_opacity == 1.


def test_dragging_opacity_slider_updates_before_mouse_release(window):
    win = window
    win.workspace_tabs.setCurrentIndex(1)
    win.map_styles_toggle.setChecked(True)
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(15))
    win.apply_label_settings()
    win.show()
    QApplication.processEvents()
    slider = win.grid_opacity
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                          QStyle.SubControl.SC_SliderHandle, slider)
    before = slider.value()
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=handle.center())
    QTest.mouseMove(slider, QPoint(slider.width()-handle.width()-5, handle.center().y()))
    assert slider.value() > before
    assert win.project.grid_opacity == slider.value()/100 and not win.style_pending
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton)


def test_missing_dem_keeps_labels_and_prevents_silent_incomplete_export(window, tmp_path):
    win = window
    win.dem_path = win.project.terrain_path = ""
    existing = [item.feature["id"] for item in win.annotation_items]
    win.elevation_toggle.setChecked(True)
    win.apply_label_settings()
    assert [item.feature["id"] for item in win.annotation_items] == existing
    assert "DEM" in win.map_layer_status.text()
    with pytest.raises(ValueError, match="尚未生成"):
        win.render_png(tmp_path/"missing.png")
    with pytest.raises(ValueError, match="DEM"):
        build_map_layers(win.project, win.image.shape)


def test_apply_retries_failed_elevation_after_source_becomes_available(window, tmp_path):
    win = window
    errors = []
    win.error = errors.append
    path = tmp_path/"recovered-dem.npz"
    win.dem_path = str(path)
    win.elevation_toggle.setChecked(True)
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
    assert errors and win._elevation_failed_key is not None and win.map_layers.elevation is None
    data = dem()
    np.savez(path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
    assert not win.busy and win.map_layers.elevation is not None
    assert len(errors) == 1


@pytest.mark.parametrize("art_style", ["standard", "manuscript"])
def test_svg_halo_keeps_fine_text_legible_and_editable(tmp_path, art_style):
    application = QApplication.instance() or QApplication([])
    path = tmp_path/"caption.svg"
    export_svg(path, np.zeros((160, 400, 3), np.uint8),
               [({"id": "42", "name": "Moon Tycho"}, [0, 0], [30, 50])],
               Project(art_style=art_style, font_weight="normal", font_size=30),
               {"42": (0, 0, 0, 0)})
    result = QImage(400, 160, QImage.Format.Format_RGBA8888)
    result.fill(0xff000000)
    painter = QPainter(result)
    QSvgRenderer(str(path)).render(painter)
    painter.end()
    pixels = np.asarray(result.constBits()).reshape(160, 400, 4)
    # SVG 2 paint-order is ignored by Qt: stroking after the fill previously
    # covered almost all the fine lettering. Check the rendered face itself.
    assert np.count_nonzero(np.all(pixels[45:85, 25:250, :3] > 150, axis=2)) > 150
    captions = ET.parse(path).findall('.//{http://www.w3.org/2000/svg}text')
    assert len(captions) == 1 and captions[0].text == "Moon Tycho"


def test_legend_reserves_space_without_moving_user_pins():
    from moonlabeler.layout import LabelBox, arrange_labels, rect_intersects
    rect = legend_rect((600, 800, 3))
    labels = [LabelBox("automatic", (80, 540), 90, 20, 8),
              LabelBox("pin", (500, 300), 70, 20, 8, fixed=(500, 540))]
    placements, _ = arrange_labels(labels, 800, 600, obstacles=[rect])
    assert "automatic" in placements and not rect_intersects(placements["automatic"], rect)
    assert placements["pin"][:2] == (500, 540)
