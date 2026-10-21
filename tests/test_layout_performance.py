# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Keep the 0.6.1 layout contract while reducing spatial-query work."""
import json
import random
from pathlib import Path
from moonlabeler.layout import LabelBox, arrange_labels, _SpatialIndex


def crowded_labels():
    randomizer = random.Random(612)
    labels = [LabelBox(str(i), (randomizer.uniform(100, 700), randomizer.uniform(80, 520)),
                       randomizer.uniform(70, 160), 24, radius=randomizer.uniform(4, 25),
                       important=i < 8) for i in range(72)]
    labels[1].fixed = (50, 25)
    labels[5].force = True
    return labels


def test_crowded_layout_keeps_baseline_positions_and_omissions():
    expected = json.loads((Path(__file__).parent/'fixtures/label-layout-061.json').read_text(encoding="utf-8"))
    placed, omitted = arrange_labels(crowded_labels(), 800, 600, gap=8, max_labels=50)
    assert {key: list(rect) for key, rect in placed.items()} == expected['placed']
    assert sorted(omitted) == expected['omitted']


def test_spatial_queries_are_conservative_after_updates():
    # Different bucket sizes must never miss a genuinely nearby rectangle.
    from moonlabeler.layout import rect_intersects
    for size in (32, 96, 160):
        index = _SpatialIndex(size)
        rectangles = {str(i): (i*19-50, i*11-25, 80, 30) for i in range(12)}
        for key, rect in rectangles.items():
            index.put(key, rect)
        index.remove('2'); rectangles.pop('2')
        rectangles['5'] = (-40, -20, 100, 60)
        index.put('5', rectangles['5'])
        for query in ((0, 0, 120, 40), (-60, -50, 30, 50), (90, 40, 100, 90)):
            found = index.near(query, 12, exclude='3')
            for key, rect in rectangles.items():
                if key != '3' and rect_intersects(query, rect, padding=12):
                    assert rect in found
