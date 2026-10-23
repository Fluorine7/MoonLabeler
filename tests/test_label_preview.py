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
