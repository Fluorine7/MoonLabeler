# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional real-photo regression; third-party photographs stay local."""
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from moonlabeler.geometry import compute_geometry
from moonlabeler.registration import transform_points
from moonlabeler.sources import read_image, load_catalog
from moonlabeler.terrain_identification import identify_from_terrain

ROOT = Path(__file__).resolve().parents[1]
PHOTO = ROOT/'examples/auto-online-20261011/polar-original.jpg'


@pytest.mark.skipif(not PHOTO.exists() or not (ROOT/'.cache/terrain/LDEM_16.IMG').exists()
                    or not (ROOT/'.cache/ephemeris/de421.bsp').exists(),
                    reason='Local third-party south-polar photograph and cached data are not distributed')
def test_blind_south_polar_photo_retrieves_clavius_region():
    cache = ROOT/'.cache'
    geometry = compute_geometry(datetime.fromisoformat('2023-01-03T19:45:00+00:00'), cache/'ephemeris')
    image = read_image(PHOTO)
    result = identify_from_terrain(image, geometry, cache)
    feature = next(f for f in load_catalog(cache) if f['name']=='Clavius')
    projected, visible, _ = (result.projection_geometry or geometry).project([feature['lat']], [feature['lon']])
    assert visible[0]
    # Independently estimated center of the large crater with a curved chain
    # of floor craters, not an input to the automatic search.
    center = transform_points(result.matrix, projected)[0]
    assert np.linalg.norm(center-[1995.,2090.]) < 90
    assert result.image_inliers >= 24
    assert result.coverage >= .1
