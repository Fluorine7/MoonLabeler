# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional geographic overlays, independent of recognition and label edits.

The grid follows the reference sphere. Height colours follow the registered
surface (including DEM ray intersection for terrain registrations). Raster
sampling is bounded; exporting cannot manufacture additional DEM detail.
"""
from dataclasses import dataclass, field
import base64
import io

import numpy as np
from PIL import Image

from ._opencv import cv2
from .annotation_style import svg_segments, svg_caption
from .geometry import surface_vectors
from .registration import transform_points
from .terrain import ElevationMap
from .terrain_view import TerrainView

GRID_SPACINGS = (0, 10, 15, 30)
ELEVATION_PALETTES = {
    "terrain": ("#20385b", "#337d9e", "#7aafad", "#cbc89a", "#d9a365", "#b86548", "#f3dfce"),
    "antique": ("#192b46", "#3c5265", "#787e7b", "#b1a784", "#d0b274", "#e3cb99", "#fff0c8"),
}
HEIGHT_STOPS = np.array([-9., -4., -1.5, 0., 2., 5., 9.])


@dataclass
class GridLine:
    segments: list
    label: str
    label_position: tuple
    major: bool
    show_label: bool = True


@dataclass
class ElevationRaster:
    heights: np.ndarray
    sunlit: np.ndarray
    source: str
    resolution_km: float
    photo_lit: np.ndarray | None = None

    @property
    def display_lit(self):
        return self.sunlit if self.photo_lit is None else self.photo_lit


@dataclass
class MapLayers:
    grid: list = field(default_factory=list)
    elevation: np.ndarray | None = None  # RGBA, already carries the chosen opacity


def photo_coordinates(project, pixels):
    """Undo the validated radial lens correction, then the affine registration."""
    points = np.asarray(pixels, float)
    distortion = project.identification.get("lens_distortion")
    if distortion and distortion["k"]:
        center, scale, k = np.asarray(distortion["center"]), distortion["scale"], distortion["k"]
        delta = (points-center)/scale
        radius = np.linalg.norm(delta, axis=1)
        # The validated pincushion model has k >= 0 and a unique positive root.
        original = np.minimum(radius, np.cbrt(radius/k))
        for _ in range(12):
            original -= (original+k*original**3-radius)/(1+3*k*original**2)
        points = center + delta*(original/np.maximum(radius, 1e-30))[:, None]*scale
    inverse = np.linalg.inv(np.vstack((project.matrix, [0., 0., 1.])))[:2]
    return transform_points(inverse, points)


def _clip_segment(a, b, width, height):
    """Liang–Barsky clipping also retains segments crossing a cropped photo."""
    delta = b-a
    low, high = 0., 1.
    for p, q in ((-delta[0], a[0]), (delta[0], width-a[0]),
                 (-delta[1], a[1]), (delta[1], height-a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
        elif p < 0:
            low = max(low, q/p)
        else:
            high = min(high, q/p)
        if low > high:
            return None
    return a+low*delta, a+high*delta


def _visible_segments(points, valid, width, height):
    segments, current = [], []
    for i in range(len(points)-1):
        clipped = _clip_segment(points[i], points[i+1], width, height) if valid[i] and valid[i+1] else None
        if clipped is None:
            if len(current) > 1:
                segments.append(current)
            current = []
            continue
        a, b = clipped
        if current and np.linalg.norm(a-current[-1]) > 1e-5:
            segments.append(current)
            current = []
        if not current:
            current.append(a.tolist())
        current.append(b.tolist())
    if len(current) > 1:
        segments.append(current)
    return segments


def photo_lighting(project, image, shape):
    """Observed terrain envelope, not a claim about the physical terminator.

    A supplied date can disagree with the photo. Keep photographed bright
    ground and enclosed crater shadows; leave connected dark surroundings out.
    The separate disk/DEM masks still determine where lunar data exists.
    """
    h, w = shape[:2]
    gray = np.asarray(Image.fromarray(image).convert("L").resize((w, h), Image.Resampling.BILINEAR))
    bright = max(16., float(np.percentile(gray[::4, ::4], 95)))
    threshold = max(4., bright*.08)
    if project.identification.get("lens_distortion"):
        threshold = max(threshold, 30., bright*.25)
    observed = (gray >= threshold).astype(np.uint8)*255
    radius = max(1, round(min(h, w)*.003))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1))
    closed = cv2.morphologyEx(observed, cv2.MORPH_CLOSE, kernel)
    # Fill dark floors enclosed by the bright terrain, but keep darkness that
    # connects to the frame. Padding makes the flood seed independent of crop.
    flooded = np.pad(closed, 1)
    cv2.floodFill(flooded, None, (0, 0), 255)
    return (closed > 0) | (observed > 0) | (flooded[1:-1, 1:-1] == 0)


def grid_lines(project, shape, *, image=None):
    if not project.grid_spacing or project.geometry is None or project.matrix is None:
        return []
    h, w = shape[:2]
    light_mask = None
    if project.map_lit_only and image is not None:
        factor = min(1., 1000/max(h, w))
        light_mask = photo_lighting(project, image, (max(1, round(h*factor)), max(1, round(w*factor))))
    spacing = project.grid_spacing
    # At most ~1 projected pixel per sample, with bounded work for close-ups.
    scale = np.linalg.norm(project.matrix[:, :2], ord=2)
    step = max(.05, min(.5, np.degrees(1/max(scale, 1))))
    latitudes = np.linspace(-90, 90, int(np.ceil(180/step))+1)
    longitudes = np.linspace(-180, 180, int(np.ceil(360/step))+1)
    curves = [("lon", value, latitudes, np.full_like(latitudes, value))
              for value in range(-180, 180, spacing)]
    curves += [("lat", value, np.full_like(longitudes, value), longitudes)
               for value in range(-90+spacing, 90, spacing)]
    result = []
    inset = min(h, w)*.012
    caption_boxes = []
    for axis, value, lat, lon in curves:
        xy, visible, lit = project.geometry.project(lat, lon)
        points = project.photo_points(xy)
        if light_mask is not None:
            rows, columns = light_mask.shape
            x = np.clip(points[:, 0]*columns/w, 0, columns-1).astype(int)
            y = np.clip(points[:, 1]*rows/h, 0, rows-1).astype(int)
            lit = light_mask[y, x]
        valid = visible & (lit if project.map_lit_only else True) & np.isfinite(points).all(axis=1)
        segments = _visible_segments(points, valid, w, h)
        if not segments:
            continue
        longest = max(segments, key=lambda s: np.linalg.norm(np.diff(s, axis=0), axis=1).sum())
        if np.linalg.norm(np.diff(longest, axis=0), axis=1).sum() < inset*8:
            continue
        suffix = ("E" if value > 0 else "W") if axis == "lon" else ("N" if value > 0 else "S")
        label = f"{abs(value)}°{suffix}" if value else ("0° lon" if axis == "lon" else "0° lat")
        size = max(6, round(min(h, w)*.009))
        position = (0., 0.)
        fractions = (.5, .4, .6, .3, .7) if axis == "lon" else (.2, .8, .3, .7)
        for fraction in fractions:
            point = longest[min(len(longest)-1, int(len(longest)*fraction))]
            x = float(np.clip(point[0]+inset*.3, inset, max(inset, w-inset*6)))
            y = float(np.clip(point[1]-inset*.3, inset*1.5, h-inset))
            box = (x-size*.2, y-size*1.2, size*(len(label)*.7+.4), size*1.6)
            if not any(box[0] < a+c and box[0]+box[2] > a and box[1] < b+d and box[1]+box[3] > b
                       for a, b, c, d in caption_boxes):
                caption_boxes.append(box)
                position = (x, y)
                break
        else:
            label = ""
        result.append(GridLine(segments, label, position, value == 0))
    return result


def sample_elevation(project, shape, dem, *, max_edge=1000, image=None):
    if project.geometry is None or project.matrix is None:
        raise ValueError("请先打开照片并配准。")
    h, w = shape[:2]
    factor = min(1., max_edge/max(h, w))
    rows, columns = max(1, round(h*factor)), max(1, round(w*factor))
    heights = np.full((rows, columns), np.nan, np.float32)
    sunlit = np.zeros((rows, columns), bool)
    view = TerrainView.from_geometry(project.geometry, dem) if project.projection_surface == "terrain" else project.geometry
    for first in range(0, rows, 32):
        last = min(rows, first+32)
        x, y = np.meshgrid((np.arange(columns)+.5)*w/columns, (np.arange(first, last)+.5)*h/rows)
        points = photo_coordinates(project, np.column_stack((x.ravel(), y.ravel())))
        lat, lon, disk = view.unproject(points)
        height = dem.sample(lat, lon)
        valid = disk & np.isfinite(height)
        heights[first:last] = np.where(valid, height, np.nan).reshape(last-first, columns)
        sunlit[first:last] = (valid & (surface_vectors(lat, lon) @ project.geometry.sun > 0)).reshape(last-first, columns)
    if not np.isfinite(heights).any():
        raise ValueError("高程数据没有覆盖当前照片中的月面。")
    observed = photo_lighting(project, image, (rows, columns)) if image is not None else None
    return ElevationRaster(heights, sunlit, dem.name, dem.resolution_km, observed)


def elevation_colors(heights, palette):
    colors = np.array([[int(color[i:i+2], 16) for i in (1, 3, 5)] for color in ELEVATION_PALETTES[palette]])
    values = np.nan_to_num(heights)
    return np.stack([np.interp(values, HEIGHT_STOPS, colors[:, c]) for c in range(3)], axis=-1).round().astype(np.uint8)


def elevation_alpha(raster, project):
    valid = np.isfinite(raster.heights) & (raster.display_lit if project.map_lit_only else True)
    return np.where(valid, round(255*project.elevation_opacity), 0).astype(np.uint8)


def colorize_elevation(raster, project, *, image=None):
    rgba = np.zeros((*raster.heights.shape, 4), np.uint8)
    rgba[:, :, :3] = elevation_colors(raster.heights, project.elevation_palette)
    if image is not None:
        # Colour follows height; luminance keeps the photograph's relief. Only
        # resample the bounded display raster, never the source photograph.
        h, w = raster.heights.shape
        photo = np.asarray(Image.fromarray(image).convert("RGB").resize((w, h), Image.Resampling.BILINEAR))
        luminance = photo.astype(np.float32) @ np.array([.2126, .7152, .0722], np.float32)
        lit = np.isfinite(raster.heights) & raster.display_lit
        reference = max(25.5, float(np.percentile(luminance[lit], 90))) if lit.any() else 255.
        shade = .18 + .82*np.clip(luminance/reference, 0, 1)
        rgba[:, :, :3] = (rgba[:, :, :3]*shade[:, :, None]).round().astype(np.uint8)
    rgba[:, :, 3] = elevation_alpha(raster, project)
    return rgba


def build_map_layers(project, shape, *, image=None):
    """Offline convenience API. The editor supplies its cached raster instead."""
    layers = MapLayers(grid_lines(project, shape, image=image))
    if project.elevation_enabled:
        if not project.terrain_path:
            raise ValueError("高程图需要 DEM：请导入或下载基础 LOLA 高程数据。")
        dem = ElevationMap.load(project.terrain_path)
        try:
            layers.elevation = colorize_elevation(sample_elevation(project, shape, dem, image=image), project, image=image)
        finally:
            dem.close()
    return layers


def grid_color(project):
    return "#c6a35e" if project.art_style == "manuscript" else "#9ec6d9"


def legend_rect(shape):
    h, w = shape[:2]
    unit = min(h, w)/100
    return (2*unit, h-8*unit, min(30*unit, w-4*unit), 6*unit)


def legend_image(shape, palette):
    """Only the colour ramp is raster; labels remain editable SVG text."""
    return elevation_colors(np.linspace(-9, 9, 256)[None, :], palette)


def png_data(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def layers_svg(project, shape, layers):
    h, w = shape[:2]
    parts = []
    if project.elevation_enabled:
        if layers.elevation is None:
            raise ValueError("高程图尚未生成；请先生成或关闭高程着色再导出。")
        parts.append(f'<image id="elevation-overlay" width="{w}" height="{h}" xlink:href="data:image/png;base64,{png_data(layers.elevation)}"/>')
    if layers.grid:
        color, size = grid_color(project), max(6, round(min(h, w)*.009))
        width = max(.7, min(h, w)*.00065)
        parts.append(f'<g id="selenographic-grid" opacity="{project.grid_opacity:.3f}" font-family="serif" font-size="{size:.3f}">')
        for index, line in enumerate(layers.grid):
            dash = "" if line.major else f' stroke-dasharray="{width*4:.3f} {width*5:.3f}"'
            parts.append(f'<path d="{svg_segments(line.segments)}" stroke="{color}" stroke-width="{width:.3f}"{dash} fill="none"/>')
            if line.label and line.show_label:
                x, y = line.label_position
                parts.append(svg_caption(line.label, x, y, size, color, "#10151d",
                                         max(1., size*.12), f'grid-text-{index}'))
        parts.append('</g>')
    return parts


def legend_svg(project, shape):
    x, y, w, h = legend_rect(shape)
    u = h/6
    ramp = png_data(legend_image(shape, project.elevation_palette))
    return [f'<g id="elevation-legend" font-family="serif" font-size="{max(1, round(u))}" fill="#f0ece1">',
            f'<rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" rx="{u*.4:.3f}" fill="#10151d" fill-opacity=".92"/>',
            f'<text x="{x+u:.3f}" y="{y+u*1.5:.3f}">LOLA · km (R = 1737.4 km)</text>',
            f'<image x="{x+u:.3f}" y="{y+u*2.2:.3f}" width="{w-2*u:.3f}" height="{u:.3f}" xlink:href="data:image/png;base64,{ramp}"/>',
            f'<text x="{x+u:.3f}" y="{y+u*4.8:.3f}">≤ −9</text>',
            f'<text x="{x+w/2:.3f}" y="{y+u*4.8:.3f}" text-anchor="middle">0</text>',
            f'<text x="{x+w-u:.3f}" y="{y+u*4.8:.3f}" text-anchor="end">≥ +9</text>', '</g>']
