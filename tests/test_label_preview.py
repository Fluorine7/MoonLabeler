# SPDX-License-Identifier: GPL-3.0-or-later
"""Viewport caching must preserve the photograph-space size of every caption."""
import os
import threading
import time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from moonlabeler.app import Annotation, Canvas
from moonlabeler.project import Project


@pytest.mark.parametrize('style', ['standard', 'manuscript', 'topographic'])
def test_cached_text_matches_vector_size_across_wheel_zoom_buckets(style):
    app = QApplication.instance() or QApplication([])
    canvas = Canvas()
    canvas.resize(1400, 600)
    canvas.setSceneRect(-10000, -10000, 20000, 20000)
    canvas.setBackgroundBrush(QColor('black'))
    project = Project(font_size=73, art_style=style)
    label = Annotation({'id': 'test', 'name': 'Copernicus'}, (0, 0), '哥白尼 · Copernicus',
                       project, lambda *args: None, lambda *args: None)
    canvas.scene().addItem(label)
    canvas.show()
    try:
        for scale in (.2, .3, .4, .6, 1., 1.2, 2., .2):
            canvas.scale(scale/canvas.transform().m11(), scale/canvas.transform().m11())
            canvas.centerOn(label.boundingRect().center())
            boxes = []
            for cached in (True, False):
                if cached:
                    label.set_export_mode(False)
                    canvas.update_text_caches()
                else:
                    label.set_export_mode(True)
                app.processEvents()
                image = canvas.viewport().grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                pixels = np.frombuffer(image.bits(), np.uint8).reshape(image.height(), image.width(), 4)
                y, x = np.nonzero(pixels[:, :, :3].max(axis=2) > 120)
                boxes.append(np.array([x.min(), y.min(), x.max(), y.max()]))
            assert np.max(abs(boxes[0]-boxes[1])) <= 2, (style, scale, boxes)
            assert label.font_size == 73 and project.font_size == 73
    finally:
        canvas.close()


@pytest.mark.parametrize('style,kind,text', [
    ('standard', 'Crater', '哥白尼 · Copernicus'),
    ('topographic', 'Crater', '哥白尼 · Copernicus'),
    ('manuscript', 'Mons, montes', '斯匹次卑尔根山脉 · Montes Spitzbergen'),
    ('manuscript', 'Mare', '雨海 · MARE IMBRIUM'),
])
def test_caption_preview_preserves_vector_ink_and_holes(style, kind, text):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter
    from moonlabeler.app import paint_caption, rasterize_caption
    app = QApplication.instance() or QApplication([])
    label = Annotation({'id': 'test', 'name': text, 'kind': kind}, (0, 0), text,
                       Project(font_size=110, art_style=style), lambda *args: None, lambda *args: None)
    bounds = label.boundingRect()
    size = round(bounds.width()*1.7), round(bounds.height()*1.7)
    request = label.text_raster_request(size)
    preview = rasterize_caption(*request)
    vector = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    vector.fill(Qt.GlobalColor.transparent)
    painter = QPainter(vector)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size[0]/bounds.width(), size[1]/bounds.height())
    painter.translate(-bounds.x(), -bounds.y())
    paint_caption(painter, *request[2:])
    painter.end()
    def pixels(image):
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(rgba.bits(), np.uint8).reshape(*size[::-1], 4).astype(np.int16)
    # Separate anti-aliased contours can differ at a few overlapping edge
    # pixels. Halos, counters, curved placement and the foreground must agree.
    assert np.abs(pixels(preview)-pixels(vector)).mean() < .5


def test_zoom_refines_text_in_background_and_discards_removed_labels(monkeypatch):
    from moonlabeler import app as app_module
    app = QApplication.instance() or QApplication([])
    canvas = Canvas()
    canvas.resize(800, 500)
    canvas.setSceneRect(-1000, -1000, 2000, 2000)
    label = Annotation({'id': 'test', 'name': 'Copernicus'}, (0, 0), '哥白尼 · Copernicus',
                       Project(font_size=73, art_style='manuscript'), lambda *args: None, lambda *args: None)
    canvas.scene().addItem(label)
    canvas.scale(.2, .2)
    canvas.show()
    canvas.centerOn(label.boundingRect().center())
    app.processEvents()
    canvas.viewport().grab()
    before = label._preview_size
    calls, release = [], threading.Event()
    original = app_module.rasterize_caption
    def render(*args):
        calls.append(threading.get_ident())
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(app_module, 'rasterize_caption', render)
    try:
        canvas.scale(2, 2)
        canvas.viewport().grab()
        assert label._preview_size == before and label._cache_size != before
        assert not calls, 'A wheel frame must reuse the previous pixels without blocking on glyph painting'
        canvas.refine_text_caches()
        assert canvas._text_worker is not None
        canvas.scene().clear()  # A newly opened image can delete all old scene items mid-job.
        release.set()
        deadline = time.monotonic()+5
        while canvas._text_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert canvas._text_worker is None
        assert calls and all(thread != threading.get_ident() for thread in calls)
        assert not canvas.scene().items()
    finally:
        release.set()
        canvas.close()


def test_complex_caption_refinement_keeps_the_ui_responsive():
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    canvas = Canvas()
    canvas.resize(1100, 730)
    canvas.setSceneRect(-10000, -10000, 20000, 20000)
    label = Annotation({'id': '4017', 'name': 'Montes Spitzbergen', 'kind': 'Mons, montes'}, (0, 0),
                       '斯匹次卑尔根山脉 · Montes Spitzbergen', Project(font_size=110, art_style='manuscript'),
                       lambda *args: None, lambda *args: None)
    canvas.scene().addItem(label)
    canvas.scale(.2, .2)
    canvas.show()
    canvas.centerOn(label.boundingRect().center())
    app.processEvents()
    canvas.viewport().grab()
    gaps, last = [], [time.monotonic()]
    pulse = QTimer()
    pulse.setInterval(8)
    def heartbeat():
        now = time.monotonic()
        gaps.append(now-last[0])
        last[0] = now
    pulse.timeout.connect(heartbeat)
    pulse.start()
    try:
        for scale in (4., .2, 4.):
            canvas.scale(scale/canvas.transform().m11(), scale/canvas.transform().m11())
            canvas.centerOn(label.boundingRect().center())
            canvas.refine_text_caches()
            deadline = time.monotonic()+5
            while canvas._text_worker is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            assert canvas._text_worker is None
            QTest.qWait(20)
        assert gaps and max(gaps) < .06, f'UI blocked for {max(gaps)*1000:.1f} ms while refining one caption'
    finally:
        pulse.stop()
        canvas.close()


def test_evicted_caption_reuses_a_bounded_preview_and_refines_after_navigation(monkeypatch):
    from PySide6.QtGui import QPixmap, QPixmapCache
    from moonlabeler import app as app_module
    app = QApplication.instance() or QApplication([])
    canvas = Canvas()
    canvas.resize(900, 600)
    canvas.setSceneRect(-3000, -3000, 6000, 6000)
    label = Annotation({'id': 'test', 'name': 'Copernicus'}, (0, 0), '哥白尼 · Copernicus',
                       Project(font_size=110, art_style='manuscript'), lambda *args: None, lambda *args: None)
    canvas.scene().addItem(label)
    canvas.scale(.2, .2)
    canvas.show()
    canvas.centerOn(label.boundingRect().center())
    app.processEvents()
    canvas.viewport().grab()
    # Reproduce the global Qt cache discarding a caption while keeping its item.
    QPixmapCache.remove(label._preview_key)
    calls = []
    original = app_module.rasterize_caption
    def render(*args):
        calls.append(threading.get_ident())
        return original(*args)
    monkeypatch.setattr(app_module, 'rasterize_caption', render)
    try:
        canvas.scale(8, 8)
        canvas.centerOn(label.boundingRect().center())
        canvas.viewport().grab()
        assert not calls, 'Navigation must reuse caption pixels after global cache eviction'
        canvas.refine_text_caches()
        deadline = time.monotonic()+5
        while canvas._text_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.001)
        assert canvas._text_worker is None
        assert calls and all(thread != threading.get_ident() for thread in calls)
        assert label._preview_size == label._cache_size
        assert QPixmapCache.find(label._preview_key, QPixmap())
        assert label._fallback_preview.width()*label._fallback_preview.height() <= 65536
    finally:
        canvas.close()


@pytest.mark.parametrize('gesture', ['wheel', 'pan'])
def test_navigation_cancels_the_remainder_of_an_inflight_text_batch(monkeypatch, gesture):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from moonlabeler import app as app_module
    app = QApplication.instance() or QApplication([])
    canvas = Canvas()
    canvas.resize(900, 600)
    canvas.setSceneRect(-3000, -3000, 6000, 6000)
    project = Project(font_size=73, art_style='manuscript')
    for number in range(6):
        label = Annotation({'id': str(number), 'name': 'Copernicus'}, (0, number*190),
                           '哥白尼 · Copernicus', project, lambda *args: None, lambda *args: None)
        label.setPos(0, number*190)
        canvas.scene().addItem(label)
    canvas.scale(.2, .2)
    canvas.show()
    canvas.centerOn(250, 500)
    app.processEvents()
    canvas.viewport().grab()
    release, started, calls = threading.Event(), threading.Event(), []
    original = app_module.rasterize_caption
    def render(*args):
        calls.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(app_module, 'rasterize_caption', render)
    try:
        canvas.scale(2, 2)
        canvas.refine_text_caches()
        assert started.wait(5)
        viewport = canvas.viewport()
        start = viewport.rect().center()
        if gesture == 'wheel':
            event = QWheelEvent(QPointF(start), QPointF(viewport.mapToGlobal(start)), QPoint(), QPoint(0, 120),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            app.sendEvent(viewport, event)
        else:
            before = canvas.horizontalScrollBar().value()
            for kind, position, button, buttons in (
                    (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                    (QEvent.Type.MouseMove, start+QPoint(60, 30), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
                    (QEvent.Type.MouseButtonRelease, start+QPoint(60, 30), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)):
                app.sendEvent(viewport, QMouseEvent(kind, QPointF(position), QPointF(viewport.mapToGlobal(position)),
                                                   button, buttons, Qt.KeyboardModifier.NoModifier))
            assert canvas.horizontalScrollBar().value() != before
        canvas._text_timer.stop()  # Inspect the interrupted batch before the next idle refinement.
        release.set()
        deadline = time.monotonic()+5
        while canvas._text_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert canvas._text_worker is None
        assert len(calls) == 1, 'A gesture must stop the old batch after its current caption'
        assert all(thread != threading.get_ident() for thread in calls)
    finally:
        release.set()
        canvas.close()


def test_limb_crossing_invalidates_pending_text_preview_even_when_size_matches_again(monkeypatch):
    from moonlabeler import app as app_module
    from moonlabeler.geometry import Geometry
    app = QApplication.instance() or QApplication([])
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([1., 0, 0]), 384400., '')
    project = Project(art_style='manuscript', font_size=25, geometry=geometry,
                      matrix=np.array([[300., 0, 600.], [0, 300., 400.]]))
    canvas = Canvas()
    canvas.resize(800, 500)
    canvas.setSceneRect(0, 0, 1200, 800)
    label = Annotation({'id': 'sea', 'name': 'Mare Imbrium', 'kind': 'Mare'}, (600, 400),
                       'MARE IMBRIUM', project, lambda *args: None, lambda *args: None)
    canvas.scene().addItem(label)
    label.setPos(450, 380)
    canvas.scale(.5, .5)
    canvas.show()
    canvas.centerOn(label.sceneBoundingRect().center())
    app.processEvents()
    canvas.viewport().grab()
    release, started, installed = threading.Event(), threading.Event(), []
    original = app_module.rasterize_caption
    def render(*args):
        started.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(app_module, 'rasterize_caption', render)
    monkeypatch.setattr(label, 'install_text_preview', lambda *args: installed.append(args))
    try:
        canvas.scale(2, 2)
        canvas.refine_text_caches()
        assert started.wait(5)
        size = label._cache_size
        label.setPos(10, 380)
        assert not label.typography.arc and label._preview_size is None
        label.setPos(450, 380)
        assert label.typography.arc and label._cache_size == size
        # Hide the canvas while the old job completes, so only its result
        # handler (not a fresh paint) can try to install a preview.
        canvas.hide()
        release.set()
        deadline = time.monotonic()+5
        while canvas._text_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert canvas._text_worker is None and not installed
    finally:
        release.set()
        canvas.close()
