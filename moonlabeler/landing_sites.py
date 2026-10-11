# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Offline annotation-only landing locations, separate from matching features."""
from functools import lru_cache
import json
from pathlib import Path

LANDING_KIND = 'Landing Site'
DEFAULT_LANDING_COLOR = '#79d9ef'


def is_landing_site(feature):
    return feature.get('kind') == LANDING_KIND


@lru_cache(maxsize=1)
def _sites():
    data = json.loads((Path(__file__).parent/'data/landing_sites.json').read_text(encoding='utf-8'))
    return tuple(dict(site, kind=LANDING_KIND, diameter=0., source=data['source']) for site in data['sites'])


def landing_sites():
    return [dict(site) for site in _sites()]


def landing_marker_radius(font_size):
    return max(3., font_size*.22)
