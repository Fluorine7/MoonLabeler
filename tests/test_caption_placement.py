# SPDX-License-Identifier: GPL-3.0-or-later
"""Artistic names follow their final placement, including exported user pins."""
import os
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from moonlabeler._opencv import cv2
from moonlabeler.annotation_style import caption_text, caption_typography, placed_caption_typography
from moonlabeler.app import Annotation, MainWindow
from moonlabeler.geometry import Geometry
from moonlabeler.project import Project, export_svg


def lunar_project(**options):
    geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                        np.array([-1., 0, 0]), 384400., '2026-01-01T00:00:00+00:00')
    return Project(geometry=geometry, matrix=np.array([[240., 0, 500.], [0, 240., 350.]]),
                   art_style='manuscript', language='英文', font_size=20, illuminated_only=False, **options)


FEATURE = {'id': 'sea', 'name': 'Mare Imbrium', 'kind': 'Mare, maria', 'diameter': 1145,
           'lat': 0., 'lon': 0.}


@pytest.mark.parametrize('kind', ['Mare, maria', 'Oceanus, oceani', 'Mons, montes'])
def test_arcs_require_the_whole_caption_on_the_disk_even_with_an_on_disk_anchor(kind):
    p = lunar_project()
    feature = dict(FEATURE, kind=kind)
    text = caption_text(p, feature)
    base = caption_typography(p, feature)
    assert base.arc
    # All of this test's visible sphere is dark: brightness must not flatten it.
    assert placed_caption_typography(p, feature, text, 20, (400, 340)) == base
    for position in ((30, 340), (760, 340), (400, 50), (400, 640), (650, 340)):
        flat = placed_caption_typography(p, feature, text, 20, position)
        assert flat.arc == 0
        assert (flat.tracking, flat.uppercase, flat.scale) == (base.tracking, base.uppercase, base.scale)
    # No disk geometry is available before registration; retain the preset.
    p.matrix = None
    assert placed_caption_typography(p, feature, text, 20, (30, 340)) == base


@pytest.mark.parametrize('mirrored', [False, True])
def test_caption_placement_uses_rotated_mirrored_and_distorted_registration(mirrored):
    p = lunar_project()
    angle = .7
    p.matrix[:, :2] = np.array([[290., 0], [0, 180.]]) @ np.array([
        [np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    if mirrored:
        p.matrix[:, 0] *= -1
    p.identification = {'lens_distortion': {'center': [500., 350.], 'scale': 240., 'k': .3}}
    text = caption_text(p, FEATURE)
    assert placed_caption_typography(p, FEATURE, text, 20, (400, 340)).arc
    # This small arc sits on the expanded, lens-distorted limb. Ignoring the
    # correction would incorrectly treat it as off disk.
    assert placed_caption_typography(p, FEATURE, 'MARE', 8, (810, 345)).arc
    assert not placed_caption_typography(p, FEATURE, text, 20, (940, 340)).arc


def test_moving_a_caption_across_the_limb_preserves_size_and_reserves_both_shapes():
    application = QApplication.instance() or QApplication([])
    p = lunar_project()
    moved = []
    label = Annotation(FEATURE, (500, 350), caption_text(p, FEATURE), p,
                       lambda *args: moved.append(args), lambda *args: None)
    bounds = label.layout_bounds()
    for position, curved in (((400, 340), True), ((30, 340), False), ((400, 340), True)):
        label.setPos(*position)
        assert bool(label.typography.arc) is curved
        assert label.pos() == QPointF(*position)
        assert label.layout_bounds() == bounds and bounds.contains(label.boundingRect())
        assert label.font_size == p.font_size == 20
        assert moved[-1] == ('sea', list(position))


@pytest.mark.parametrize('position,curved', [((430, 340), True), ((40, 340), False), ((700, 340), False)])
def test_pinned_native_png_and_editable_svg_use_the_same_caption_shape(tmp_path, position, curved):
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win.project = lunar_project(labels={'sea': {'position': list(position)}})
        win.catalog = [FEATURE]
        win.set_image(np.zeros((700, 1000, 3), np.uint8))
        label, = win.annotation_items
        assert bool(label.typography.arc) is curved
        assert label.pos() == QPointF(*position)
        assert win.project.labels['sea']['position'] == list(position)
        native_path, svg_path = tmp_path/'caption.png', tmp_path/'caption.svg'
        win.render_png(native_path)
        export_svg(svg_path, win.image, win.annotation_entries(), win.project, win.annotation_leaders())
        root = ET.parse(svg_path)
        ns = {'s': 'http://www.w3.org/2000/svg'}
        text = root.find('.//s:g[@id="label-text-0"]', ns)
        assert text is not None and ''.join(text.itertext()) == 'MARE IMBRIUM'
        if not curved:
            assert all(glyph.get('transform').endswith('rotate(0.000)') for glyph in text.findall('s:g', ns))
        native = QImage(str(native_path)).convertToFormat(QImage.Format.Format_RGB32)
        svg = QImage(1000, 700, QImage.Format.Format_RGB32)
        svg.fill(0xff000000)
        painter = QPainter(svg)
        QSvgRenderer(str(svg_path)).render(painter)
        painter.end()
        def face(image):
            pixels = np.asarray(image.constBits()).reshape(700, 1000, 4)[:, :, :3]
            # Include antialiased thin stems but exclude the dark halo.
            return (pixels > 80).all(axis=2)
        first, second = face(native), face(svg)
        # SVG text hinting and vector outlines differ by a pixel or two for
        # small, axis-aligned serifs. Check glyph coverage with that tolerance;
        # ignored tracking previously shortened this caption by over 30 px.
        for expected, actual in ((first, second), (second, first)):
            nearby = cv2.dilate(actual.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            assert (expected & nearby).sum()/expected.sum() > .99
    finally:
        win.dirty = False
        win.close()
