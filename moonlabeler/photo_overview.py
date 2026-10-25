# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Offline lunar locator, shared by the canvas and editable SVG exports.

The footprint describes the registered photo frame on the reference sphere.
Its geometry is independent of label filters, artistic colouring and DEM masks.
"""
import base64
from dataclasses import dataclass
from functools import lru_cache
import io
from pathlib import Path
import sys
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image

from ._opencv import cv2
from .annotation_style import manuscript_fonts, svg_serif_family
from .geometry import Geometry, surface_vectors, unit
from .i18n import is_traditional, tr
from .map_layers import photo_coordinates, svg_segments


CARD_WIDTH, CARD_HEIGHT = 320., 366.


@dataclass(frozen=True)
class OverviewTheme:
    panel: str = '#10171f'
    border: str = '#3b4750'
    grid: str = '#bac6d3'
    ink: str = '#d7dfdd'
    muted: str = '#80928f'
    accent: str = '#efb85f'
    moon: tuple | None = None  # Shadow, midtone and highlight; no elevation data.
    serif: bool = False


OVERVIEW_THEMES = {
    'standard': OverviewTheme(),
    'manuscript': OverviewTheme(
        panel='#131f2b', border='#9e814c', grid='#d4bd83', ink='#f4e0a8',
        muted='#b7a57e', accent='#f2bd61',
        moon=('#0c1722', '#607580', '#ebd3a1'), serif=True),
    'topographic': OverviewTheme(
        panel='#20251b', border='#85805a', grid='#e1d29d', ink='#f3dfa0',
        muted='#b4b38d', accent='#8bd9d0',
        moon=('#101710', '#7a8053', '#ddc38e')),
    'cyanotype': OverviewTheme(
        panel='#0a223d', border='#4b8daf', grid='#bee5ed', ink='#e3f2ee',
        muted='#91bdcc', accent='#eed29c',
        moon=('#071629', '#346b95', '#d7eeea')),
    'copperplate': OverviewTheme(
        panel='#252521', border='#bc8969', grid='#d9c7a3', ink='#f2dfbf',
        muted='#bea98c', accent='#f1ac78',
        moon=('#101f20', '#53817c', '#e8c59c'), serif=True),
    'inkwash': OverviewTheme(
        panel='#202b2c', border='#81918b', grid='#c3d0c9', ink='#eee6d5',
        muted='#a6b3aa', accent='#e5866c',
        moon=('#142225', '#7e9292', '#eee5ce'), serif=True),
    'redalert': OverviewTheme(
        panel='#19291c', border='#87935d', grid='#d4d8a2', ink='#f4eccb',
        muted='#abb58a', accent='#f2bd68',
        moon=('#0c1a12', '#65804c', '#dbc18c')),
}


def _themed_image(model, theme):
    if theme.moon is None:
        return model.image
    # Tint the cached, already shaded albedo. Keep its alpha and geometry intact.
    stops = np.array([[int(color[i:i+2], 16) for i in (1, 3, 5)] for color in theme.moon])
    ramp = np.arange(256)
    lut = np.column_stack([np.interp(ramp, [0, 110, 255], stops[:, channel]) for channel in range(3)])
    image = model.image.copy()
    image[:, :, :3] = lut[model.image[:, :, 0]].round().astype(np.uint8)
    return image


def overview_rect(shape, position=None):
    short = min(shape[:2])
    width = short*.25
    height = width*CARD_HEIGHT/CARD_WIDTH
    x, y = (short*.02, short*.02) if position is None else position
    return (min(max(0., x), shape[1]-width), min(max(0., y), shape[0]-height), width, height)


def overview_key(project, shape):
    g = project.geometry
    return (tuple(shape[:2]), project.matrix.tobytes(),
            *(getattr(g, field).tobytes() for field in ('observer', 'right', 'north', 'sun')),
            g.distance_km, repr(project.identification.get('lens_distortion')))


@lru_cache(maxsize=1)
def _albedo():
    with Image.open(Path(__file__).parent/'data/moon_albedo_2k.jpg') as source:
        return np.array(source.convert('L').convert('RGB'))


def _overview_view(project, shape):
    # Aim at the photographed field so even small polar/limb crops are visible.
    # Using many interior rays also handles black margins and off-disk corners.
    h, w = shape[:2]
    x, y = np.meshgrid(np.linspace(.5, w-.5, 32), np.linspace(.5, h-.5, 32))
    lat, lon, valid = project.geometry.unproject(photo_coordinates(project, np.column_stack((x.ravel(), y.ravel()))))
    observer = unit(surface_vectors(lat[valid], lon[valid]).mean(axis=0)) if valid.any() else project.geometry.observer.copy()
    pole = np.array([0., 0., 1.])
    north = pole-observer[2]*observer
    if np.linalg.norm(north) < 1e-6:
        north = project.geometry.north-(project.geometry.north @ observer)*observer
    north = unit(north)
    return Geometry(observer, unit(np.cross(north, observer)), north,
                    project.geometry.sun.copy(), project.geometry.distance_km, project.geometry.utc)


def _segments(points, visible):
    indices = np.flatnonzero(visible)
    if not len(indices):
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) != 1)+1)
    return [points[group].tolist() for group in groups if len(group) > 1]


@dataclass
class Overview:
    size: int
    image: np.ndarray
    footprint: list
    grid: list
    center: tuple | None  # Geographic field centre; None when the frame misses the Moon.
    north: tuple | None
    earth: tuple | None


def build_overview(project, shape, *, size=384):
    view = _overview_view(project, shape)
    center, scale = (size-1)/2, size*.47
    y, x = np.mgrid[:size, :size]
    points = np.column_stack(((x.ravel()-center)/scale, (y.ravel()-center)/scale))
    lat, lon, disk = view.unproject(points)
    texture = _albedo()
    mx = np.nan_to_num((lon+180)/360*texture.shape[1]-.5).astype(np.float32).reshape(x.shape)
    my = np.nan_to_num((90-lat)/180*texture.shape[0]-.5).astype(np.float32).reshape(x.shape)
    color = cv2.remap(texture, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    vectors = surface_vectors(lat, lon)
    incidence = np.maximum(vectors @ view.sun, 0)
    emission = np.maximum(vectors @ view.observer, 0)
    light = .045+.955*np.sqrt(np.clip(2*incidence/(incidence+emission+1e-8), 0, 1))
    rgba = np.zeros((size, size, 4), np.uint8)
    rgba[:, :, :3] = np.nan_to_num(color*light.reshape(size, size, 1)).clip(0, 255).astype(np.uint8)
    rgba[:, :, 3] = disk.reshape(size, size)*255

    # Project the globe into the real photo, rather than assuming all four
    # photo corners are on the Moon or drawing a rectangle in globe space.
    xy, facing_photo, _ = project.geometry.project(lat, lon)
    pixels = project.photo_points(xy)
    in_frame = (disk & facing_photo & (pixels[:, 0] >= 0) & (pixels[:, 0] <= shape[1])
                & (pixels[:, 1] >= 0) & (pixels[:, 1] <= shape[0]))
    contours, _ = cv2.findContours(in_frame.reshape(size, size).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    footprint = [cv2.approxPolyDP(contour, 1., True)[:, 0, :].astype(float).tolist()
                 for contour in contours if cv2.contourArea(contour) > 1]

    grid = []
    for longitude in range(-180, 180, 30):
        latitude = np.linspace(-90, 90, 361)
        xy, visible, _ = view.project(latitude, np.full_like(latitude, longitude))
        grid.extend(_segments(center+scale*xy, visible))
    for latitude in range(-60, 90, 30):
        longitude = np.linspace(-180, 180, 721)
        xy, visible, _ = view.project(np.full_like(longitude, latitude), longitude)
        grid.extend(_segments(center+scale*xy, visible))

    def marker(vector):
        latitude = np.degrees(np.arcsin(np.clip(vector[2], -1, 1)))
        longitude = np.degrees(np.arctan2(vector[1], vector[0]))
        xy, visible, _ = view.project([latitude], [longitude])
        return tuple(center+scale*xy[0]) if visible[0] else None

    return Overview(size, rgba, footprint, grid, view.libration if footprint else None,
                    marker(np.array([0., 0., 1.])), marker(project.geometry.observer))


def overview_markup(model, art_style='standard'):
    theme = OVERVIEW_THEMES.get(art_style, OVERVIEW_THEMES['standard'])
    original = art_style == 'standard'
    family = svg_serif_family(manuscript_fonts(is_traditional(), sys.platform)) if theme.serif else 'sans-serif'
    family = escape(family, {'"': '&quot;'})
    buffer = io.BytesIO()
    Image.fromarray(_themed_image(model, theme)).save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    rim = model.size*.47
    center = (model.size-1)/2
    grid_path = svg_segments(model.grid)
    parts = [f'<rect class="overview-card" x="1" y="1" width="318" height="364" rx="12" fill="{theme.panel}" stroke="{theme.border}" stroke-width="1.2"/>']
    if theme.serif:
        parts.append(f'<rect x="6" y="6" width="308" height="354" rx="8" fill="none" stroke="{theme.border}" stroke-opacity=".45" stroke-width=".65"/>')
    elif art_style == 'cyanotype':
        parts.append(f'<path d="M 18,30 V 18 H 30 M 290,18 H 302 V 30" fill="none" stroke="{theme.grid}" stroke-width="1.2"/>')
    parts.extend([f'<g transform="translate(10 10) scale({300/model.size:.9f})">',
             f'<image width="{model.size}" height="{model.size}" xlink:href="data:image/png;base64,{encoded}"/>',
             f'<path d="{grid_path}" fill="none" stroke="#07121c" stroke-opacity=".65" stroke-width="4"/>',
             f'<path d="{grid_path}" fill="none" stroke="{theme.grid}" stroke-opacity=".80" stroke-width="2.1"/>',
             f'<circle cx="{center}" cy="{center}" r="{rim}" fill="none" stroke="{"#757e73" if original else theme.muted}" stroke-width="1.1"/>'])
    for polygon in model.footprint:
        path = svg_segments([polygon])+' Z'
        parts.extend([f'<path class="photo-footprint" d="{path}" fill="{"#e9ad50" if original else theme.accent}" fill-opacity=".10" stroke="{"#493b26" if original else theme.panel}" stroke-width="4.5" stroke-linejoin="round"/>',
                      f'<path d="{path}" fill="none" stroke="{theme.accent}" stroke-width="2.5" stroke-linejoin="round"/>'])
    earth_color = '#9eb6c5' if original else theme.accent
    for point, label, color in ((model.north, 'N', theme.ink), (model.earth, 'Earth', earth_color)):
        if point is None:
            continue
        x, y = point
        anchor = 'end' if x > model.size*.72 else 'start'
        text_x = x-7 if anchor == 'end' else x+7
        parts.extend([f'<circle cx="{x:.3f}" cy="{y:.3f}" r="2.3" fill="{color}"/>',
                      f'<text x="{text_x:.3f}" y="{y+4:.3f}" text-anchor="{anchor}" fill="{color}" font-family="{family}" font-size="12" stroke="{theme.panel}" stroke-width=".3">{label}</text>'])
    parts.append('</g>')
    if model.north is None:
        parts.append(f'<text x="168" y="14" fill="{"#b8c5bf" if original else theme.ink}" font-family="{family}" font-size="9">N</text>')
    if model.center is None:
        lat_text = lon_text = '—'
    else:
        latitude, longitude = (round(value, 2) for value in model.center)
        lat_text = f'{abs(latitude):.2f}° {"N" if latitude >= 0 else "S"}'
        lon_text = f'{abs(longitude):.2f}° {"E" if longitude >= 0 else "W"}'
    swatch = (f'<rect x="22" y="322" width="9" height="9" fill="{theme.accent}"/>' if art_style == 'inkwash' else
              f'<path d="M 20,326 H 34" stroke="{theme.accent}" stroke-width="1.7"/>')
    parts.extend([f'<path d="M 14,312 H 306" stroke="{theme.border}" stroke-width=".7"/>',
                  f'<g fill="{theme.ink}" font-family="{family}">', swatch,
                  f'<text x="42" y="330" font-size="11">{escape(tr("取景范围"))}</text>',
                  f'<text x="20" y="351" font-size="8" fill="{theme.muted}">LAT</text>',
                  f'<text x="47" y="352" font-size="12">{lat_text}</text>',
                  f'<text x="172" y="351" font-size="8" fill="{theme.muted}">LON</text>',
                  f'<text x="203" y="352" font-size="12">{lon_text}</text>', '</g>'])
    return ''.join(parts)


def overview_document(model, art_style='standard'):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{CARD_WIDTH:g}" height="{CARD_HEIGHT:g}" viewBox="0 0 {CARD_WIDTH:g} {CARD_HEIGHT:g}">'
            +overview_markup(model, art_style)+'</svg>')


def overview_svg(project, shape, model=None):
    if not project.overview_enabled or project.geometry is None or project.matrix is None:
        return ''
    model = build_overview(project, shape) if model is None else model
    x, y, width, _ = overview_rect(shape, project.overview_position)
    return (f'<g id="photo-overview" transform="translate({x:.6f} {y:.6f}) scale({width/CARD_WIDTH:.9f})">'
            +overview_markup(model, project.art_style)+'</g>')
