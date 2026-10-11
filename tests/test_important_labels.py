# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from moonlabeler.app import MainWindow


def test_copernicus_survives_full_moon_layout_without_landing_layer():
    path = Path(__file__).parents[1]/'examples/auto-regression-0511/full-color-user-automatic.moonlabel'
    if not path.exists():
        pytest.skip('Local photographer project is not distributed')
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.open_project(str(path))
        assert window.image is not None
        assert not window.project.show_landing_sites
        assert 'Copernicus' in {item.feature['name'] for item in window.annotation_items}
    finally:
        window.dirty = False
        window.close()


def test_ordinary_centers_yield_to_reserved_label_and_leader():
    from moonlabeler.layout import LabelBox, arrange_labels, leader_segment, rect_intersects, segment_hits_rect, segments_cross
    major = LabelBox('major', (250, 200), 120, 24, 5, important=True)
    # Dense minor terrain can occupy every nearby direction. It must not
    # displace the major caption, including when it comes earlier in input.
    minor = [LabelBox(f'{x}:{y}', (x, y), 40, 15, 4)
             for x in range(130, 391, 20) for y in range(140, 261, 20) if (x, y) != major.anchor]
    reserved, _ = arrange_labels([major], 600, 400, max_labels=100)
    placed, omitted = arrange_labels(minor+[major], 600, 400, max_labels=100)
    assert placed['major'] == reserved['major']
    assert omitted and len(placed) <= 100
    major_line = leader_segment(major.anchor, placed['major'])
    for label in minor:
        if label.key not in placed:
            continue
        line = leader_segment(label.anchor, placed[label.key])
        assert not rect_intersects(placed['major'], placed[label.key])
        assert not segment_hits_rect(line, placed['major'])
        assert not segment_hits_rect(major_line, placed[label.key])
        assert not segments_cross(line, major_line)
        marker = (label.anchor[0]-4, label.anchor[1]-4, 8, 8)
        assert not rect_intersects(marker, placed['major'])
        assert not segment_hits_rect(major_line, marker)


def test_important_label_respects_pinned_positions_and_image_bounds():
    from moonlabeler.layout import LabelBox, arrange_labels, rect_intersects
    major = LabelBox('major', (250, 200), 120, 24, 5, important=True)
    pinned = LabelBox('manual', (400, 100), 120, 24, fixed=(265, 205))
    placed, omitted = arrange_labels([major, pinned], 600, 400, max_labels=2)
    assert not omitted and placed['manual'] == (265, 205, 120, 24)
    assert not rect_intersects(placed['manual'], placed['major'])
    impossible = LabelBox('too-wide', (50, 50), 700, 24, important=True)
    placed, omitted = arrange_labels([impossible], 600, 400, max_labels=2)
    assert not placed and omitted == {'too-wide'}
