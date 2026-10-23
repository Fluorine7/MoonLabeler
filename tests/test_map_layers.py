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
from PySide6.QtWidgets import QApplication, QSlider, QStyle, QStyleOptionSlider, QGraphicsScene
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtSvg import QSvgRenderer

from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry, surface_vectors, unit
from moonlabeler.map_layers import (photo_coordinates, grid_lines, sample_elevation, colorize_elevation,
                                    MapLayers, ElevationRaster, build_map_layers, legend_rect, contour_lines,
                                    terminator_segments, GridLine, ContourLine, resolved_contour_interval)
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
    p = project(grid_spacing=15)
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


def test_grid_clips_to_cropped_photo_and_visible_hemisphere():
    p = project(grid_spacing=10)
    p.matrix[:, 2] = [80, 50]
    curves = grid_lines(p, (140, 200, 3))
    assert curves
    for curve in curves:
        points = np.concatenate(curve.segments)
        lat, lon, visible = p.geometry.unproject(photo_coordinates(p, points))
        assert visible.all()
        assert (points[:, 0] >= -1e-8).all() and (points[:, 0] <= 200+1e-8).all()
        assert (points[:, 1] >= -1e-8).all() and (points[:, 1] <= 140+1e-8).all()


def test_grid_covers_dark_hemisphere_independent_of_solar_geometry():
    p = project(grid_spacing=15)
    original = grid_lines(p, (600, 600, 3))
    p.geometry.sun = -p.geometry.observer
    actual = grid_lines(p, (600, 600, 3))
    assert actual and len(actual) == len(original)
    for before, after in zip(original, actual):
        assert before.segments == after.segments


def test_elevation_fully_covers_bright_and_dark_ground_without_changing_geometry():
    p = project(elevation_enabled=True)
    p.matrix = np.array([[26., 0, 32.], [0, 26., 32.]])
    p.geometry.sun = np.array([-1., 0, 0])
    image = np.zeros((64, 64, 3), np.uint8)
    image[12:52, 12:52] = 180
    image[25:39, 25:39] = 0
    original, matrix = image.copy(), p.matrix.copy()
    raster = sample_elevation(p, image.shape, dem())
    rgba = colorize_elevation(raster, p, image=image)
    assert rgba[20, 32, 3] > 0 and rgba[32, 32, 3] > 0 and rgba[32, 8, 3] > 0
    assert np.array_equal(rgba[:, :, 3] > 0, np.isfinite(raster.heights))
    assert np.array_equal(image, original) and np.array_equal(p.matrix, matrix)
    assert np.array_equal(p.geometry.sun, [-1., 0, 0])


def test_real_clavius_photo_does_not_lose_bright_ground_to_example_date():
    root = Path(__file__).parents[1]
    project_path = root/"examples/auto-clavius.moonlabel"
    if not project_path.exists():
        pytest.skip("Local Clavius project is unavailable")
    p = Project.load(project_path)
    source = Path(p.image_path)
    dem_path = root/".cache/terrain/LDEM_16.LBL"
    if not source.exists() or not dem_path.exists() or not dem_path.with_suffix(".IMG").exists():
        pytest.skip("Local Clavius photo and LOLA cache are unavailable")
    with Image.open(source) as photo:
        image = np.array(photo.convert("RGB"))
    elevation = ElevationMap.load(dem_path)
    try:
        raster = sample_elevation(p, image.shape, elevation, max_edge=256)
    finally:
        elevation.close()
    h, w = raster.heights.shape
    luminance = np.asarray(Image.fromarray(image).convert("L").resize((w, h), Image.Resampling.BILINEAR))
    bright = (luminance > max(20, np.percentile(luminance, 95)*.25)) & np.isfinite(raster.heights)
    rgba = colorize_elevation(raster, p, image=image)
    assert (rgba[bright, 3] > 0).all(), "Clearly photographed bright ground must remain visible"


@pytest.mark.parametrize("terrain", [False, True])
def test_elevation_uses_registered_surface_and_preserves_missing_pixels(terrain):
    p = project(elevation_enabled=True)
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
    assert np.array_equal(rgba[:, :, 3] > 0, np.isfinite(raster.heights))


def test_regional_dem_has_transparent_uncovered_area_and_rejects_no_coverage():
    p = project(elevation_enabled=True)
    p.matrix = np.array([[26., 0, 32.], [0, 26., 32.]])
    regional = ElevationMap(np.ones((20, 20)), 10, -10, 1)
    raster = sample_elevation(p, (64, 64, 3), regional)
    rgba = colorize_elevation(raster, p)
    assert rgba[32, 32, 3] and not rgba[32, 45, 3]
    backside = ElevationMap(np.ones((20, 20)), 10, 170, 1)
    with pytest.raises(ValueError, match="覆盖"):
        sample_elevation(p, (64, 64, 3), backside)


def test_elevation_colours_keep_photo_relief_at_high_opacity():
    p = project(elevation_enabled=True, elevation_opacity=.85)
    heights = np.zeros((20, 20), np.float32)
    heights[0, 0] = np.nan
    raster = ElevationRaster(heights, "test", 1.)
    photo = np.full((80, 80, 3), 220, np.uint8)
    photo[:, :40] = 45
    before = photo.copy()
    colours = colorize_elevation(raster, p, image=photo)
    assert colours[10, 5, :3].mean() < colours[10, 15, :3].mean()*.6
    assert colours[0, 0, 3] == 0 and colours[10, 5, 3] == round(255*.85)
    assert np.array_equal(photo, before)


def test_optional_settings_roundtrip_and_legacy_defaults(tmp_path):
    p = project(art_style="manuscript", grid_spacing=15, grid_opacity=.2, elevation_enabled=True,
                elevation_palette="wilderness", elevation_opacity=.55,
                contour_enabled=True, contour_interval=.25, contour_opacity=.72,
                terminator_enabled=True, terminator_opacity=.83, terminator_source='ephemeris',
                image_path=str(tmp_path/"image.png"), color="#aabbcc", font_weight="bold",
                labels={"42": {"text": "A & B", "position": [30, 40], "hidden": True}})
    path = tmp_path/"map.moonlabel"
    p.save(path)
    loaded = Project.load(path)
    fields = ("art_style", "grid_spacing", "grid_opacity", "elevation_enabled", "elevation_palette",
              "elevation_opacity", "contour_enabled", "contour_interval", "contour_opacity",
              "terminator_enabled", "terminator_opacity", "terminator_source")
    assert all(getattr(p, f) == getattr(loaded, f) for f in fields)
    assert loaded.labels == p.labels and loaded.color == p.color and loaded.font_weight == "bold"
    data = json.loads(path.read_text())
    for f in fields:
        del data["style"][f]
    path.write_text(json.dumps(data))
    legacy = Project.load(path)
    assert legacy.art_style == "standard" and legacy.grid_spacing == 0 and not legacy.elevation_enabled
    assert not legacy.contour_enabled and legacy.contour_interval == 'auto'
    assert not legacy.terminator_enabled and legacy.terminator_opacity == 1.
    assert legacy.terminator_source == 'photo'


def test_automatic_contour_spacing_adapts_to_terrain_density_and_preserves_manual_choice(tmp_path):
    p = project(contour_enabled=True, image_path=str(tmp_path/'photo.png'))
    assert p.contour_interval == 'auto'
    for size in (128, 256, 512):
        x, y = np.meshgrid(np.linspace(0, 1, size), np.linspace(0, 1, size))
        local = ElevationRaster((2*x-1).astype(np.float32), 'local', 1.)
        broad = ElevationRaster((3*np.sin(x*30*np.pi)*np.cos(y*26*np.pi)).astype(np.float32), 'broad', 1.)
        broad.heights[:size//8, :] = np.nan
        assert resolved_contour_interval(local, p) == .25
        assert resolved_contour_interval(broad, p) == 2.
        p.contour_interval = .5
        assert resolved_contour_interval(broad, p) == .5
        p.contour_interval = 'auto'
    saved = tmp_path/'auto.moonlabel'
    p.save(saved)
    assert Project.load(saved).contour_interval == 'auto'


def test_auto_contour_interval_matches_manual_geometry_and_svg_legend(tmp_path):
    p = project(contour_enabled=True, image_path=str(tmp_path/'photo.png'))
    data = dem()
    path = tmp_path/'dem.npz'
    np.savez(path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    p.terrain_path = str(path)
    image = np.full((120, 180, 3), 100, np.uint8)
    p.matrix = np.array([[55., 0, 90.], [0, 55., 60.]])
    layers = build_map_layers(p, image.shape, image=image)
    assert layers.contours and layers.contour_interval in (.25, .5, 1., 2.)
    output = tmp_path/'auto.svg'
    export_svg(output, image, [], p, layers=layers)
    assert f'Δh = {layers.contour_interval:g} km' in output.read_text()
    assert f'Index: {layers.contour_interval*5:g} km' in output.read_text()
    assert p.contour_interval == 'auto'
    p.contour_interval = layers.contour_interval
    manual = build_map_layers(p, image.shape, image=image)
    assert manual.contours == layers.contours


@pytest.mark.parametrize("key,value", [("grid_spacing", True), ("grid_spacing", 20), ("grid_spacing", "15"),
    ("grid_opacity", 1.1), ("elevation_opacity", float("nan")), ("elevation_opacity", True),
    ("elevation_enabled", "false"), ("art_style", []), ("elevation_palette", None),
    ("contour_enabled", 1), ("contour_interval", True), ("contour_interval", .3),
    ("contour_opacity", -.1), ("contour_opacity", float("inf")),
    ("terminator_enabled", 1), ("terminator_opacity", True),
    ("terminator_opacity", -.1), ("terminator_opacity", float("nan")),
    ("terminator_source", "auto"), ("terminator_source", [])])
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
        time.sleep(.005)  # Let background Python work acquire the GIL.
    win.dirty = False
    win.close()


@pytest.mark.parametrize("style", ["manuscript", "topographic"])
def test_original_preset_clears_art_layers_and_keeps_project_edits(window, style, monkeypatch):
    win = window
    item = win.annotation_items[0]
    item.setPos(120, 240)
    win.project.labels[item.feature["id"]]["text"] = "手工地名"
    win.project.color, win.project.font_weight = "#abcded", "normal"
    win.project.art_style = style
    win.project.grid_spacing = 30
    win.project.elevation_enabled = win.project.contour_enabled = True
    win.project.terminator_enabled = win.project.map_light_mask = True
    win.project.map_light_threshold = 47
    win.project.contour_interval = .5
    win.sync_controls()  # Loading a saved art project must keep its custom settings.
    assert win.grid_spacing.currentData() == 30 and win.terminator_toggle.isChecked()
    assert win.map_light_threshold.value() == 47 and win.contour_interval.currentData() == .5
    edits, anchors = deepcopy(win.project.labels), deepcopy(win.project.anchors)
    matrix, photo = win.project.matrix.copy(), win.image.copy()
    with monkeypatch.context() as selecting:
        selecting.setattr(win, "refresh_map_coverage", lambda: pytest.fail("Selecting a preset must not repaint the applied layers"))
        win.art_style.setCurrentIndex(win.art_style.findData("standard"))
    assert win.grid_spacing.currentData() == 0
    assert not any(toggle.isChecked() for toggle in (win.elevation_toggle, win.contour_toggle,
                                                   win.terminator_toggle, win.map_light_toggle))
    assert win.project.art_style == style and win.project.elevation_enabled and win.style_pending
    win.apply_map_styles_button.click()
    assert win.project.art_style == "standard" and not win.style_pending
    assert not any((win.project.grid_spacing, win.project.elevation_enabled, win.project.contour_enabled,
                    win.project.terminator_enabled, win.project.map_light_mask))
    assert not win.map_items
    assert win.project.color == "#abcded" and win.project.font_weight == "normal"
    assert win.font_weight.isEnabled() and win.color_button.isEnabled()
    assert win.project.labels == edits and win.project.anchors == anchors
    assert np.array_equal(win.project.matrix, matrix) and np.array_equal(win.image, photo)
    # Original annotations can still have an independently selected map layer.
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(15))
    win.apply_map_styles_button.click()
    assert win.project.art_style == "standard" and win.project.grid_spacing == 15
    assert win.map_layers.grid


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
    win.elevation_toggle.setChecked(False)
    win.contour_toggle.setChecked(False)
    assert win.project.art_style == "standard" and win.style_pending
    win.apply_label_settings()
    assert win.project.art_style == "manuscript" and not win.font_weight.isEnabled()
    assert win.project.color == "#abcded" and win.project.font_weight == "bold"
    assert all(not item.outline_segments for item in win.annotation_items)
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
        return sample_elevation(p, shape, data, max_edge=128)
    monkeypatch.setattr(app_module, "sample_elevation", sample)
    win.art_style.setCurrentIndex(1)
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(30))
    win.elevation_toggle.setChecked(True)
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)  # Let background Python work acquire the GIL.
    assert not win.busy and win.map_layers.elevation is not None and len(calls) == 1
    assert win.map_layer_status.isHidden() and not win.map_layer_status.text()
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
        time.sleep(.005)  # Let background Python work acquire the GIL.
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
    assert not root.findall('.//s:path[@class="caption-ornament"]', ns)
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
        if value in (0, 85):
            win.grid_opacity_value.selectAll()
            QTest.keyClicks(win.grid_opacity_value, str(value))
            QTest.keyClick(win.grid_opacity_value, Qt.Key.Key_Return)
        else:
            win.grid_opacity.setValue(value)
        assert win.grid_opacity_value.value() == win.grid_opacity.value() == value
        assert win.project.grid_opacity == value/100 and win.map_items == map_items
        assert all(item.opacity() == value/100 for item in map_items if getattr(item, "map_layer", None) == "grid")
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
    assert not win.map_layer_status.isHidden()
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
        time.sleep(.005)  # Let background Python work acquire the GIL.
    assert errors and win._elevation_failed_key is not None and win.map_layers.elevation is None
    assert not win.map_layer_status.isHidden()
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(30))
    win.project.grid_spacing = 30
    win.refresh_annotations()
    assert not win.map_layer_status.isHidden() and 'DEM' in win.map_layer_status.text()
    data = dem()
    np.savez(path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)  # Let background Python work acquire the GIL.
    assert not win.busy and win.map_layers.elevation is not None
    assert len(errors) == 1
    assert win.map_layer_status.isHidden()


@pytest.mark.parametrize("art_style", ["standard", "manuscript", "topographic"])
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
    # Luminance also measures gold faces correctly when their blue is subdued.
    luminance = pixels[45:85, 25:250, :3] @ np.array([.2126, .7152, .0722])
    assert np.count_nonzero(luminance > 150) > 150
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


def test_legend_position_roundtrip_and_legacy_default(tmp_path):
    path = tmp_path/'legend.moonlabel'
    p = Project(image_path=str(tmp_path/'photo.png'), legend_position=[60.5, 80.25])
    p.save(path)
    loaded = Project.load(path)
    assert loaded.legend_position == p.legend_position
    assert legend_rect((600, 800, 3), loaded.legend_position)[:2] == (60.5, 80.25)
    data = json.loads(path.read_text())
    del data['style']['legend_position']
    path.write_text(json.dumps(data))
    legacy = Project.load(path)
    assert legacy.legend_position is None
    assert legend_rect((600, 800, 3), legacy.legend_position) == legend_rect((600, 800, 3))


@pytest.mark.parametrize('elevation', [False, True])
def test_svg_legend_uses_saved_position_for_elevation_and_contours(tmp_path, elevation):
    p = project(elevation_enabled=elevation, contour_enabled=not elevation, legend_position=[60, 80])
    path = tmp_path/'legend.svg'
    export_svg(path, np.zeros((600, 800, 3), np.uint8), [], p,
               layers=MapLayers(elevation=np.zeros((2, 2, 4), np.uint8) if elevation else None,
                                contours=[], contour_interval=.5))
    ns = {'s': 'http://www.w3.org/2000/svg'}
    legend = ET.parse(path).find('.//s:g[@id="elevation-legend"]/s:rect', ns)
    assert (float(legend.get('x')), float(legend.get('y'))) == (60, 80)


def test_dragged_legend_reuses_layers_and_matches_png_svg_and_reopened_project(window, tmp_path, monkeypatch):
    from moonlabeler import app as app_module
    from moonlabeler.ui.map_layers import ElevationLegend
    win = window
    data = dem()
    dem_path = tmp_path/'legend-dem.npz'
    np.savez(dem_path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    win.dem_path = win.project.terrain_path = str(dem_path)
    calls = []
    def sample(p, shape, elevation, *, image=None):
        calls.append(True)
        return sample_elevation(p, shape, elevation, max_edge=128)
    monkeypatch.setattr(app_module, 'sample_elevation', sample)
    win.elevation_toggle.setChecked(True)
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)
    assert not win.busy and len(calls) == 1
    legend = next(item for item in win.map_items if isinstance(item, ElevationLegend))
    assert win.project.legend_position is None
    old_rect = legend.sceneBoundingRect()
    before = tmp_path/'legend-before.png'
    win.render_png(before)
    items, labels = list(win.map_items), list(win.annotation_items)
    positions = [item.pos() for item in labels]
    layers = win.map_layers
    font = win.project.font_percent
    win.font_size.setValue(2.4)  # Moving the legend must not apply pending styles.
    win.dirty = False
    legend.setPos(60, 60)
    assert win.project.legend_position == [60, 60] and win.dirty
    assert win.style_pending and win.project.font_percent == font
    assert win.map_layers is layers and win.map_items == items
    assert win.annotation_items == labels and [item.pos() for item in labels] == positions
    assert len(calls) == 1
    png, svg = tmp_path/'legend-moved.png', tmp_path/'legend-moved.svg'
    win.render_png(png)
    export_svg(svg, win.image, win.annotation_entries(), win.project, win.annotation_leaders(), layers=layers)
    rendered = QImage(win.image.shape[1], win.image.shape[0], QImage.Format.Format_RGB32)
    rendered.fill(0xff000000)
    painter = QPainter(rendered)
    QSvgRenderer(str(svg)).render(painter)
    painter.end()
    native = np.array(Image.open(png).convert('RGB'))
    vector = np.asarray(rendered.constBits()).reshape(rendered.height(), rendered.width(), 4)[:, :, :3][:, :, ::-1]
    unit = legend.boundingRect().height()/6
    x, y = round(60+2*unit), round(60+2.7*unit)
    assert np.max(abs(native[y, x].astype(float)-vector[y, x])) < 6
    old_x, old_y = round(old_rect.x()+2*unit), round(old_rect.y()+2.7*unit)
    previous = np.array(Image.open(before).convert('RGB'))
    assert np.max(abs(native[old_y, old_x].astype(float)-previous[old_y, old_x])) > 10
    saved = tmp_path/'moved.moonlabel'
    win.project.save(saved)
    win.dirty = False
    win.open_project(saved)
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)
    assert not win.busy
    reopened = next(item for item in win.map_items if isinstance(item, ElevationLegend))
    assert reopened.pos().x() == reopened.pos().y() == 60
    assert win.project.legend_position == [60, 60]


def test_contours_interpolate_actual_heights_and_leave_missing_boundaries_open():
    heights = np.tile(np.linspace(-2, 2, 41), (31, 1)).astype(np.float32)
    heights[10:20, 17:24] = np.nan
    raster = ElevationRaster(heights, "test", 1.)
    p = project(contour_enabled=True, contour_interval=.5)
    lines = contour_lines(raster, p, (310, 410, 3))
    assert lines and contour_lines(raster, p, (310, 410, 3)) is lines
    zero = next(line for line in lines if line.height_km == 0)
    assert zero.major and len(zero.segments) == 2
    assert any(not line.major for line in lines)
    for line in lines:
        points = np.concatenate(line.segments)
        expected_x = ((line.height_km+2)/.1+.5)*10
        assert np.allclose(points[:, 0], expected_x, atol=1e-5)
        assert (points[:, 1] >= 5).all() and (points[:, 1] <= 305).all()
    for segment in zero.segments:
        ys = np.array(segment)[:, 1]
        assert ys.max() <= 95 or ys.min() >= 205, "Do not bridge missing heights or trace their boundary"


def test_contours_form_closed_hill_rings_and_resolve_saddles():
    y, x = np.mgrid[-20:21, -20:21]
    heights = (3-(x*x+y*y)/100).astype(np.float32)
    raster = ElevationRaster(heights, "hill", 1.)
    lines = contour_lines(raster, project(contour_interval=1.), (410, 410, 3))
    ring = next(line for line in lines if line.height_km == 1.)
    assert len(ring.segments) == 1
    assert np.allclose(ring.segments[0][0], ring.segments[0][-1])
    radius = np.linalg.norm((np.array(ring.segments[0])-205)/10, axis=1)
    assert np.max(abs(radius-np.sqrt(200))) < .04
    saddle = np.array([[2., -1.], [-1., 2.]], np.float32)
    raster = ElevationRaster(saddle, "saddle", 1.)
    line = next(line for line in contour_lines(raster, project(contour_interval=1.), (20, 20, 3))
                if line.height_km == 0)
    assert len(line.segments) == 2
    assert all(len(segment) == 2 for segment in line.segments)
    assert any(np.allclose(sorted(segment), sorted([[5+20/3, 5], [15, 5+10/3]]))
               for segment in line.segments)


def test_wilderness_preset_and_contour_only_live_export_preserve_originals(window, tmp_path, monkeypatch):
    from moonlabeler import app as app_module
    win = window
    data = dem()
    dem_path = tmp_path/"contour-dem.npz"
    np.savez(dem_path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    win.dem_path = str(dem_path)
    win.annotation_items[0].setPos(130, 220)
    win.refresh_annotations()
    edits, matrix, color = deepcopy(win.project.labels), win.project.matrix.copy(), win.project.color
    original = tmp_path/"original.png"
    win.render_png(original)
    calls = []
    def sample(p, shape, data, *, image=None):
        calls.append(True)
        return sample_elevation(p, shape, data, max_edge=128)
    monkeypatch.setattr(app_module, "sample_elevation", sample)
    win.art_style.setCurrentIndex(win.art_style.findData("topographic"))
    assert not win.project.contour_enabled and win.project.art_style == "standard"
    assert win.contour_toggle.isChecked() and win.elevation_toggle.isChecked()
    assert win.elevation_palette.currentData() == "wilderness"
    win.elevation_toggle.setChecked(False)  # Contours also work over the original photograph.
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)  # Let background Python work acquire the GIL.
    assert not win.busy and win.map_layers.contours and win.map_layers.elevation is None
    assert len(calls) == 1 and win.project.color == color
    assert win.project.labels == edits and np.array_equal(win.project.matrix, matrix)
    items, positions = list(win.annotation_items), [item.pos() for item in win.annotation_items]
    contour_items = [item for item in win.map_items if getattr(item, "map_layer", None) == "contour"]
    win.font_size.setValue(2.4)
    font = win.project.font_percent
    with monkeypatch.context() as fast:
        fast.setattr(app_module, "contour_lines", lambda *a: pytest.fail("Opacity must not rebuild isolines"))
        for opacity in (0, 30, 100):
            win.contour_opacity.setValue(opacity)
            assert all(item.opacity() == opacity/100 for item in contour_items)
    assert win.project.font_percent == font and win.style_pending
    assert win.annotation_items == items and [item.pos() for item in items] == positions
    path = tmp_path/"contours.svg"
    export_svg(path, win.image, win.annotation_entries(), win.project, layers=win.map_layers)
    assert QSvgRenderer(str(path)).isValid()
    ns = {"s": "http://www.w3.org/2000/svg"}
    root = ET.parse(path)
    group = root.find('.//s:g[@id="elevation-contours"]', ns)
    assert group is not None and group.get("opacity") == "1.000"
    assert group.findall('.//s:path', ns)
    assert root.find('.//s:image[@id="elevation-overlay"]', ns) is None
    assert f"Δh = {win.map_layers.contour_interval:g} km" in path.read_text()
    win.render_png(tmp_path/"contours.png")
    saved = tmp_path/"contours.moonlabel"
    win.project.save(saved)
    loaded = Project.load(saved)
    assert loaded.art_style == "topographic" and loaded.contour_opacity == 1.
    win.sync_controls()
    win.art_style.setCurrentIndex(0)
    win.apply_label_settings()
    win.render_png(tmp_path/"restored.png")
    assert np.array_equal(np.array(Image.open(original)), np.array(Image.open(tmp_path/"restored.png")))


def test_missing_contours_prevent_incomplete_export(window, tmp_path):
    window.dem_path = window.project.terrain_path = ""
    window.contour_toggle.setChecked(True)
    window.apply_label_settings()
    with pytest.raises(ValueError, match="等高线尚未生成"):
        window.render_png(tmp_path/"missing-contours.png")
    with pytest.raises(ValueError, match="DEM"):
        build_map_layers(window.project, window.image.shape)


def test_wilderness_basemap_flattens_photo_contrast_without_changing_data():
    heights = np.tile(np.linspace(-4, 4, 80), (60, 1)).astype(np.float32)
    heights[0, 0] = np.nan
    before = heights.copy()
    raster = ElevationRaster(heights, "map", 1.)
    p = project(art_style="topographic", elevation_palette="wilderness", elevation_opacity=1.)
    dark, bright = np.zeros((120, 160, 3), np.uint8), np.full((120, 160, 3), 255, np.uint8)
    first = colorize_elevation(raster, p, image=dark)
    second = colorize_elevation(raster, p, image=bright)
    assert np.array_equal(first, second), "A flat map must not inherit photographic noise or cast shadows"
    assert first[20, 20, :3].min() > 20 and first[20, 20, 3] == 255
    assert first[0, 0, 3] == 0
    assert np.array_equal(heights, before, equal_nan=True)
    assert not dark.any() and (bright == 255).all()


def test_wilderness_names_have_hierarchy_and_preserve_explicit_pins(window):
    win = window
    original_font, original_step = win.project.font_size, win.project.font_step_percent
    win.project.art_style = "topographic"
    win.sync_controls()
    win.refresh_annotations()
    automatic = [item for item in win.annotation_items if "position" not in win.project.labels.get(item.feature['id'], {})]
    assert automatic and all(not item.line.isVisible() and not item.outline_segments for item in automatic)
    item = automatic[0]
    item.setPos(item.pos().x()+150, item.pos().y()+120)
    assert not item.line.isVisible() and "position" in win.project.labels[item.feature['id']]
    sizes = win.project.label_font_sizes([
        {"id": "main", "name": "Clavius", "kind": "Crater, craters", "diameter": 200},
        {"id": "minor", "name": "Clavius A", "kind": "Satellite Feature", "diameter": 10}], win.image.shape)
    assert sizes['main'] > sizes['minor']*1.5
    assert (win.project.font_size, win.project.font_step_percent) == (original_font, original_step)


@pytest.mark.parametrize("legacy_value", [True, False])
def test_legacy_lighting_flag_is_ignored_and_not_saved(window, tmp_path, legacy_value):
    path = tmp_path/"legacy-lighting.moonlabel"
    window.project.save(path)
    data = json.loads(path.read_text())
    data['style']['map_lit_only'] = legacy_value
    path.write_text(json.dumps(data))
    p = Project.load(path)
    assert not hasattr(p, 'map_lit_only') and not hasattr(window, 'map_lit_only')
    assert p.illuminated_only == window.project.illuminated_only
    p.save(path)
    assert 'map_lit_only' not in json.loads(path.read_text())['style']


def test_classical_caption_hierarchy_and_curved_svg_remain_editable(tmp_path):
    from moonlabeler.annotation_style import caption_text, caption_typography
    p = Project(art_style="manuscript", language="英文", font_size=25)
    features = [
        {"id": "sea", "name": "Mare Imbrium", "kind": "Mare, maria", "diameter": 1145},
        {"id": "crater", "name": "Archimedes", "kind": "Crater, craters", "diameter": 80},
        {"id": "rille", "name": "Rima Hadley", "kind": "Rima, rimae", "diameter": 100}]
    sizes = p.label_font_sizes(features, (600, 1000, 3))
    assert sizes['sea'] > sizes['crater'] > sizes['rille']
    assert caption_text(p, features[0]) == 'MARE IMBRIUM'
    assert caption_typography(p, features[2]).italic
    path = tmp_path/'classical.svg'
    export_svg(path, np.zeros((600, 1000, 3), np.uint8),
               [(f, [100, 100], [80, 100+i*100]) for i, f in enumerate(features)], p)
    root = ET.parse(path)
    ns = {'s': 'http://www.w3.org/2000/svg'}
    text = root.find('.//s:g[@id="label-text-0"]', ns)
    assert ''.join(text.itertext()) == 'MARE IMBRIUM'
    glyphs = text.findall('s:g', ns)
    assert len(glyphs) == len('MARE IMBRIUM')
    assert 'rotate(-' in glyphs[0].get('transform') and 'rotate(-' not in glyphs[-1].get('transform')
    assert root.find('.//s:text[@id="label-text-2"]', ns).get('font-style') == 'italic'
    p.labels['sea'] = {'text': 'My own Moon label'}
    assert caption_text(p, features[0]) == 'My own Moon label'


def test_classical_curved_svg_renders_like_native_text(tmp_path):
    from moonlabeler.app import Annotation
    from moonlabeler.annotation_style import caption_text
    application = QApplication.instance() or QApplication([])
    p = Project(art_style='manuscript', language='英文', font_size=25)
    feature = {'id': 'sea', 'name': 'Mare Imbrium', 'kind': 'Mare, maria', 'diameter': 1145}
    photograph = np.zeros((400, 800, 3), np.uint8)
    size = p.label_font_sizes([feature], photograph.shape)['sea']
    item = Annotation(feature, [0, 0], caption_text(p, feature), p, lambda *a: None, lambda *a: None, font_size=size)
    # Compare glyph geometry at higher sampling density. Windows text hinting
    # and path antialiasing can put the same small edge on adjacent pixels at
    # 1x. Keep both world coordinates and the overlap requirement unchanged.
    render_scale = 4
    native = QImage(800*render_scale, 400*render_scale, QImage.Format.Format_RGB32)
    native.fill(0xff000000)
    painter = QPainter(native)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    painter.scale(render_scale, render_scale)
    painter.translate(80, 150)
    item.paint(painter, None)
    painter.end()
    path = tmp_path/'arc.svg'
    export_svg(path, photograph, [(feature, [0, 0], [80, 150])], p)
    svg = QImage(800*render_scale, 400*render_scale, QImage.Format.Format_RGB32)
    svg.fill(0xff000000)
    painter = QPainter(svg)
    QSvgRenderer(str(path)).render(painter)
    painter.end()
    def face(image):
        pixels = np.asarray(image.constBits()).reshape(image.height(), image.width(), 4)[:, :, :3]
        return (pixels > 150).all(axis=2)
    first, second = face(native), face(svg)
    assert (first & second).sum()/(first | second).sum() > .75


def test_art_styles_desaturate_display_png_svg_and_restore_colour_source(window, tmp_path, monkeypatch):
    from moonlabeler import app as app_module
    win = window
    source = np.zeros((200, 320, 3), np.uint8)
    source[:, :100] = (220, 45, 20)
    source[:, 100:220] = (30, 190, 65)
    source[:, 220:] = (45, 60, 235)
    original = source.copy()
    path = tmp_path/'colour-moon.png'
    Image.fromarray(source).save(path)
    gray = np.asarray(Image.fromarray(source).convert('L').convert('RGB'))
    win.catalog = []
    win.project.image_path = str(path)
    win.set_image(source)
    matrix = win.project.matrix.copy()
    anchors = deepcopy(win.project.anchors)
    changes = []
    convert = app_module.photo_for_style
    def tracked(image, style):
        changes.append(style)
        return convert(image, style)
    monkeypatch.setattr(app_module, 'photo_for_style', tracked)
    def scene_photo():
        image = win.photo_item.pixmap().toImage().convertToFormat(QImage.Format.Format_RGB888)
        return np.asarray(image.constBits()).reshape(image.height(), image.bytesPerLine())[:, :image.width()*3].reshape(image.height(), image.width(), 3).copy()
    assert np.array_equal(scene_photo(), original)
    art_path = tmp_path/'art.moonlabel'
    for style in ('manuscript', 'topographic'):
        win.art_style.setCurrentIndex(win.art_style.findData(style))
        win.elevation_toggle.setChecked(False)
        win.contour_toggle.setChecked(False)
        win.apply_label_settings()
        assert np.array_equal(scene_photo(), gray)
        win.render_png(tmp_path/f'{style}.png')
        assert np.array_equal(np.asarray(Image.open(tmp_path/f'{style}.png')), gray)
        svg = tmp_path/f'{style}.svg'
        export_svg(svg, win.image, [], win.project)
        node = ET.parse(svg).find('.//{http://www.w3.org/2000/svg}image[@id="photograph"]')
        data = node.get('{http://www.w3.org/1999/xlink}href').split(',', 1)[1]
        assert np.array_equal(np.asarray(Image.open(io.BytesIO(base64.b64decode(data)))), gray)
        if style == 'manuscript':
            win.project.save(art_path)
    assert changes == ['manuscript'], "Both art styles and repeated redraws reuse the grayscale base"
    win.art_style.setCurrentIndex(win.art_style.findData('standard'))
    win.apply_label_settings()
    assert np.array_equal(scene_photo(), original)
    win.render_png(tmp_path/'restored.png')
    assert np.array_equal(np.asarray(Image.open(tmp_path/'restored.png')), original)
    assert win.image is source and np.array_equal(source, original)
    assert np.array_equal(win.project.matrix, matrix) and win.project.anchors == anchors
    win.confirm_discard = lambda: True
    win.open_project(str(art_path))
    assert win.project.art_style == 'manuscript' and np.array_equal(scene_photo(), gray)
    assert np.array_equal(win.image, original) and np.array_equal(np.asarray(Image.open(path)), original)


@pytest.mark.parametrize("sun", [(-.65, .7, .25), (0., 1., 0.), (.7, -.65, -.2)])
@pytest.mark.parametrize("mirrored", [False, True])
def test_terminator_follows_solar_horizon_with_rotation_lens_and_photo_clipping(sun, mirrored):
    p = project(terminator_enabled=True)
    p.geometry.sun = unit(sun)
    angle = .43
    p.matrix[:, :2] = 240*np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    p.matrix[:, 2] = [250, 210]
    if mirrored:
        p.matrix[:, 0] *= -1
    p.identification = {"lens_distortion": {"center": [250., 210.], "scale": 250., "k": .07}}
    geometry, matrix = p.geometry.to_dict(), p.matrix.copy()
    segments = terminator_segments(p, (420, 500, 3))
    assert segments
    points = np.concatenate(segments)
    assert np.isfinite(points).all()
    assert (points >= -1e-8).all() and (points <= [500+1e-8, 420+1e-8]).all()
    lat, lon, visible = p.geometry.unproject(photo_coordinates(p, points))
    assert visible.all()
    vectors = surface_vectors(lat, lon)
    assert np.max(abs(vectors @ p.geometry.sun)) < 5e-5
    assert np.all(vectors @ p.geometry.observer > 1737.4/p.geometry.distance_km-1e-6)
    assert p.geometry.to_dict() == geometry and np.array_equal(p.matrix, matrix)
    p.terminator_enabled = False
    assert not terminator_segments(p, (420, 500, 3))


@pytest.mark.parametrize("phase", [-1, 1])
def test_exact_new_and_full_moon_have_no_visible_reference_sphere_terminator(phase):
    p = project(terminator_enabled=True, terminator_source='ephemeris')
    p.geometry.sun = phase*p.geometry.observer
    assert not build_map_layers(p, (600, 600, 3)).terminator


def test_terminator_without_dem_live_opacity_save_reopen_and_exports(window, tmp_path, monkeypatch):
    from moonlabeler import app as app_module
    win = window
    win.project.geometry.sun = unit(win.project.geometry.right)
    win.terminator_source.setCurrentIndex(win.terminator_source.findData('ephemeris'))
    before, matrix = win.image.copy(), win.project.matrix.copy()
    labels, geometry = deepcopy(win.project.labels), win.project.geometry.to_dict()
    monkeypatch.setattr(app_module, "sample_elevation", lambda *a, **k: pytest.fail("Terminator needs no DEM"))
    assert not win.project.terminator_enabled
    win.terminator_toggle.setChecked(True)
    win.terminator_opacity.setValue(82)
    assert not win.project.terminator_enabled
    win.apply_label_settings()
    assert win.project.terminator_enabled and win.project.terminator_opacity == .82
    assert not win.busy and win.map_layers.terminator and win.map_layers.elevation is None
    assert not win.project.terrain_path
    items, positions = list(win.annotation_items), [item.pos() for item in win.annotation_items]
    map_items, segments = list(win.map_items), deepcopy(win.map_layers.terminator)
    old_font = win.project.font_percent
    win.font_size.setValue(2.4)
    with monkeypatch.context() as fast:
        fast.setattr(app_module, "build_terminator", lambda *a, **k: pytest.fail("Opacity must reuse the curve"))
        fast.setattr(win, "refresh_annotations", lambda: pytest.fail("Opacity must not regenerate labels"))
        for value in (0, 40, 100):
            win.terminator_opacity.setValue(value)
            assert win.project.terminator_opacity == value/100 and win.map_items == map_items
            assert all(item.opacity() == value/100 for item in map_items)
            assert win.annotation_items == items and [item.pos() for item in items] == positions
            assert win.map_layers.terminator == segments and win.project.font_percent == old_font
    assert win.style_pending and win.project.labels == labels
    svg = tmp_path/"terminator.svg"
    export_svg(svg, win.image, win.annotation_entries(), win.project)
    group = ET.parse(svg).find('.//{http://www.w3.org/2000/svg}g[@id="lunar-terminator"]')
    assert group is not None and len(group.findall('{http://www.w3.org/2000/svg}path')) == 2
    assert group.attrib['data-utc'] == win.project.geometry.utc
    assert group.attrib['data-model'] == 'reference-sphere' and group.attrib['opacity'] == '1.000'
    assert group.attrib['data-source'] == 'ephemeris'
    win.render_png(tmp_path/"terminator.png")
    assert Image.open(tmp_path/"terminator.png").size == (before.shape[1], before.shape[0])
    assert np.array_equal(win.image, before) and np.array_equal(win.project.matrix, matrix)
    assert win.project.geometry.to_dict() == geometry
    saved = tmp_path/"terminator.moonlabel"
    win.project.save(saved)
    win.confirm_discard = lambda: True
    win.open_project(str(saved))
    assert win.terminator_toggle.isChecked() and win.terminator_opacity.value() == 100
    assert win.map_styles_toggle.isChecked() and win.map_layers.terminator
    assert win.project.labels == labels and win.project.geometry.to_dict() == geometry
    assert np.array_equal(win.image, before) and np.array_equal(win.project.matrix, matrix)
    win.terminator_toggle.setChecked(False)
    win.apply_label_settings()
    assert not win.map_layers.terminator and not win.map_items


@pytest.mark.parametrize("art_style", ["standard", "manuscript", "topographic"])
def test_full_opacity_vectors_remain_visible_when_fitted_on_light_and_dark_ground(tmp_path, art_style):
    from moonlabeler.ui.map_layers import add_map_layers, array_image
    application = QApplication.instance() or QApplication([])
    p = project(art_style=art_style, grid_spacing=15, grid_opacity=1., contour_enabled=True,
                contour_opacity=1., terminator_enabled=True, terminator_source='ephemeris')
    image = np.full((2400, 3200, 3), 38, np.uint8)
    image[:1200] = 216
    segment = lambda x: [[[x, 100], [x, 2100]]]
    layers = MapLayers(grid=[GridLine(segment(400), '', (0, 0), True),
                             GridLine(segment(1000), '', (0, 0), False)],
                       contours=[ContourLine(0., segment(1800), True),
                                 ContourLine(.5, segment(2400), False)],
                       terminator=segment(2800))
    scene = QGraphicsScene()
    scene.addPixmap(QPixmap.fromImage(array_image(image)))
    add_map_layers(scene, p, image.shape, layers)
    native = QImage(800, 600, QImage.Format.Format_RGBA8888)
    painter = QPainter(native)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter, QRectF(0, 0, 800, 600), QRectF(0, 0, 3200, 2400))
    painter.end()
    path = tmp_path/f'{art_style}.svg'
    export_svg(path, image, [], p, layers=layers)
    svg = QImage(800, 600, QImage.Format.Format_RGBA8888)
    painter = QPainter(svg)
    QSvgRenderer(str(path)).render(painter)
    painter.end()
    for rendered in (native, svg):
        pixels = np.asarray(rendered.constBits()).reshape(600, 800, 4)[:, :, :3].astype(float)
        for x in (100, 250, 450, 600, 700):
            for y, background in ((180, 216), (420, 38)):
                difference = np.max(abs(pixels[y-8:y+8, x-4:x+5]-background), axis=2)
                # Filtering may spread the same subpixel stroke across two
                # columns. Measure its total contrast, not one sample's peak.
                assert np.count_nonzero(difference.sum(axis=1) > 65) >= 8, (art_style, x, y)


def test_real_photo_estimated_terminator_does_not_bisect_bright_copernicus_ground():
    from PIL import ImageFilter
    root = Path(__file__).parents[1]
    project_path = root/'examples/auto-copernicus.moonlabel'
    if not project_path.exists():
        pytest.skip('Local Copernicus project is unavailable')
    p = Project.load(project_path)
    if not Path(p.image_path).exists():
        pytest.skip('Local Copernicus photo is unavailable')
    p.terminator_enabled = True
    p.terminator_source = 'photo'
    p.elevation_enabled = p.contour_enabled = False
    p.grid_spacing = 0
    with Image.open(p.image_path) as source:
        image = np.asarray(source.convert('RGB'))
        small = source.convert('L')
        small.thumbnail((800, 800))
        gray = np.asarray(small.filter(ImageFilter.GaussianBlur(3)))
    geometry, matrix = p.geometry.to_dict(), p.matrix.copy()
    layers = build_map_layers(p, image.shape, image=image)
    assert layers.terminator
    samples = []
    for segment in layers.terminator:
        points = np.array(segment)*[gray.shape[1]/image.shape[1], gray.shape[0]/image.shape[0]]
        distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        along = np.linspace(0, distance[-1], max(2, int(distance[-1])))
        xy = np.column_stack([np.interp(along, distance, points[:, c]) for c in range(2)]).round().astype(int)
        samples.extend(gray[xy[:, 1].clip(0, gray.shape[0]-1), xy[:, 0].clip(0, gray.shape[1]-1)])
    floor, bright = np.percentile(gray, [2, 90])
    assert (np.median(samples)-floor)/(bright-floor) < .25
    assert p.geometry.to_dict() == geometry and np.array_equal(p.matrix, matrix)


def photo_terminator_example():
    p = project(terminator_enabled=True)
    p.geometry.sun = unit([-.55, -.83, .05])  # Deliberately wrong project illumination.
    y, x = np.mgrid[:600, :600]
    lat, lon, valid = p.geometry.unproject(photo_coordinates(p, np.column_stack((x.ravel()+.5, y.ravel()+.5))))
    vectors = surface_vectors(lat, lon)
    actual_sun = unit([.25, -.95, .17])
    incidence = (vectors @ actual_sun).reshape(600, 600)
    gray = np.where(valid.reshape(600, 600), 12+190*np.clip(incidence*4, 0, 1), 0).astype(np.uint8)
    for cx, cy in ((180, 230), (220, 300), (170, 370)):
        gray[(x-cx)**2+(y-cy)**2 < 12**2] = 0
    return p, np.repeat(gray[:, :, None], 3, axis=2), actual_sun


def test_photo_fit_uses_broad_boundary_and_preserves_original_solar_geometry(tmp_path):
    p, image, actual_sun = photo_terminator_example()
    before, geometry = image.copy(), p.geometry.to_dict()
    layers = build_map_layers(p, image.shape, image=image)
    assert layers.terminator and not layers.terminator_unreliable
    points = np.vstack(layers.terminator)
    lat, lon, valid = p.geometry.unproject(photo_coordinates(p, points))
    assert valid.all() and np.median(abs(surface_vectors(lat, lon) @ actual_sun)) < .06
    assert p.geometry.to_dict() == geometry and np.array_equal(image, before)
    p.geometry.sun = unit([.8, .1, .59])
    same = build_map_layers(p, image.shape, image=image)
    assert same.terminator == layers.terminator, 'Photo estimates must not follow an unverified project Sun'
    path = tmp_path/'photo-terminator.svg'
    export_svg(path, image, [], p, layers=layers)
    group = ET.parse(path).find('.//{http://www.w3.org/2000/svg}g[@id="lunar-terminator"]')
    assert group.attrib['data-source'] == 'photo' and 'data-utc' not in group.attrib
    assert 'Photo-estimated' in group.find('{http://www.w3.org/2000/svg}title').text
    assert all('stroke-dasharray' in item.attrib for item in group.findall('{http://www.w3.org/2000/svg}path'))


def test_photo_mode_rejects_isolated_crater_shadows_and_prevents_incomplete_export(window, tmp_path):
    win = window
    p = project(terminator_enabled=True)
    image = np.full((600, 600, 3), 170, np.uint8)
    image[180:210, 180:210] = image[320:360, 320:360] = 0
    p.image_path = str(tmp_path/'daylit.png')
    Image.fromarray(image).save(p.image_path)
    geometry, matrix = p.geometry.to_dict(), p.matrix.copy()
    win.project = p
    win.catalog = []
    win.sync_controls()
    win.set_image(image)
    assert not win.map_layers.terminator and win.map_layers.terminator_unreliable
    assert win.terminator_status.text() and not win.map_items
    assert not win.terminator_status.isHidden()
    with pytest.raises(ValueError, match='可靠的晨昏'):
        win.render_png(tmp_path/'incomplete.png')
    with pytest.raises(ValueError, match='可靠的晨昏'):
        export_svg(tmp_path/'incomplete.svg', image, [], p)
    assert not (tmp_path/'incomplete.png').exists() and not (tmp_path/'incomplete.svg').exists()
    assert win.project.geometry.to_dict() == geometry and np.array_equal(win.project.matrix, matrix)
    win.terminator_toggle.setChecked(False)
    win.apply_label_settings()
    assert win.terminator_status.isHidden()
    win.render_png(tmp_path/'original.png')
    assert np.array_equal(np.asarray(Image.open(tmp_path/'original.png')), image)


def test_photo_estimate_is_cached_through_cosmetic_changes_and_survives_project_reopen(window, tmp_path, monkeypatch):
    from moonlabeler import app as app_module
    win = window
    p, image, _ = photo_terminator_example()
    p.image_path = str(tmp_path/'photo.png')
    Image.fromarray(image).save(p.image_path)
    geometry, matrix = p.geometry.to_dict(), p.matrix.copy()
    calls, original = [], app_module.build_terminator
    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(app_module, 'build_terminator', counted)
    win.project, win.catalog = p, []
    win.sync_controls()
    win.set_image(image)
    segments = deepcopy(win.map_layers.terminator)
    assert segments and len(calls) == 1
    assert win.terminator_status.isHidden() and not win.terminator_status.text()
    win.art_style.setCurrentIndex(win.art_style.findData('manuscript'))
    win.elevation_toggle.setChecked(False)
    win.contour_toggle.setChecked(False)
    win.apply_label_settings()
    win.terminator_opacity.setValue(35)
    assert len(calls) == 1 and win.map_layers.terminator == segments
    assert win.project.geometry.to_dict() == geometry and np.array_equal(win.project.matrix, matrix)
    saved = tmp_path/'photo.moonlabel'
    win.project.save(saved)
    win.confirm_discard = lambda: True
    win.open_project(str(saved))
    assert win.project.terminator_source == 'photo' and win.terminator_opacity.value() == 35
    assert win.map_layers.terminator == segments and not win.map_layers.terminator_unreliable
    win.render_png(tmp_path/'photo-lines.png')
    assert np.array_equal(win.image, image) and win.project.geometry.to_dict() == geometry


@pytest.mark.parametrize('layer', ['contour', 'grid'])
def test_map_preview_reuses_pixels_and_png_renders_original_resolution(window, tmp_path, monkeypatch, layer):
    from moonlabeler.ui.map_layers import ContourLayer
    win = window
    monkeypatch.setattr(ContourLayer, 'MAX_PREVIEW_PIXELS', 2048)
    data = dem()
    path = tmp_path/'dem.npz'
    np.savez(path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    win.dem_path = str(path)
    win.art_style.setCurrentIndex(win.art_style.findData('manuscript'))
    win.elevation_toggle.setChecked(False)
    win.contour_toggle.setChecked(layer == 'contour')
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(15 if layer == 'grid' else 0))
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)  # Let background Python work acquire the GIL.
    assert not win.busy
    item = next(item for item in win.map_items if getattr(item, 'map_layer', None) == layer)
    preview, calls = item.preview, []
    original = item.rasterize
    def render(size):
        calls.append(size)
        return original(size)
    monkeypatch.setattr(item, 'rasterize', render)
    getattr(win, f'{layer}_opacity').setValue(83)
    win.canvas.scale(1.2, 1.2)
    win.canvas.viewport().repaint()
    QApplication.processEvents()
    assert not calls and item.preview is preview
    assert item.preview_size != item.source_size
    win.render_png(tmp_path/'full-resolution.png')
    assert calls == [item.source_size]
    assert item.export_image is None and item.preview is preview
    assert Image.open(tmp_path/'full-resolution.png').size == item.source_size


def test_contour_preparation_runs_off_ui_thread_and_keeps_canvas_interactive(window, tmp_path, monkeypatch):
    import threading
    from moonlabeler import app as app_module
    from moonlabeler.ui import map_layers as ui_module
    win = window
    data = dem()
    path = tmp_path/'dem.npz'
    np.savez(path, height_km=data.data, north=data.north, west=data.west, pixels_per_degree=data.ppd)
    win.dem_path = str(path)
    threads = []
    for module, name in ((app_module, 'contour_lines'), (ui_module, 'path_from_segments')):
        original = getattr(module, name)
        def record(*args, _call=original, **kwargs):
            threads.append(threading.get_ident())
            return _call(*args, **kwargs)
        monkeypatch.setattr(module, name, record)
    win.contour_toggle.setChecked(True)
    win.apply_label_settings()
    assert win.busy and win.canvas.isEnabled()
    items = list(win.annotation_items)
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)  # Release the GIL for Python contour work, like QApplication.exec().
    assert not win.busy and win.map_layers.contours
    assert threads and all(thread != threading.get_ident() for thread in threads)
    assert win.annotation_items == items, 'Finishing map work must not rebuild or move labels'
    assert win.contour_interval.currentData() == 'auto'
    assert f'{win.map_layers.contour_interval:g} km' in win.contour_interval.currentText()
    raster = win._elevation_raster
    threads.clear()
    win.contour_interval.setCurrentIndex(win.contour_interval.findData(2.))
    win.apply_label_settings()
    assert win.busy and win.canvas.isEnabled()
    with pytest.raises(ValueError, match='尚未生成'):
        win.check_map_export()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)
    assert not win.busy and win.map_layers.contour_interval == 2.
    assert win._elevation_raster is raster
    assert threads and all(thread != threading.get_ident() for thread in threads)


@pytest.mark.parametrize('style', ['standard', 'manuscript', 'topographic'])
def test_exported_text_is_independent_of_preview_zoom_and_selection(window, tmp_path, style):
    win = window
    win.art_style.setCurrentIndex(win.art_style.findData(style))
    win.elevation_toggle.setChecked(False)
    win.contour_toggle.setChecked(False)
    win.apply_label_settings()
    assert win.annotation_items
    win.canvas.scale(.08, .08)
    win.canvas.viewport().grab()
    before = tmp_path/'fitted.png'
    win.render_png(before)
    win.canvas.scale(40, 40)
    selected = win.annotation_items[0]
    selected.setSelected(True)
    win.canvas.viewport().grab()
    after = tmp_path/'zoomed.png'
    win.render_png(after)
    assert np.array_equal(np.array(Image.open(before)), np.array(Image.open(after)))
    assert selected.isSelected(), 'Export must restore the editor selection'
