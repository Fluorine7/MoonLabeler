# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""A confirmed point must not disable an independently verified polar pose."""
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from moonlabeler.geometry import compute_geometry
from moonlabeler.guided_identification import identify_from_reference_points
from moonlabeler.sources import read_image, load_catalog

ROOT = Path(__file__).resolve().parents[1]
PHOTO = ROOT/'examples/auto-online-20261011/polar-original.jpg'


@pytest.mark.skipif(not PHOTO.exists() or not (ROOT/'.cache/terrain/LDEM_16.IMG').exists()
                    or not (ROOT/'.cache/ephemeris/de421.bsp').exists(),
                    reason='Local third-party polar photo and caches are not distributed')
def test_confirmed_clavius_point_keeps_automatic_polar_registration_available():
    cache = ROOT/'.cache'
    geometry = compute_geometry(datetime.fromisoformat('2023-01-03T19:45:00+00:00'), cache/'ephemeris')
    image, catalog = read_image(PHOTO), load_catalog(cache)
    feature = next(f for f in catalog if f['name'] == 'Clavius')
    # A click consistent with the already independently validated blind pose.
    # It supplies a region constraint, not the rotation/scale/other map points.
    anchor = dict(id=feature['id'], pixel=[1993.3955, 2044.0191], enabled=True)
    result = identify_from_reference_points(image, geometry, cache, [anchor], catalog)
    assert result.image_inliers >= 24 and result.coverage >= .1
    assert result.reference_points['reference_ids'] == [feature['id']]
    assert np.max(result.reference_points['reference_errors_px']) < 20
    assert result.refinement and result.refinement.get('relief_aware')
