# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional real northern photographs; source images remain local.

The manifest records original sources and UTC capture dates. Landmark checks
are independent visual estimates, never supplied to the recognizer.
"""
from datetime import datetime
import json
from pathlib import Path

import numpy as np
import pytest

from moonlabeler.geometry import compute_geometry
from moonlabeler.registration import transform_points
from moonlabeler.sources import read_image
from moonlabeler.terrain_identification import identify_from_terrain

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'examples/auto-polar-more-059'


@pytest.mark.parametrize('key,landmarks', [
    ('north-endymion', {'Endymion': (467, 376, 35),
                        'Hercules': (251, 499, 35), 'Atlas': (342, 535, 35)}),
    ('north-gartner', {'Gärtner': (340, 260, 45)}),
])
def test_blind_northern_photo(key, landmarks):
    if not (DATA / 'manifest.json').exists() or not (ROOT / '.cache/terrain/LDEM_16.IMG').exists():
        pytest.skip('Local photographs and cached terrain required')
    item = next(row for row in json.loads((DATA / 'manifest.json').read_text(encoding="utf-8")) if row['key'] == key)
    image = read_image(DATA / item['file'])
    geometry = compute_geometry(datetime.fromisoformat(item['utc']), ROOT / '.cache/ephemeris')
    result = identify_from_terrain(image, geometry, ROOT / '.cache')
    catalog = json.loads((ROOT / 'moonlabeler/data/catalog.json').read_text(encoding="utf-8"))['features']
    projected_geometry = result.projection_geometry or geometry
    for name, (x, y, tolerance) in landmarks.items():
        feature = next(feature for feature in catalog if feature['name'] == name)
        points, _, _ = projected_geometry.project([feature['lat']], [feature['lon']])
        actual = transform_points(result.matrix, points)[0]
        assert np.linalg.norm(actual - [x, y]) < tolerance, (name, actual)
