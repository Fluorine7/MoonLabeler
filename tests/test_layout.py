# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from itertools import combinations

from moonlabeler.layout import (LabelBox, arrange_labels, leader_segment,
                               rect_intersects, segment_hits_rect, segments_cross)


def test_close_features_get_different_directions_without_crossings():
    labels = [LabelBox(str(i), point, 110, 22, 5) for i, point in enumerate(
        ((190, 160), (240, 175), (285, 185), (215, 220), (280, 235)))]
    placed, omitted = arrange_labels(labels, 600, 400, gap=8)
    assert not omitted
    for first, second in combinations(placed.values(), 2):
        assert not rect_intersects(first, second, padding=4)
    lines = {label.key: leader_segment(label.anchor, placed[label.key]) for label in labels}
    for first, second in combinations(lines.values(), 2):
        assert not segments_cross(first, second)
    for key, line in lines.items():
        for other, rect in placed.items():
            if key != other:
                assert not segment_hits_rect(line, rect)
    for x, y, w, h in placed.values():
        assert x >= 8 and y >= 8 and x+w <= 592 and y+h <= 392
    # Both sides of the crowded group are used; no downward stacking rule.
    assert min(rect[0] for rect in placed.values()) < 190
    assert max(rect[0] for rect in placed.values()) > 280


def test_pinned_label_stays_fixed_and_auto_caption_avoids_it():
    fixed = LabelBox('manual', (170, 160), 100, 22, fixed=(185, 140))
    other = LabelBox('auto', (180, 180), 100, 22)
    placed, omitted = arrange_labels([other, fixed], 500, 350)
    assert not omitted
    assert placed['manual'] == (185, 140, 100, 22)
    assert not rect_intersects(placed['manual'], placed['auto'])


def test_unplaceable_caption_is_omitted_without_changing_user_data():
    label = LabelBox('long', (80, 60), 250, 30)
    placed, omitted = arrange_labels([label], 180, 120)
    assert not placed and omitted == {'long'}
    assert label.fixed is None and not label.force


def test_leader_ends_at_nearest_caption_edge_not_text_baseline():
    line = leader_segment((100, 100), (150, 70, 120, 20))
    assert line[2:] == (150, 90)
    assert line[0] > 100 and line[1] < 100
    assert not segment_hits_rect(line, (150, 70, 120, 20))


def test_large_crater_leader_starts_on_rim_not_at_center():
    contour = [[(80, 70), (120, 70), (120, 130), (80, 130), (80, 70)]]
    line = leader_segment((100, 100), (150, 90, 60, 20), outline=contour)
    assert line == (120., 100., 150, 100)
    interior = leader_segment((100, 100), (105, 95, 5, 5), outline=contour)
    assert interior[:2] == interior[2:]


def test_region_name_can_cover_its_own_formation_but_preserves_fixed_names():
    labels = [LabelBox('map-name', (150, 150), 100, 24, region=True),
              LabelBox('pinned', (350, 250), 80, 24, fixed=(300, 100), region=True)]
    placements, _ = arrange_labels(labels, 600, 400)
    assert placements['map-name'][:2] == (100, 138)
    assert placements['pinned'][:2] == (300, 100)
