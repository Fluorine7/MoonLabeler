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
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image

from ._opencv import cv2
from .annotation_style import svg_segments, svg_caption
from .geometry import unit, surface_vectors
from .registration import transform_points
from .terrain import ElevationMap
from .terrain_view import TerrainView

GRID_SPACINGS = (0, 10, 15, 30)
CONTOUR_INTERVALS = (.25, .5, 1., 2.)  # km, relative to the same LOLA reference sphere
ELEVATION_PALETTES = {
    "terrain": ("#20385b", "#337d9e", "#7aafad", "#cbc89a", "#d9a365", "#b86548", "#f3dfce"),
    "antique": ("#142635", "#29475f", "#4e7892", "#c5b78a", "#d9b56e", "#e4c184", "#eddaad"),
    "wilderness": ("#302c19", "#494222", "#72642e", "#a28f46", "#c3ab68", "#d5c28b", "#e6d5a7"),
    "cyanotype": ("#071b37", "#0b3669", "#1f5f98", "#ece2bd", "#f1d6a0", "#f3dda9", "#fff3d3"),
    "copperplate": ("#062f39", "#0e4d55", "#236776", "#e8a064", "#cf7845", "#edac69", "#f7e4b9"),
    "inkwash": ("#18252a", "#2f494d", "#48676b", "#d5d2b8", "#c8a393", "#eee0c6", "#f5f0dc"),
    "redalert": ("#183c47", "#294e35", "#568432", "#c7ae62", "#a48b5c", "#bdb197", "#e6dcc5"),
}
HEIGHT_STOPS = np.array([-9., -4., -1.5, 0., 2., 5., 9.])


@dataclass(frozen=True)
class MapInks:
    contour: str
    index: str
    grid: str
    halo: str
    terminator: str


ART_MAP_INKS = {
    "cyanotype": MapInks("#a7d2dd", "#e3efdf", "#c0e2e7", "#102d48", "#e5c389"),
    "copperplate": MapInks("#8f704e", "#7d4e2c", "#875c3a", "#eedfbd", "#9a4d36"),
    "inkwash": MapInks("#536663", "#b94d37", "#ac4c38", "#ede7d5", "#a84335"),
    "redalert": MapInks("#536c36", "#d8c681", "#c8d5a0", "#17251b", "#e1a767"),
}


@dataclass(frozen=True)
class LegendStyle:
    family: str = "serif"
    background: str = "#10151d"
    foreground: str = "#f0ece1"
    border: str = ""
    sample: str = "#c5bb82"
    alpha: int = 235


LEGEND_STYLES = {
    "topographic": LegendStyle("sans-serif", "#372f1b", border="#968454", alpha=225),
    "cyanotype": LegendStyle("sans-serif", "#0b2943", "#e3f2ee", "#5b8ba1", "#c0e2e7"),
    "copperplate": LegendStyle("serif", "#ead9b6", "#412a21", "#9a7857", "#7d4e2c"),
    "inkwash": LegendStyle("serif", "#e8e5d3", "#303b3c", "#81877d", "#a84335"),
    "redalert": LegendStyle("sans-serif", "#1e2d23", "#f4eccb", "#89946a", "#d8c681"),
}
DEFAULT_LEGEND_STYLE = LegendStyle()


def legend_style(project):
    return LEGEND_STYLES.get(project.art_style, DEFAULT_LEGEND_STYLE)


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
    source: str
    resolution_km: float
    _contour_cache: dict = field(default_factory=dict, init=False, repr=False)
    _auto_interval: float | None = field(default=None, init=False, repr=False)


@dataclass
class MapLayers:
    grid: list = field(default_factory=list)
    elevation: np.ndarray | None = None  # RGBA, already carries the chosen opacity
    contours: list | None = None  # None means not generated; [] is valid flat terrain.
    terminator: list = field(default_factory=list)
    terminator_unreliable: bool = False
    contour_interval: float | None = None  # Resolved km; the project can remain on "auto".
    coverage: list | None = None  # Photo-space polygons; None covers all valid terrain.
    light_threshold: int | None = None


@dataclass
class PhotoLightness:
    values: np.ndarray
    automatic_threshold: int
    source_shape: tuple

    def coverage(self, threshold="auto"):
        """Keep broad bright regions and enclosed crater shadows, using cached lightness."""
        level = self.automatic_threshold if threshold == "auto" else threshold
        mask = np.uint8(self.values >= level)*255
        # Close narrow shadow gaps before retaining external contours. Enclosed
        # dark crater floors remain covered; the open dark hemisphere stays out.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        scale = np.array([self.source_shape[1]/mask.shape[1], self.source_shape[0]/mask.shape[0]])
        polygons = []
        for contour in contours:
            if cv2.contourArea(contour) < 3:
                continue
            points = cv2.approxPolyDP(contour, .35, True).reshape(-1, 2).astype(float)
            if len(points) >= 3:
                # Edge pixels represent the photograph boundary, not a one-pixel inset.
                for axis, size in enumerate((mask.shape[1], mask.shape[0])):
                    points[:, axis] = np.where(points[:, axis] == size-1, size, points[:, axis])
                polygons.append((points*scale).tolist())
        return polygons, int(level)


@dataclass
class ContourLine:
    height_km: float
    segments: list
    major: bool


def feathered_coverage(shape, coverage, *, max_edge=512):
    """Shared soft coverage for Qt and SVG, bounded independently of photo size."""
    h, w = shape[:2]
    scale = min(1., max_edge/max(h, w))
    width, height = max(1, round(w*scale)), max(1, round(h*scale))
    alpha = np.zeros((height, width), np.uint8)
    if coverage:
        factors = np.array([width/w, height/h])
        points = [np.round(np.asarray(polygon)*factors).astype(np.int32) for polygon in coverage]
        cv2.fillPoly(alpha, points, 255)
        # Feather at a stable fraction of the photograph, not the current zoom.
        # The broad day/night boundary fades; the far dark hemisphere stays clear.
        alpha = cv2.GaussianBlur(alpha, (0, 0), max(.8, min(width, height)*.008))
    rgba = np.full((height, width, 4), 255, np.uint8)
    rgba[:, :, 3] = alpha
    return rgba


def resolved_contour_interval(raster, project):
    """Choose readable isoline spacing at the photograph's overview scale.

    The DEM gradient estimates how closely contours would pack on the map.
    Aim for eight pixels between lines in the steeper fifth of valid terrain
    on a 1000-pixel-short-edge overview. This adapts to field of view and
    relief, independently of image resolution, window size and wheel zoom.
    Missing corners never contribute a fictitious cliff at the lunar limb.
    """
    if project.contour_interval != "auto":
        return project.contour_interval
    if raster._auto_interval is None:
        h = raster.heights
        a, b, c, d = h[:-1, :-1], h[:-1, 1:], h[1:, 1:], h[1:, :-1]
        gradient = np.hypot((b-a+c-d)*.5, (d-a+c-b)*.5)
        gradient = gradient[np.isfinite(gradient)]
        target = float(np.percentile(gradient, 80))*min(h.shape)/1000*8 if gradient.size else .5
        raster._auto_interval = next((interval for interval in CONTOUR_INTERVALS if interval >= target),
                                     CONTOUR_INTERVALS[-1])
    return raster._auto_interval


def _join_contour_edges(pairs, coordinates):
    """Stitch shared marching-square edges into continuous open/closed paths."""
    neighbours = {}
    for a, b in pairs:
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    paths = []
    starts = [key for key, values in neighbours.items() if len(values) == 1]
    starts.extend(neighbours)
    for start in starts:
        if not neighbours.get(start):
            continue
        keys, current = [start], start
        while neighbours[current]:
            following = neighbours[current].pop()
            neighbours[following].remove(current)
            keys.append(following)
            current = following
        points = np.array([coordinates[key] for key in keys])
        if len(points) > 2:
            # Drop collinear vertices, retaining the original interpolated path.
            delta = np.diff(points, axis=0)
            turn = abs(delta[:-1, 0]*delta[1:, 1]-delta[:-1, 1]*delta[1:, 0])
            points = points[np.r_[True, turn > 1e-8, True]]
        if len(points) > 1 and np.linalg.norm(np.diff(points, axis=0), axis=1).sum() > 1e-6:
            paths.append(points.tolist())
    return paths


def contour_lines(raster, project, shape):
    """Subpixel isolines from registered DEM heights, never from photo brightness.

    Four valid cell corners are required; missing data creates open endpoints,
    not fake contour rings around data boundaries.
    Every fifth contour is an index line. Pixel centres match sample_elevation.
    """
    interval = resolved_contour_interval(raster, project)
    key = (interval, tuple(shape[:2]), project.art_style)
    if key in raster._contour_cache:
        return raster._contour_cache[key]
    heights = raster.heights
    rows, columns = heights.shape
    if min(rows, columns) < 2:
        return []
    valid = np.isfinite(heights)
    cells = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, 1:] & valid[1:, :-1]
    if not cells.any():
        return []
    corners = (heights[:-1, :-1], heights[:-1, 1:], heights[1:, 1:], heights[1:, :-1])
    low, high = float(heights[valid].min()), float(heights[valid].max())
    first, last = int(np.ceil(low/interval)), int(np.floor(high/interval))
    # The supported lunar height range and minimum interval bound the work.
    if last-first > 160:
        raise ValueError("高程范围过大，无法生成等高线；请检查 DEM 单位是否为 km。")
    edge_corners = ((0, 1), (1, 2), (3, 2), (0, 3))
    cases = {1: ((3, 0),), 2: ((0, 1),), 3: ((3, 1),), 4: ((1, 2),),
             5: ((0, 1), (2, 3)), 6: ((0, 2),), 7: ((3, 2),),
             8: ((2, 3),), 9: ((0, 2),), 10: ((0, 3), (1, 2)),
             11: ((1, 2),), 12: ((1, 3),), 13: ((0, 1),), 14: ((0, 3),)}
    offsets = ((0, 0), (1, 0), (1, 1), (0, 1))
    scale = np.array([shape[1]/columns, shape[0]/rows])
    result = []
    for index in range(first, last+1):
        level = index*interval
        code = sum((corner >= level).astype(np.uint8)*(1 << i) for i, corner in enumerate(corners))
        y, x = np.nonzero(cells & (code != 0) & (code != 15))
        values = np.array([corner[y, x] for corner in corners]).T
        pairs, coordinates = [], {}
        for row, column, value, case in zip(y.tolist(), x.tolist(), values, code[y, x].tolist()):
            connections = cases[case]
            if case in (5, 10):
                # Asymptotic decider for bilinear saddle cells.
                shifted = value-level
                determinant = shifted[0]*shifted[2]-shifted[1]*shifted[3]
                connections = ((0, 1), (2, 3)) if determinant >= 0 else ((0, 3), (1, 2))
            ids = (row*(columns-1)+column,
                   rows*(columns-1)+row*columns+column+1,
                   (row+1)*(columns-1)+column,
                   rows*(columns-1)+row*columns+column)
            for a, b in connections:
                for edge in (a, b):
                    identity = ids[edge]
                    if identity not in coordinates:
                        c, d = edge_corners[edge]
                        fraction = (level-value[c])/(value[d]-value[c])
                        point = np.array(offsets[c])+fraction*(np.array(offsets[d])-offsets[c])
                        coordinates[identity] = (point+[column+.5, row+.5])*scale
                pairs.append((ids[a], ids[b]))
        segments = _join_contour_edges(pairs, coordinates)
        if project.art_style in ("topographic", "redalert"):
            # Generalize the map at its display scale without moving isolines.
            segments = [segment for segment in segments
                        if np.linalg.norm(np.diff(segment, axis=0), axis=1).sum() >= min(shape[:2])*.009]
        if segments:
            result.append(ContourLine(level, segments, index % 5 == 0))
    raster._contour_cache.clear()
    raster._contour_cache[key] = result
    return result


def contour_appearance(shape, major, style="standard"):
    width = max(1.8, min(shape[:2])*.0018) if major else max(1.1, min(shape[:2])*.0011)
    if style in ART_MAP_INKS:
        ink = ART_MAP_INKS[style]
        return ink.index if major else ink.contour, ink.halo, width
    if style == "manuscript":
        return "#efcf82", "#17242f", width
    if style == "topographic":
        return "#34250e", "#e7d39c", width
    return "#e4bd73", "#18232b", width


def line_strokes(color, halo, width):
    """A narrow contrasting edge keeps the same ink legible on light and dark ground."""
    return ((halo, width*1.8, .65), (color, width, 1.))


def grid_appearance(project, shape, major):
    width = max(1.8, min(shape[:2])*.0022) if major else max(1.25, min(shape[:2])*.0016)
    ink = ART_MAP_INKS.get(project.art_style)
    return grid_color(project), ink.halo if ink else "#15212a", width


def grid_dashes(width, major):
    # Physical photo-pixel lengths, shared by the foreground and its wider edge.
    return () if major else (width*7, width*4)


def terminator_appearance(project, shape):
    if project.art_style in ART_MAP_INKS:
        ink = ART_MAP_INKS[project.art_style]
        return ink.terminator, ink.halo, max(2.8, min(shape[:2])*.0028)
    color = "#91d8e5" if project.art_style == "topographic" else "#f3a46e"
    return color, "#14212b", max(2.8, min(shape[:2])*.0028)


def terminator_dashes(project, width):
    return (width*10, width*5) if project.terminator_source == "photo" else ()


def cartographic_colors(raster, project):
    """A generalized DEM basemap with restrained illustrative relief.

    Height terraces replace photographic contrast. The faint northwest relief
    is a drawing convention, independent of the photo and the ephemeris sun.
    Normalized filtering keeps missing DEM samples out of the calculation.
    """
    valid = np.isfinite(raster.heights)
    weights = cv2.GaussianBlur(valid.astype(np.float32), (0, 0), 1.1)
    smooth = cv2.GaussianBlur(np.where(valid, raster.heights, 0), (0, 0), 1.1)/np.maximum(weights, 1e-6)
    interval = resolved_contour_interval(raster, project)
    terraced = (np.floor(smooth/interval)+.5)*interval
    game_terrain = project.art_style == "redalert"
    rgb = elevation_colors(terraced, project.elevation_palette if game_terrain else "wilderness").astype(np.float32)
    if min(smooth.shape) > 1:
        dy, dx = np.gradient(smooth)
        slope = np.hypot(dx, dy)
        scale = max(.01, float(np.percentile(slope[valid], 90))) if valid.any() else .01
        if game_terrain:
            # Steep crater walls become rock faces, while flats retain the
            # green/sand height bands. This is a display convention, not a
            # claim about lunar vegetation or rock composition.
            cliff = np.clip((slope/scale-.55)/.65, 0, .88)[:, :, None]
            rgb = rgb*(1-cliff)+np.array([132., 115., 87.], np.float32)*cliff
            shade = np.clip(.97+(-dx-dy)*.14/scale, .68, 1.12)
        else:
            shade = np.clip(.97+(-dx-dy)*.045/scale, .87, 1.04)
        rgb *= shade[:, :, None]
    return rgb.round().clip(0, 255).astype(np.uint8)


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


def photo_lightness(project, image, *, max_edge=512):
    """Estimate a display threshold from the photo, independently of Sun/date/DEM.

    The registered disk only selects histogram samples, excluding black borders
    and watermarks. The coverage itself follows the photographed bright regions,
    so a slightly inaccurate reference limb cannot erase real bright terrain.
    """
    h, w = image.shape[:2]
    ratio = min(1., max_edge/max(h, w))
    width, height = max(1, round(w*ratio)), max(1, round(h*ratio))
    grey = np.asarray(Image.fromarray(image).convert("L").resize((width, height), Image.Resampling.BOX))
    smooth = cv2.GaussianBlur(grey, (0, 0), max(.8, min(width, height)*.006))
    if project.geometry is not None and project.matrix is not None:
        y, x = np.mgrid[:height, :width]
        pixels = np.column_stack(((x.ravel()+.5)*w/width, (y.ravel()+.5)*h/height))
        _, _, disk = project.geometry.unproject(photo_coordinates(project, pixels))
        samples = smooth.ravel()[disk]
    else:
        samples = smooth.ravel()
    if samples.size:
        high = float(np.percentile(samples, 95))
        otsu, _ = cv2.threshold(samples.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        # A conservative fraction of the foreground split retains dark maria and
        # thin bright rims. Manual control can suppress stronger earthshine.
        threshold = max(1, round(min(otsu*.35, high*.15)))
    else:
        threshold = 1
    return PhotoLightness(smooth, threshold, (h, w))


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


def grid_lines(project, shape):
    if not project.grid_spacing or project.geometry is None or project.matrix is None:
        return []
    h, w = shape[:2]
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
        xy, visible, _ = project.geometry.project(lat, lon)
        points = project.photo_points(xy)
        valid = visible & np.isfinite(points).all(axis=1)
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


def terminator_segments(project, shape, *, sun=None):
    """Zero solar altitude on the reference sphere, using the saved ephemeris Sun.

    This is a geometric guide, not a detected photo boundary or a terrain-shadow
    simulation. It needs neither a DEM nor photo brightness, and never masks
    other layers. The usual camera registration and lens correction still apply.
    """
    if not project.terminator_enabled or project.geometry is None or project.matrix is None:
        return []
    sun = unit(project.geometry.sun if sun is None else sun)
    axis = np.eye(3)[np.argmin(abs(sun))]
    u = unit(np.cross(sun, axis))
    v = np.cross(sun, u)
    scale = np.linalg.norm(project.matrix[:, :2], ord=2)
    step = max(.05, min(.5, np.degrees(1/max(scale, 1))))
    angle = np.linspace(0, 2*np.pi, int(np.ceil(360/step))+1)
    vectors = np.cos(angle)[:, None]*u+np.sin(angle)[:, None]*v
    lat = np.degrees(np.arcsin(np.clip(vectors[:, 2], -1, 1)))
    lon = np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0]))
    xy, visible, _ = project.geometry.project(lat, lon)
    points = project.photo_points(xy)
    return _visible_segments(points, visible & np.isfinite(points).all(axis=1), shape[1], shape[0])


def photo_terminator_segments(project, image):
    """Fit a broad day/night division without changing the saved ephemeris.

    Only substantial dark regions touching the photo or lunar boundary supply
    night evidence; isolated crater shadows do not. A weighted logistic plane
    in lunar surface vectors estimates a great-circle boundary. Requiring both
    broad regions and a dark fitted boundary rejects ambiguous crops, maria and
    fully lit frames. This is an approximate display guide, not a time estimate
    or a simulation of local terrain shadows.
    """
    photo = Image.fromarray(image).convert("L")
    photo.thumbnail((480, 480), Image.Resampling.BILINEAR)
    gray = cv2.GaussianBlur(np.asarray(photo, dtype=np.float32), (0, 0), 1.2)
    rows, columns = gray.shape
    if min(rows, columns) < 8:
        return []
    h, w = image.shape[:2]
    x, y = np.meshgrid((np.arange(columns)+.5)*w/columns, (np.arange(rows)+.5)*h/rows)
    lat, lon, disk = project.geometry.unproject(photo_coordinates(project, np.column_stack((x.ravel(), y.ravel()))))
    vectors = surface_vectors(lat, lon).reshape(rows, columns, 3)
    valid = disk.reshape(rows, columns) & (vectors @ project.geometry.observer > .12)
    if valid.sum() < 128:
        return []
    floor, bright = np.percentile(gray[valid], [2, 90])
    if bright-floor < 18 or floor > bright*.25:
        return []
    dark = valid & (gray < floor+(bright-floor)*.085)
    _, components = cv2.connectedComponents(dark.astype(np.uint8), connectivity=8)
    interior = cv2.erode(valid.astype(np.uint8), np.ones((3, 3), np.uint8),
                         borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(bool)
    labels = np.unique(components[valid & ~interior])
    sizes = np.bincount(components.ravel())
    labels = [label for label in labels if label and sizes[label] > valid.sum()*.025]
    night = valid & np.isin(components, labels)
    day = valid & (gray > floor+(bright-floor)*.3)
    if night.sum() < valid.sum()*.04 or day.sum() < valid.sum()*.08:
        return []
    indices = np.flatnonzero(day | night)
    indices = indices[::max(1, len(indices)//20000)]
    samples = vectors.reshape(-1, 3)[indices]
    target = day.ravel()[indices].astype(float)
    # Prefer daylight when dark crater floors and broad night evidence compete.
    weight = np.where(target, .8/max(1, target.sum()), .2/max(1, (1-target).sum()))
    eigenvalues, axes = np.linalg.eigh(samples.T @ (weight[:, None]*samples))
    transform = (axes/np.sqrt(np.maximum(eigenvalues, 1e-8))) @ axes.T
    features, beta = samples @ transform, np.zeros(3)
    try:
        for _ in range(20):
            probability = 1/(1+np.exp(-np.clip(features @ beta, -40, 40)))
            gradient = features.T @ (weight*(probability-target))+.0005*beta
            hessian = features.T @ ((weight*probability*(1-probability))[:, None]*features)+.0005*np.eye(3)
            change = np.linalg.solve(hessian, gradient)
            beta -= change
            if np.linalg.norm(change) < 1e-5:
                break
    except np.linalg.LinAlgError:
        return []
    normal = transform @ beta
    if not np.isfinite(normal).all() or np.linalg.norm(normal) < 1e-8:
        return []
    sun = unit(normal)
    incidence = vectors @ sun
    if np.mean(incidence[day] > 0) < .9 or np.mean(incidence[night] < 0) < .85:
        return []
    segments = terminator_segments(project, image.shape, sun=sun)
    values = []
    for segment in segments:
        points = np.array(segment)*[columns/w, rows/h]
        distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        along = np.linspace(0, distance[-1], max(2, int(distance[-1])))
        xy = np.column_stack([np.interp(along, distance, points[:, c]) for c in range(2)]).round().astype(int)
        values.extend(gray[xy[:, 1].clip(0, rows-1), xy[:, 0].clip(0, columns-1)])
    if not values or (np.median(values)-floor)/(bright-floor) > .25:
        return []
    return segments


def build_terminator(project, shape, *, image=None):
    if not project.terminator_enabled or project.geometry is None or project.matrix is None:
        return [], False
    if project.terminator_source == "ephemeris":
        return terminator_segments(project, shape), False
    segments = photo_terminator_segments(project, image) if image is not None else []
    return segments, not bool(segments)


def sample_elevation(project, shape, dem, *, max_edge=1000):
    if project.geometry is None or project.matrix is None:
        raise ValueError("请先打开照片并配准。")
    h, w = shape[:2]
    factor = min(1., max_edge/max(h, w))
    rows, columns = max(1, round(h*factor)), max(1, round(w*factor))
    heights = np.full((rows, columns), np.nan, np.float32)
    view = TerrainView.from_geometry(project.geometry, dem) if project.projection_surface == "terrain" else project.geometry
    for first in range(0, rows, 32):
        last = min(rows, first+32)
        x, y = np.meshgrid((np.arange(columns)+.5)*w/columns, (np.arange(first, last)+.5)*h/rows)
        points = photo_coordinates(project, np.column_stack((x.ravel(), y.ravel())))
        lat, lon, disk = view.unproject(points)
        height = dem.sample(lat, lon)
        valid = disk & np.isfinite(height)
        heights[first:last] = np.where(valid, height, np.nan).reshape(last-first, columns)
    if not np.isfinite(heights).any():
        raise ValueError("高程数据没有覆盖当前照片中的月面。")
    return ElevationRaster(heights, dem.name, dem.resolution_km)


def elevation_colors(heights, palette):
    colors = np.array([[int(color[i:i+2], 16) for i in (1, 3, 5)] for color in ELEVATION_PALETTES[palette]])
    values = np.nan_to_num(heights)
    return np.stack([np.interp(values, HEIGHT_STOPS, colors[:, c]) for c in range(3)], axis=-1).round().astype(np.uint8)


def elevation_alpha(raster, project):
    valid = np.isfinite(raster.heights)
    return np.where(valid, round(255*project.elevation_opacity), 0).astype(np.uint8)


def colorize_elevation(raster, project, *, image=None):
    rgba = np.zeros((*raster.heights.shape, 4), np.uint8)
    if ((project.art_style == "topographic" and project.elevation_palette == "wilderness") or
            (project.art_style == "redalert" and project.elevation_palette == "redalert")):
        rgba[:, :, :3] = cartographic_colors(raster, project)
        rgba[:, :, 3] = elevation_alpha(raster, project)
        return rgba
    rgba[:, :, :3] = elevation_colors(raster.heights, project.elevation_palette)
    if image is not None:
        # Colour follows height; luminance keeps the photograph's relief. Only
        # resample the bounded display raster, never the source photograph.
        h, w = raster.heights.shape
        photo = np.asarray(Image.fromarray(image).convert("RGB").resize((w, h), Image.Resampling.BILINEAR))
        luminance = photo.astype(np.float32) @ np.array([.2126, .7152, .0722], np.float32)
        lit = np.isfinite(raster.heights)
        reference = max(25.5, float(np.percentile(luminance[lit], 90))) if lit.any() else 255.
        floor = .55 if project.elevation_palette == "wilderness" else .18
        shade = floor + (1-floor)*np.clip(luminance/reference, 0, 1)
        rgba[:, :, :3] = (rgba[:, :, :3]*shade[:, :, None]).round().astype(np.uint8)
    rgba[:, :, 3] = elevation_alpha(raster, project)
    return rgba


def build_map_layers(project, shape, *, image=None):
    """Offline convenience API. The editor supplies its cached raster instead."""
    layers = MapLayers(grid_lines(project, shape))
    if project.map_light_mask and image is not None:
        layers.coverage, layers.light_threshold = photo_lightness(project, image).coverage(project.map_light_threshold)
    layers.terminator, layers.terminator_unreliable = build_terminator(project, shape, image=image)
    if project.elevation_enabled or project.contour_enabled:
        if not project.terrain_path:
            raise ValueError("高程图需要 DEM：请导入或下载基础 LOLA 高程数据。")
        dem = ElevationMap.load(project.terrain_path)
        try:
            raster = sample_elevation(project, shape, dem)
            if project.elevation_enabled:
                layers.elevation = colorize_elevation(raster, project, image=image)
            if project.contour_enabled:
                layers.contour_interval = resolved_contour_interval(raster, project)
                layers.contours = contour_lines(raster, project, shape)
        finally:
            dem.close()
    return layers


def grid_color(project):
    if project.art_style in ART_MAP_INKS:
        return ART_MAP_INKS[project.art_style].grid
    if project.art_style == "topographic":
        return "#edd99b"
    return "#f0cc7b" if project.art_style == "manuscript" else "#a7d9ed"


def legend_rect(shape, position=None):
    h, w = shape[:2]
    unit = min(h, w)/100
    width, height = min(30*unit, w-4*unit), 6*unit
    x, y = (2*unit, h-8*unit) if position is None else position
    return (min(max(0., x), w-width), min(max(0., y), h-height), width, height)


def legend_image(shape, palette):
    """Only the colour ramp is raster; labels remain editable SVG text."""
    return elevation_colors(np.linspace(-9, 9, 256)[None, :], palette)


def png_data(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _svg_line(path, color, halo, width, dashes=()):
    dash = ' stroke-dasharray="'+' '.join(f'{distance:.3f}' for distance in dashes)+'"' if dashes else ''
    return ''.join(f'<path d="{path}" stroke="{ink}" stroke-width="{thickness:.3f}" '
                   f'stroke-opacity="{alpha:.3f}" stroke-linejoin="round" stroke-linecap="round" fill="none"{dash}/>'
                   for ink, thickness, alpha in line_strokes(color, halo, width))


def layers_svg(project, shape, layers):
    h, w = shape[:2]
    parts = []
    if layers.coverage is not None:
        mask = png_data(feathered_coverage(shape, layers.coverage))
        parts.extend([f'<defs><mask id="photo-lit-coverage" maskUnits="userSpaceOnUse" x="0" y="0" width="{w}" height="{h}">'
                      f'<image width="{w}" height="{h}" preserveAspectRatio="none" xlink:href="data:image/png;base64,{mask}"/></mask></defs>',
                      f'<g id="photo-lit-map-layers" mask="url(#photo-lit-coverage)" data-threshold="{layers.light_threshold}">'])
    if project.elevation_enabled:
        if layers.elevation is None:
            raise ValueError("高程图尚未生成；请先生成或关闭高程着色再导出。")
        parts.append(f'<image id="elevation-overlay" width="{w}" height="{h}" xlink:href="data:image/png;base64,{png_data(layers.elevation)}"/>')
    if project.contour_enabled:
        if layers.contours is None:
            raise ValueError("等高线尚未生成；请先生成或关闭等高线再导出。")
        parts.append(f'<g id="elevation-contours" opacity="{project.contour_opacity:.3f}" fill="none" stroke-linejoin="round" stroke-linecap="round">')
        for line in layers.contours:
            color, halo, width = contour_appearance(shape, line.major, project.art_style)
            path = svg_segments(line.segments)
            parts.append(f'<g data-height-km="{line.height_km:g}" data-index="{str(line.major).lower()}">')
            parts.extend([_svg_line(path, color, halo, width), '</g>'])
        parts.append('</g>')
    if layers.grid:
        color, size = grid_color(project), max(6, round(min(h, w)*.009))
        parts.append(f'<g id="selenographic-grid" opacity="{project.grid_opacity:.3f}" font-family="serif" font-size="{size:.3f}">')
        for index, line in enumerate(layers.grid):
            ink, halo, width = grid_appearance(project, shape, line.major)
            parts.append(_svg_line(svg_segments(line.segments), ink, halo, width, grid_dashes(width, line.major)))
            if line.label and line.show_label:
                x, y = line.label_position
                parts.append(svg_caption(line.label, x, y, size, color, "#10151d",
                                         max(1., size*.12), f'grid-text-{index}'))
        parts.append('</g>')
    if layers.coverage is not None:
        parts.append('</g>')
    if project.terminator_enabled:
        if layers.terminator_unreliable:
            raise ValueError("照片内未找到可靠的晨昏交界；请选择工程时间的理论线，或关闭晨昏线再导出。")
        theoretical = project.terminator_source == "ephemeris"
        utc = (project.geometry.utc if project.geometry else project.utc) if theoretical else ""
        timestamp = escape(utc, {'"': '&quot;'})
        timestamp = f' data-utc="{timestamp}"' if theoretical else ""
        parts.append(f'<g id="lunar-terminator" opacity="{project.terminator_opacity:.3f}" '
                     f'data-model="reference-sphere" data-source="{project.terminator_source}"{timestamp} '
                     'stroke-linejoin="round" stroke-linecap="round">')
        title = f'Calculated lunar terminator · {utc} · reference sphere' if theoretical else 'Photo-estimated lunar terminator · approximate reference-sphere boundary'
        parts.append(f'<title>{escape(title)}</title>')
        if layers.terminator:
            style = terminator_appearance(project, shape)
            parts.append(_svg_line(svg_segments(layers.terminator), *style, terminator_dashes(project, style[2])))
        parts.append('</g>')
    return parts


def legend_svg(project, shape, *, contour_interval=None):
    x, y, w, h = legend_rect(shape, project.legend_position)
    u = h/6
    title = legend_title(project, contour_interval)
    interval = project.contour_interval if contour_interval is None else contour_interval
    style = legend_style(project)
    border = f' stroke="{style.border}" stroke-width="{max(.5, u*.045):.3f}"' if style.border else ''
    opacity = style.alpha/255 if project.art_style in ART_MAP_INKS else .92
    parts = [f'<g id="elevation-legend" font-family="{style.family}" font-size="{max(1, round(u))}" fill="{style.foreground}">',
            f'<rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" rx="{u*.4:.3f}" fill="{style.background}" fill-opacity="{opacity:.3f}"{border}/>',
            f'<text x="{x+u:.3f}" y="{y+u*1.5:.3f}">{title}</text>']
    if not project.elevation_enabled:
        index = f"Index: {interval*5:g} km · " if interval != "auto" else ""
        parts.extend([f'<path d="M {x+u:.3f},{y+u*2.7:.3f} H {x+w-u:.3f}" stroke="{style.sample}" fill="none" stroke-width="{max(1., u*.12):.3f}"/>',
                      f'<text x="{x+u:.3f}" y="{y+u*4.8:.3f}">{index}R = 1737.4 km</text>', '</g>'])
        return parts
    ramp = png_data(legend_image(shape, project.elevation_palette))
    parts.extend([
            f'<image x="{x+u:.3f}" y="{y+u*2.2:.3f}" width="{w-2*u:.3f}" height="{u:.3f}" xlink:href="data:image/png;base64,{ramp}"/>',
            f'<text x="{x+u:.3f}" y="{y+u*4.8:.3f}">≤ −9</text>',
            f'<text x="{x+w/2:.3f}" y="{y+u*4.8:.3f}" text-anchor="middle">0</text>',
            f'<text x="{x+w-u:.3f}" y="{y+u*4.8:.3f}" text-anchor="end">≥ +9</text>', '</g>'])
    return parts


def legend_title(project, contour_interval=None):
    if project.contour_enabled:
        interval = project.contour_interval if contour_interval is None else contour_interval
        return f"LOLA · km · Δh = {interval:g} km" if interval != "auto" else "LOLA · km"
    return "LOLA · km (R = 1737.4 km)"
