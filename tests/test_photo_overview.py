# SPDX-License-Identifier: GPL-3.0-or-later
"""Registered footprint geometry, modifier dragging and matching exports."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PIL import Image
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QThreadPool, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from moonlabeler import app as app_module
from moonlabeler.annotation_style import ART_STYLES
from moonlabeler.geometry import Geometry, unit
from moonlabeler.photo_overview import build_overview, overview_key, overview_rect, overview_document
from moonlabeler.project import Project, export_svg


def registered(matrix=None):
    g = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                 unit([1., 1., 0]), 384400., '2026-01-01T00:00:00+00:00')
    return Project(geometry=g, matrix=np.array([[600., 0, 150.], [0, 600., 100.]]) if matrix is None else matrix,
                   overview_enabled=True)


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application):
    win = app_module.MainWindow()
    win.error = lambda exc: (_ for _ in ()).throw(AssertionError(str(exc)))
    win.open_project(str(Path(__file__).parents[1]/'examples/demo.moonlabel'))
    yield win
    win.canvas._text_timer.stop()
    if win.canvas._text_cancel is not None:
        win.canvas._text_cancel.set()
    assert QThreadPool.globalInstance().waitForDone(10000)
    application.processEvents()
    win.canvas._text_timer.stop()
    win.dirty = False
    win.close()


@pytest.mark.parametrize('rotated,mirrored', [(False, False), (False, True), (True, False), (True, True)])
def test_crop_footprint_follows_rotation_and_mirroring_without_changing_registration(rotated, mirrored):
    p = registered()
    if rotated:
        p.matrix[:, :2] = [[0, -600], [600, 0]]
    if mirrored:
        p.matrix[:, 0] *= -1
    matrix, geometry = p.matrix.copy(), deepcopy(p.geometry.to_dict())
    model = build_overview(p, (200, 300, 3))
    assert len(model.footprint) == 1
    points = np.asarray(model.footprint[0])
    extent = np.ptp(points, axis=0)
    scale = model.size*.47
    expected = np.array([200, 300] if rotated else [300, 200])/600*scale
    assert np.max(abs(extent-expected)) < 3
    assert np.max(abs(points.mean(axis=0)-(model.size-1)/2)) < 3
    assert np.allclose(model.center, (0, 0), atol=1e-10)
    assert np.array_equal(p.matrix, matrix) and p.geometry.to_dict() == geometry


def test_full_disk_footprint_handles_off_disk_corners_and_no_visible_field():
    p = registered(np.array([[80., 0, 150.], [0, 80., 100.]]))
    model = build_overview(p, (200, 300, 3))
    points = np.asarray(model.footprint[0])
    assert np.max(abs(np.ptp(points, axis=0)-model.size*.94)) < 3
    p.matrix[:, 2] += 10000
    missing = build_overview(p, (200, 300, 3))
    assert not missing.footprint and missing.center is None


def test_lens_correction_and_cache_inputs_follow_the_photo_geometry():
    p = registered()
    shape = (200, 300, 3)
    before = build_overview(p, shape)
    key = overview_key(p, shape)
    p.overview_position = [22, 35]
    p.art_style, p.map_light_mask, p.map_light_threshold = 'redalert', True, 71
    p.labels['test'] = {'text': '手工文字', 'hidden': True}
    assert overview_key(p, shape) == key
    p.identification['lens_distortion'] = {'center': [150., 100.], 'scale': 300., 'k': 1.2}
    after = build_overview(p, shape)
    assert overview_key(p, shape) != key
    assert np.prod(np.ptp(after.footprint[0], axis=0)) < np.prod(np.ptp(before.footprint[0], axis=0))
    key = overview_key(p, shape)
    p.geometry.sun = -p.geometry.sun
    assert overview_key(p, shape) != key


def test_locator_keeps_its_geographic_annotations_in_the_compact_layout():
    model = build_overview(registered(), (200, 300, 3))
    assert model.grid and model.footprint and model.earth is not None
    root = ET.fromstring(overview_document(model))
    texts = [node.text for node in root.findall('.//{http://www.w3.org/2000/svg}text')]
    assert all(label in texts for label in ('N', 'Earth', 'LAT', 'LON'))
    assert any('0.00° N' in text for text in texts)
    assert any('0.00° E' in text for text in texts)


def test_overview_position_roundtrips_and_legacy_projects_remain_opt_in(tmp_path):
    p = registered()
    p.overview_position = [33.25, 51.5]
    path = tmp_path/'照片区域.moonlabel'
    p.save(path)
    loaded = Project.load(path)
    assert loaded.overview_enabled and loaded.overview_position == p.overview_position
    data = json.loads(path.read_text(encoding='utf-8'))
    for key in ('overview_enabled', 'overview_position'):
        del data['style'][key]
    path.write_text(json.dumps(data), encoding='utf-8')
    legacy = Project.load(path)
    assert not legacy.overview_enabled and legacy.overview_position is None
    x, y, width, height = overview_rect((600, 800, 3))
    assert x == y == 12 and width < 800 and height < 600
    assert overview_rect((600, 800, 3), (-10, -10))[:2] == (0, 0)
    x, y, width, height = overview_rect((600, 800, 3), (10000, 10000))
    assert x+width == 800 and y+height == 600


@pytest.mark.parametrize('field,value', [('overview_enabled', 'true'), ('overview_position', [1]),
                                       ('overview_position', [1, float('inf')])])
def test_invalid_overview_settings_are_rejected(tmp_path, field, value):
    path = tmp_path/'invalid.moonlabel'
    registered().save(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['style'][field] = value
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match=field):
        Project.load(path)


def mouse(canvas, kind, point, modifiers=Qt.KeyboardModifier.NoModifier):
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    QApplication.sendEvent(canvas.viewport(), QMouseEvent(kind, QPointF(point), QPointF(canvas.viewport().mapToGlobal(point)),
                                                        button, buttons, modifiers))


def test_overview_toggle_and_gestures_reuse_rendering_and_preserve_labels(window, monkeypatch, application):
    win = window
    labels, matrix, rgb = deepcopy(win.project.labels), win.project.matrix.copy(), win.image.copy()
    positions = win.annotation_entries()
    win.font_size.setValue(2.4)
    old_font = win.project.font_percent
    win.overview_toggle.setChecked(True)
    item, model = win.overview_item, win._overview_model
    assert item is not None and item.pos().x() == item.pos().y() == min(rgb.shape[:2])*.02
    assert win.style_pending and win.project.font_percent == old_font
    win.resize(1300, 850)
    win.show()
    application.processEvents()
    win.canvas.scale(1.5, 1.5)
    win.canvas.centerOn(item.sceneBoundingRect().center())
    application.processEvents()
    win.canvas.viewport().grab()
    monkeypatch.setattr(app_module, 'build_overview', lambda *a, **k: pytest.fail('Navigation and moving the inset must reuse its model'))
    monkeypatch.setattr(item.renderer, 'render', lambda *a, **k: pytest.fail('A navigation frame must reuse the raster preview'))
    before = item.pos()
    start = win.canvas.mapFromScene(item.sceneBoundingRect().center())
    mouse(win.canvas, QEvent.Type.MouseButtonPress, start)
    mouse(win.canvas, QEvent.Type.MouseMove, start-QPoint(30, 20))
    mouse(win.canvas, QEvent.Type.MouseButtonRelease, start-QPoint(30, 20))
    assert item.pos() == before
    start = win.canvas.mapFromScene(item.sceneBoundingRect().center())
    ctrl = Qt.KeyboardModifier.ControlModifier  # Qt maps this to Cmd on macOS.
    mouse(win.canvas, QEvent.Type.MouseButtonPress, start, ctrl)
    mouse(win.canvas, QEvent.Type.MouseMove, start+QPoint(30, 20), ctrl)
    mouse(win.canvas, QEvent.Type.MouseButtonRelease, start+QPoint(30, 20), ctrl)
    assert item.pos() != before and win.project.overview_position == [item.pos().x(), item.pos().y()]
    event = QWheelEvent(QPointF(start), QPointF(win.canvas.viewport().mapToGlobal(start)), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    scale = win.canvas.transform().m11()
    QApplication.sendEvent(win.canvas.viewport(), event)
    assert win.canvas.transform().m11() > scale
    win.canvas.viewport().grab()
    win.refresh_photo_overview()
    assert win.overview_item is item and win._overview_model is model
    assert win.annotation_entries() == positions and win.project.labels == labels
    assert np.array_equal(win.project.matrix, matrix) and np.array_equal(win.image, rgb)
    win.overview_toggle.setChecked(False)
    assert win.overview_item is None and win.style_pending


@pytest.mark.parametrize('style', ART_STYLES)
def test_overview_exports_and_reopened_project_use_the_saved_position(window, tmp_path, style):
    win = window
    win.project.art_style = style
    win.sync_controls()
    win.refresh_annotations()
    win.overview_toggle.setChecked(True)
    win.overview_item.setPos(180.25, 240.5)
    png, svg = tmp_path/'photo.png', tmp_path/'photo.svg'
    win.overview_item.setSelected(True)
    win.render_png(png)
    export_svg(svg, win.image, win.annotation_entries(), win.project, win.annotation_leaders(),
               layers=win.map_layers, display_image=win.display_image, overview=win._overview_model)
    ns = {'s': 'http://www.w3.org/2000/svg'}
    root = ET.parse(svg)
    assert '180.250000 240.500000' in root.find('.//s:g[@id="photo-overview"]', ns).get('transform')
    assert root.findall('.//s:path[@class="photo-footprint"]', ns)
    rendered = QImage(win.image.shape[1], win.image.shape[0], QImage.Format.Format_RGB32)
    rendered.fill(0xff000000)
    painter = QPainter(rendered)
    QSvgRenderer(str(svg)).render(painter)
    painter.end()
    native = np.asarray(Image.open(png).convert('RGB')).astype(float)
    vector = np.asarray(rendered.constBits()).reshape(rendered.height(), rendered.width(), 4)[:, :, :3][:, :, ::-1].astype(float)
    x, y, w, h = map(round, overview_rect(win.image.shape, win.project.overview_position))
    assert np.abs(native[y:y+h, x:x+w]-vector[y:y+h, x:x+w]).mean() < 2.
    assert win.overview_item.isSelected() and not win.overview_item._export_mode
    project = tmp_path/'moved.moonlabel'
    win.project.save(project)
    win.dirty = False
    win.open_project(project)
    assert win.project.overview_enabled and win.overview_item.pos() == QPointF(180.25, 240.5)
    assert win.project.art_style == win.overview_item.art_style == style


def test_art_themes_update_cached_appearance_without_reprojecting_or_moving_the_locator(window, monkeypatch, application):
    win = window
    win.overview_toggle.setChecked(True)
    item, model = win.overview_item, win._overview_model
    item.setPos(180.25, 240.5)
    position, original_preview = item.pos(), item.preview.copy()
    image, rgb, matrix = model.image.copy(), win.image.copy(), win.project.matrix.copy()
    geometry, key = deepcopy(win.project.geometry.to_dict()), win._overview_key
    monkeypatch.setattr(app_module, 'build_overview', lambda *a, **k: pytest.fail('Changing theme must reuse the projected globe'))
    for style in ART_STYLES[1:]:
        previous = item.preview.cacheKey()
        win.art_style.setCurrentIndex(win.art_style.findData(style))
        win.elevation_toggle.setChecked(False)
        win.contour_toggle.setChecked(False)
        assert item.preview.cacheKey() == previous, 'A staged theme must not alter the applied locator'
        win.apply_label_settings()
        assert win.overview_item is item and item.model is model and win._overview_key == key
        assert item.art_style == style and item.preview != original_preview and item.pos() == position
        cached = item.preview.cacheKey()
        with monkeypatch.context() as navigation:
            navigation.setattr(item.renderer, 'render', lambda *a, **k: pytest.fail('Navigation must paint the cached preview'))
            win.refresh_photo_overview()
            win.canvas.scale(1.03, 1.03)
            win.canvas.translate(3, 2)
            application.processEvents()
            win.canvas.viewport().grab()
        assert item.preview.cacheKey() == cached
    win.art_style.setCurrentIndex(win.art_style.findData('standard'))
    win.apply_label_settings()
    assert item.preview == original_preview and item.pos() == position
    assert np.array_equal(model.image, image) and np.array_equal(win.image, rgb)
    assert np.array_equal(win.project.matrix, matrix) and win.project.geometry.to_dict() == geometry


def test_overview_cache_invalidates_after_a_registration_change(window):
    win = window
    win.overview_toggle.setChecked(True)
    before = win._overview_model
    win.project.matrix[:, 2] += [20, -10]
    win.refresh_photo_overview()
    assert win._overview_model is not before
    before = win._overview_model
    win.art_style.setCurrentIndex(win.art_style.findData('redalert'))
    win.elevation_toggle.setChecked(False)
    win.contour_toggle.setChecked(False)
    win.apply_label_settings()
    assert win._overview_model is before and win.overview_item is not None


def test_overview_control_becomes_available_after_manual_registration(window):
    win = window
    matrix = win.project.matrix
    win.project.matrix = None
    win.refresh_photo_overview()
    assert not win.overview_toggle.isEnabled()
    win.project.matrix = matrix
    win.refresh_photo_overview()
    assert win.overview_toggle.isEnabled()
    win.overview_toggle.setChecked(True)
    assert win.overview_item is not None


def test_rounded_card_captures_its_background_but_not_transparent_corners(window):
    win = window
    win.overview_toggle.setChecked(True)
    item = win.overview_item
    corner = item.pos()+QPointF(item.rect.width()*.002, item.rect.height()*.002)
    hits = win.canvas.scene().items(corner)
    assert item not in hits and win.photo_item in hits
    background = item.pos()+QPointF(item.rect.width()*.08, item.rect.height()*.08)
    assert item in win.canvas.scene().items(background)
    assert item in win.canvas.scene().items(item.sceneBoundingRect().center())


@pytest.mark.parametrize('style', ART_STYLES)
def test_graticule_remains_visible_on_bright_and_dark_surface_at_small_size(application, style):
    model = build_overview(registered(), (200, 300, 3))

    def render(value):
        image = QImage(180, 206, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)
        painter = QPainter(image)
        QSvgRenderer(overview_document(value, style).encode('utf-8')).render(painter)
        painter.end()
        return np.frombuffer(image.constBits(), np.uint8).reshape(206, image.bytesPerLine()//4, 4)[:, :180, :3].copy()

    plain = render(replace(model, grid=[]))
    delta = np.max(abs(render(model).astype(int)-plain.astype(int)), axis=2)
    brightness = plain.mean(axis=2)
    assert np.count_nonzero((delta > 25) & (brightness > 80)) > 80
    assert np.count_nonzero((delta > 25) & (brightness < 50)) > 80


def test_overview_is_independent_of_the_art_style_section(window, application):
    win = window
    win.overview_toggle.setChecked(True)
    win.sync_controls()
    assert win.project.art_style == 'standard' and not win.map_styles_toggle.isChecked()
    win.workspace_tabs.setCurrentIndex(1)
    win.show()
    application.processEvents()
    assert win.overview_toggle.isVisible() and not win.map_styles_block.isVisible()
    model = win._overview_model
    win.art_style.setCurrentIndex(win.art_style.findData('redalert'))
    win.art_style.setCurrentIndex(win.art_style.findData('standard'))
    win.apply_label_settings()
    assert win.project.overview_enabled and win.overview_item.model is model
