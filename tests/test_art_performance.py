# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Exercise the real art canvas rather than just timing geometry generation."""
import os
import statistics
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow
from moonlabeler.project import Project


@pytest.mark.parametrize('example,maximum', [('auto-copernicus', 70), ('auto-crescent', 200)])
def test_real_art_canvas_pan_zoom_and_opacity_stay_within_interactive_budget(example, maximum):
    root = Path(__file__).parents[1]
    source = root/f'examples/{example}.moonlabel'
    dem = root/'.cache/terrain/LDEM_16.LBL'
    if not source.exists():
        pytest.skip('Local photo project is unavailable')
    p = Project.load(source)
    if not Path(p.image_path).exists() or not dem.exists() or not dem.with_suffix('.IMG').exists():
        pytest.skip('Local photo and LOLA cache are unavailable')
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.error = lambda e: (_ for _ in ()).throw(AssertionError(str(e)))
    try:
        win.resize(1920, 1000)
        win.open_project(str(source))
        win.dem_path = str(dem)
        win.maximum.setValue(maximum)
        if example == 'auto-crescent':
            win.font_size.setValue(1.8)
            win.ui_font_step.setValue(.3)
        win.art_style.setCurrentIndex(win.art_style.findData('manuscript'))
        win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(15))
        win.apply_label_settings()
        deadline = time.monotonic()+30
        while win.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert not win.busy and win.map_layers.contours
        win.show()
        app.processEvents()
        win.canvas.fitInView(QRectF(0, 450, win.image.shape[1], 2650), Qt.AspectRatioMode.KeepAspectRatio)
        app.processEvents()
        elapsed = {}
        for mode in ('pan', 'zoom', 'grid_opacity', 'elevation_opacity', 'contour_opacity'):
            if mode == 'zoom':
                # Opposite real wheel steps around this fitted view used to
                # discard the outlined-text cache on every frame.
                win.canvas.scale(.27/win.canvas.transform().m11(), .27/win.canvas.transform().m11())
                app.processEvents()
            samples = []
            for index in range(5):
                start = time.perf_counter()
                if mode == 'pan':
                    bar = win.canvas.verticalScrollBar()
                    bar.setValue(bar.value()+(2 if index%2 else -2))
                elif mode == 'zoom':
                    scale = 1.2 if index%2 else 1/1.2
                    win.canvas.scale(scale, scale)
                else:
                    getattr(win, mode).setValue(40+index*5)
                win.canvas.viewport().repaint()
                app.processEvents()
                samples.append((time.perf_counter()-start)*1000)
            elapsed[mode] = statistics.median(samples[1:])
        print('Art canvas median frame times (ms):', elapsed)
        assert max(elapsed.values()) < 33, elapsed
        if example == 'auto-crescent':
            assert win.project.contour_interval == 'auto' and win.map_layers.contour_interval == 2.
            # Real continuous zoom crosses several text-cache density buckets;
            # alternating two warm scales alone hid 300–400 ms stalls here.
            scale = .22/win.canvas.transform().m11()
            win.canvas.scale(scale, scale)
            app.processEvents()
            frames = []
            for _ in range(12):
                start = time.perf_counter()
                win.canvas.scale(1.2, 1.2)
                win.canvas.viewport().repaint()
                app.processEvents()
                frames.append((time.perf_counter()-start)*1000)
                time.sleep(.02)
            print('Continuous zoom frame times (ms):', frames)
            assert max(frames) < 60, frames
    finally:
        win.dirty = False
        win.close()
