# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Photo-based map coverage, independent of ephemeris and expensive map preparation."""
import json
import base64
import io
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry
from moonlabeler.map_layers import photo_lightness
from moonlabeler.project import Project, export_svg
from moonlabeler.ui.map_layers import MapCoverage


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def half_moon():
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([-1., 0, 0]), 384400., "2026-01-01T00:00:00+00:00")
    p = Project(geometry=geometry, matrix=np.array([[110., 0, 128.], [0, 110., 128.]]),
                map_light_mask=True)
    y, x = np.mgrid[:256, :256]
    disk = (x-128)**2+(y-128)**2 < 110**2
    image = np.zeros((256, 256, 3), np.uint8)
    image[disk & (x >= 128)] = 170
    image[disk & (x < 128)] = 4
    image[(x-185)**2+(y-128)**2 < 19**2] = 0  # Enclosed crater floor.
    return p, image


def inside(polygons, *points):
    clip = MapCoverage((256, 256), polygons)
    return [clip.coverage_path.contains(QPointF(*point)) for point in points]


def test_auto_keeps_bright_ground_and_enclosed_craters_without_using_sun(application):
    p, image = half_moon()
    original, matrix, geometry = image.copy(), p.matrix.copy(), p.geometry.to_dict()
    field = photo_lightness(p, image)
    polygons, level = field.coverage()
    assert 4 < level < 50
    assert inside(polygons, (220, 128), (185, 128), (80, 128), (5, 5)) == [True, True, False, False]
    assert p.geometry.to_dict() == geometry and np.array_equal(p.matrix, matrix)
    assert np.array_equal(image, original)
    p.geometry.sun *= -1
    p.geometry.utc = "2023-06-03T16:26:00+00:00"
    assert photo_lightness(p, image).coverage() == (polygons, level)
    p.matrix[:, :2] *= .8  # An imperfect fitted limb must not erase bright ground.
    assert inside(photo_lightness(p, image).coverage()[0], (230, 128)) == [True]


def test_manual_threshold_expands_and_reduces_coverage(application):
    p, image = half_moon()
    field = photo_lightness(p, image)
    low, _ = field.coverage(2)
    high, _ = field.coverage(200)
    assert inside(low, (80, 128), (220, 128)) == [True, True]
    assert not high
    zero, level = field.coverage(0)
    assert level == 0 and inside(zero, (.1, .1), (255.9, 255.9)) == [True, True]
    assert field.coverage(255)[0] == []


@pytest.mark.parametrize("brightness,covered", [(0, False), (180, True), (255, True)])
def test_uniform_crops_do_not_invent_a_terminator(application, brightness, covered):
    p, image = half_moon()
    image[:] = brightness
    polygons, _ = photo_lightness(p, image).coverage()
    assert inside(polygons, (100, 100), (2, 2), (254, 254)) == [covered]*3


@pytest.mark.parametrize("threshold", ["auto", 0, 31, 255])
def test_mask_settings_roundtrip_and_old_projects_keep_full_coverage(tmp_path, threshold):
    p, _ = half_moon()
    p.image_path = str(tmp_path/"moon.png")
    p.map_light_threshold = threshold
    path = tmp_path/"moon.moonlabel"
    p.save(path)
    loaded = Project.load(path)
    assert loaded.map_light_mask and loaded.map_light_threshold == threshold
    data = json.loads(path.read_text())
    del data["style"]["map_light_mask"]
    del data["style"]["map_light_threshold"]
    data["style"]["map_lit_only"] = True
    path.write_text(json.dumps(data))
    loaded = Project.load(path)
    assert not loaded.map_light_mask and loaded.map_light_threshold == "auto"


@pytest.mark.parametrize("key,value", [("map_light_mask", 1), ("map_light_threshold", True),
                                      ("map_light_threshold", -1), ("map_light_threshold", 256),
                                      ("map_light_threshold", .5), ("map_light_threshold", "31"),
                                      ("map_light_threshold", None)])
def test_invalid_mask_settings_rejected(tmp_path, key, value):
    path = tmp_path/"invalid.moonlabel"
    Project(image_path=str(tmp_path/"moon.png")).save(path)
    data = json.loads(path.read_text())
    data["style"][key] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=key):
        Project.load(path)


@pytest.fixture
def window(application, tmp_path):
    win = MainWindow()
    win.error = lambda error: (_ for _ in ()).throw(AssertionError(str(error)))
    win.open_project(str(Path(__file__).parents[1]/"examples/demo.moonlabel"))
    data = np.full((180, 360), 1., np.float32)
    path = tmp_path/"dem.npz"
    np.savez(path, height_km=data, north=90, west=-180, pixels_per_degree=1)
    win.dem_path = str(path)
    win.art_style.setCurrentIndex(win.art_style.findData("manuscript"))
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(30))
    win.apply_label_settings()
    deadline = time.monotonic()+10
    while win.busy and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(.005)
    assert not win.busy and win.map_layers.elevation is not None
    yield win
    win.dirty = False
    win.close()


def test_slider_and_auto_are_live_without_rebuilding_layers_or_labels(window, monkeypatch, tmp_path):
    from moonlabeler import app as app_module
    win = window
    assert win.project.map_light_mask and win.map_light_auto.isChecked()
    automatic, original = win.map_light_threshold.value(), win.map_layers.coverage
    annotations, maps = list(win.annotation_items), list(win.map_items)
    positions = [item.pos() for item in annotations]
    raster, rgba = win._elevation_raster, win.map_layers.elevation
    original_font = win.project.font_percent
    win.font_size.setValue(2.4)  # Unapplied unrelated setting stays pending.
    def reject(*args, **kwargs):
        pytest.fail("Changing coverage must reuse the photo, DEM and existing labels")
    monkeypatch.setattr(win, "refresh_annotations", reject)
    monkeypatch.setattr(win, "refresh_map_layers", reject)
    for name in ("photo_lightness", "sample_elevation", "colorize_elevation", "contour_lines"):
        monkeypatch.setattr(app_module, name, reject)
    win.map_light_threshold.setValue(255)
    assert win.project.map_light_threshold == 255 and not win.map_light_auto.isChecked()
    assert win.map_layers.coverage != original
    QTest.mouseClick(win.map_light_auto, Qt.MouseButton.LeftButton)
    assert win.project.map_light_threshold == "auto" and win.map_light_threshold.value() == automatic
    assert win.map_layers.coverage == original
    win.map_light_toggle.setChecked(False)
    assert win.map_layers.coverage is None and not win.project.map_light_mask
    win.map_light_toggle.setChecked(True)
    assert win.map_layers.coverage == original
    assert win.map_items == maps and win.annotation_items == annotations
    assert [item.pos() for item in annotations] == positions
    assert win._elevation_raster is raster and win.map_layers.elevation is rgba
    assert win.project.font_percent == original_font and win.style_pending
    win.project.save(tmp_path/"live.moonlabel")
    assert Project.load(tmp_path/"live.moonlabel").map_light_mask


def test_png_and_svg_share_coverage_and_leave_legend_and_names_independent(window, tmp_path):
    win = window
    win.map_light_threshold.setValue(255)
    assert win.map_layers.coverage == []
    empty = tmp_path/"masked.png"
    win.render_png(empty)
    win.map_light_toggle.setChecked(False)
    full = tmp_path/"full.png"
    win.render_png(full)
    a, b = np.array(Image.open(empty)), np.array(Image.open(full))
    assert np.count_nonzero(np.any(a != b, axis=2)) > 100
    assert all(item.isVisible() for item in win.annotation_items)
    win.map_light_toggle.setChecked(True)
    win.reset_map_light_threshold()
    output = tmp_path/"masked.svg"
    export_svg(output, win.image, win.annotation_entries(), win.project, win.annotation_leaders(), layers=win.map_layers)
    root = ET.parse(output)
    ns = {"s": "http://www.w3.org/2000/svg"}
    group = root.find('.//s:g[@id="photo-lit-map-layers"]', ns)
    assert group is not None and group.get("data-threshold") == str(win.map_layers.light_threshold)
    assert group.find('.//s:image[@id="elevation-overlay"]', ns) is not None
    assert group.find('.//s:g[@id="selenographic-grid"]', ns) is not None
    assert group.find('.//s:g[@id="elevation-contours"]', ns) is not None
    assert group.find('.//s:g[@id="elevation-legend"]', ns) is None
    assert root.find('.//s:g[@id="elevation-legend"]', ns) is not None
    mask = root.find('.//s:mask/s:image', ns)
    encoded = mask.get("{http://www.w3.org/1999/xlink}href").split(',', 1)[1]
    alpha = np.asarray(Image.open(io.BytesIO(base64.b64decode(encoded))))[:, :, 3]
    assert np.any((alpha > 0) & (alpha < 255)), "The transition must fade rather than cut abruptly"
    before, after = tmp_path/"before-zoom.png", tmp_path/"after-zoom.png"
    win.render_png(before)
    win.canvas.scale(8, 8)
    win.render_png(after)
    assert np.array_equal(np.asarray(Image.open(before)), np.asarray(Image.open(after)))


@pytest.mark.parametrize("size,dpr", [(256, 1), (1024, 1), (256, 2)])
def test_feathered_boundary_renders_with_partial_alpha_in_native_and_svg(application, tmp_path, size, dpr):
    import shutil
    import subprocess
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem
    from moonlabeler.map_layers import MapLayers, layers_svg
    from moonlabeler.ui.map_layers import array_image

    p = Project(elevation_enabled=True)
    layers = MapLayers(elevation=np.full((size, size, 4), 255, np.uint8),
                       coverage=[[[size/2, 0], [size, 0], [size, size], [size/2, size]]], light_threshold=20)
    scene = QGraphicsScene(0, 0, size, size)
    mask = MapCoverage((size, size), layers.coverage)
    QGraphicsPixmapItem(QPixmap.fromImage(array_image(layers.elevation)), mask)
    scene.addItem(mask)
    pixels = size*dpr
    image = QImage(pixels, pixels, QImage.Format.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(0, 0, size, size), QRectF(0, 0, size, size))
    painter.end()
    native = np.asarray(image.constBits()).reshape(pixels, pixels, 4)[:, :, 3]
    assert native[pixels//2, pixels//4] == 0 and native[pixels//2, pixels*3//4] == 255
    edge = native[pixels//2]
    assert np.unique(edge[(edge > 0) & (edge < 255)]).size >= 5
    # QtSvg lacks SVG masks; use a full SVG renderer when available.
    renderer = shutil.which("rsvg-convert")
    if renderer is None:
        return  # Native feathering above remains covered on all test platforms.
    svg = tmp_path/"soft.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                   f'width="{size}" height="{size}">'+''.join(layers_svg(p, (size, size), layers))+'</svg>')
    png = tmp_path/"soft.png"
    subprocess.run([renderer, str(svg), '-w', str(pixels), '-h', str(pixels), '-o', str(png)], check=True)
    exported = np.asarray(Image.open(png))[:, :, 3]
    assert np.max(np.abs(native.astype(int)-exported.astype(int))) <= 2


def test_soft_mask_high_zoom_uses_a_viewport_sized_buffer(application, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem
    from moonlabeler.ui import map_layers as ui

    allocations = []
    class TrackedImage(QImage):
        def __init__(self, *args):
            if len(args) >= 2 and all(isinstance(value, int) for value in args[:2]):
                allocations.append(args[:2])
            super().__init__(*args)
    monkeypatch.setattr(ui, "QImage", TrackedImage)
    scene = QGraphicsScene(0, 0, 1024, 1024)
    mask = MapCoverage((1024, 1024), [[[512, 0], [1024, 0], [1024, 1024], [512, 1024]]])
    source = QPixmap(1024, 1024)
    source.fill(Qt.GlobalColor.white)
    QGraphicsPixmapItem(source, mask)
    scene.addItem(mask)
    image = QImage(128, 128, QImage.Format.Format_RGBA8888)
    image.fill(0)
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, 128, 128), QRectF(508.8, 100, 6.4, 6.4))
    painter.end()
    assert allocations and max(w*h for w, h in allocations) <= 128*128
    alpha = np.asarray(image.constBits()).reshape(128, 128, 4)[:, :, 3]
    assert 0 < alpha[64, 0] < alpha[64, -1] < 255
