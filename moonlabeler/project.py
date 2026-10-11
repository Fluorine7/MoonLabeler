# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from dataclasses import dataclass, field
from pathlib import Path
import base64
import io
import json
import os
import heapq
import math
import re
from xml.sax.saxutils import escape

import cv2
import numpy as np
from PIL import Image, ImageColor

from .geometry import Geometry, MOON_RADIUS_KM, surface_vectors
from .sources import read_image, write_json, COMMON_FEATURES
from .registration import transform_points

DEFAULT_FONT_PERCENT = 1.8
DEFAULT_FONT_STEP_PERCENT = .3
# Equivalent projected diameter as a fraction of the photograph's short side.
# Fixed boundaries keep a formation's tier independent of catalogue filters.
FONT_TIER_BOUNDARIES = (.008, .02)
MIN_OUTLINE_DIAMETER_KM = 35.


def font_tier_percentages(maximum, step):
    """Subtract percentage points, rather than compounding a relative ratio."""
    return tuple(max(.05, maximum-level*step) for level in range(3))


def _invalid_field(field):
    raise ValueError(f"工程字段无效：{field}。")


def _number(value, field, minimum=None, maximum=None, *, integer=False):
    # JSON booleans and numeric-looking strings must not reach Qt spin boxes.
    okay = type(value) in (int, float) and (not integer or type(value) is int)
    try:
        okay = okay and math.isfinite(value)
    except (TypeError, OverflowError):
        okay = False
    if not okay or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        _invalid_field(field)


def _mapping(value, field):
    if not isinstance(value, dict):
        _invalid_field(field)
    return value


def _point(value, field, size=2):
    if not isinstance(value, list) or len(value) != size:
        _invalid_field(field)
    for coordinate in value:
        _number(coordinate, field)


def _validate_project_data(data):
    """Validate before replacing an editor's current document.

    Unknown catalogue IDs and extension keys remain usable when opening older
    projects. Validate fields consumed by the UI rather than requiring today's
    complete schema or silently clipping malformed values in its controls.
    """
    _mapping(data, '根节点')
    for key in ('image_path', 'utc', 'anchors', 'labels', 'geometry', 'matrix', 'style'):
        if key not in data:
            _invalid_field(key)
    for key in ('image_path', 'utc'):
        if not isinstance(data[key], str):
            _invalid_field(key)
    if data['utc']:
        from datetime import datetime
        try:
            if datetime.fromisoformat(data['utc']).tzinfo is None:
                _invalid_field('utc')
        except ValueError as exc:
            raise ValueError('工程字段无效：utc。') from exc
    if not isinstance(data['anchors'], list):
        _invalid_field('anchors')
    for anchor in data['anchors']:
        _mapping(anchor, 'anchors')
        if not isinstance(anchor.get('id'), str):
            _invalid_field('anchors.id')
        _point(anchor.get('pixel'), 'anchors.pixel')
        if 'enabled' in anchor and type(anchor['enabled']) is not bool:
            _invalid_field('anchors.enabled')
    for label in _mapping(data['labels'], 'labels').values():
        _mapping(label, 'labels')
        if 'position' in label:
            _point(label['position'], 'labels.position')
        if label.get('text') is not None and not isinstance(label['text'], str):
            _invalid_field('labels.text')
        for key in ('hidden', 'force'):
            if key in label and type(label[key]) is not bool:
                _invalid_field(f'labels.{key}')
    if data['matrix'] is not None:
        if not isinstance(data['matrix'], list) or len(data['matrix']) != 2:
            _invalid_field('matrix')
        for row in data['matrix']:
            _point(row, 'matrix', 3)
    style = _mapping(data['style'], 'style')
    for key, bounds, integer in (('font_size', (1, 2147483647), True),
                                 ('max_labels', (1, 1000), True),
                                 ('min_diameter', (0, 3000), False)):
        if key in style:
            _number(style[key], f'style.{key}', *bounds, integer=integer)
    # Legacy pixel fonts can migrate above today's 8% UI limit; retain them.
    if style.get('font_percent') is not None:
        _number(style['font_percent'], 'style.font_percent', .000001, 100)
    if 'font_step_percent' in style:
        _number(style['font_step_percent'], 'style.font_step_percent', 0, 100)
    for key in ('illuminated_only', 'optimize_layout', 'crater_outlines'):
        if key in style and type(style[key]) is not bool:
            _invalid_field(f'style.{key}')
    for key in ('kind', 'language', 'color', 'crater_outline_shape'):
        if key in style and not isinstance(style[key], str):
            _invalid_field(f'style.{key}')
    if 'language' in style and style['language'] not in ('双语', '英文', '中文'):
        _invalid_field('style.language')
    if 'color' in style:
        try:
            ImageColor.getrgb(style['color'])
        except ValueError as exc:
            raise ValueError('工程字段无效：style.color。') from exc
    observer = _mapping(data.get('observer', {}), 'observer')
    for key, extent in (('latitude', 90), ('longitude', 180)):
        if observer.get(key) is not None:
            _number(observer[key], f'observer.{key}', -extent, extent)
    terrain = _mapping(data.get('terrain', {}), 'terrain')
    if not isinstance(terrain.get('dem_path', ''), str):
        _invalid_field('terrain.dem_path')
    settings = _mapping(terrain.get('settings', {}), 'terrain.settings')
    for key, bounds in (('width_km', (10, 2000)), ('gamma', (.3, 4))):
        if key in settings:
            _number(settings[key], f'terrain.settings.{key}', *bounds)
    if settings.get('center_id') is not None and not isinstance(settings['center_id'], str):
        _invalid_field('terrain.settings.center_id')
    if 'model' in settings and not isinstance(settings['model'], str):
        _invalid_field('terrain.settings.model')
    if 'shadows' in settings and type(settings['shadows']) is not bool:
        _invalid_field('terrain.settings.shadows')
    craters = _mapping(data.get('crater_detection', {}), 'crater_detection')
    for key, bounds in (('min_radius', (3, 4000)), ('max_radius', (3, 4000)),
                        ('sensitivity', (0, 100)), ('max_candidates', (1, 500))):
        if key in craters:
            _number(craters[key], f'crater_detection.{key}', *bounds, integer=True)
    if 'viewport' in craters and type(craters['viewport']) is not bool:
        _invalid_field('crater_detection.viewport')
    recognition = _mapping(data.get('automatic_recognition', {}), 'automatic_recognition')
    if 'matched_names' in recognition and (not isinstance(recognition['matched_names'], list) or
                                         not all(isinstance(name, str) for name in recognition['matched_names'])):
        _invalid_field('automatic_recognition.matched_names')
    for rim in _mapping(data.get('terrain_rims', {}), 'terrain_rims').values():
        _mapping(rim, 'terrain_rims')
        coordinates = rim.get('coordinates')
        if not isinstance(coordinates, list) or len(coordinates) < 16:
            _invalid_field('terrain_rims.coordinates')
        for point in coordinates:
            _point(point, 'terrain_rims.coordinates', 3)
    if data['geometry'] is not None:
        geometry = _mapping(data['geometry'], 'geometry')
        for key in ('observer', 'right', 'north', 'sun'):
            _point(geometry.get(key), f'geometry.{key}', 3)
        _number(geometry.get('distance_km'), 'geometry.distance_km', MOON_RADIUS_KM+1)
        if not isinstance(geometry.get('utc'), str):
            _invalid_field('geometry.utc')


def _ellipse_outline(pixels):
    """Smooth a projected rim while retaining its vertex order for occultation."""
    if len(pixels) < 6 or not np.isfinite(pixels).all():
        return pixels
    closed = np.allclose(pixels[0], pixels[-1])
    samples = pixels[:-1] if closed else pixels
    origin = samples.mean(axis=0)
    try:
        center, axes, degrees = cv2.fitEllipse((samples-origin).astype(np.float32))
    except cv2.error:
        return pixels
    radii = np.asarray(axes, float)/2
    if not np.isfinite(radii).all() or min(radii) <= 1e-6:
        return pixels
    center = origin+np.asarray(center)
    angle = np.radians(degrees)
    rotation = np.array([[np.cos(angle), -np.sin(angle)],
                         [np.sin(angle), np.cos(angle)]])
    local = (pixels-center) @ rotation
    phase = np.arctan2(local[:, 1]/radii[1], local[:, 0]/radii[0])
    # Keep each source vertex's angular position so its visibility flag still
    # clips the same limb arc; uniformly resampling would lose that association.
    ellipse = center+(np.column_stack((np.cos(phase), np.sin(phase)))*radii) @ rotation.T
    if closed:
        ellipse[-1] = ellipse[0]
    return ellipse


@dataclass
class Project:
    image_path: str = ""
    utc: str = ""
    geometry: Geometry | None = None
    matrix: np.ndarray | None = None
    anchors: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)
    font_size: int = 24
    font_percent: float | None = DEFAULT_FONT_PERCENT
    font_step_percent: float = DEFAULT_FONT_STEP_PERCENT
    color: str = "#f5f5f2"
    language: str = "双语"
    min_diameter: float = 40.
    kind: str = "全部"
    illuminated_only: bool = True
    max_labels: int = 200
    latitude: float | None = None
    longitude: float | None = None
    terrain_path: str = ""
    terrain_settings: dict = field(default_factory=dict)
    optimize_layout: bool = True
    crater_settings: dict = field(default_factory=dict)
    identification: dict = field(default_factory=dict)
    crater_outlines: bool = True
    crater_outline_shape: str = "ellipse"
    terrain_rims: dict = field(default_factory=dict)

    def update_font_size(self, shape):
        short_side = min(shape[:2])
        if self.font_percent is None:
            # Migrate old pixel-size projects without changing their appearance.
            self.font_percent = self.font_size*100/short_side
            self.font_step_percent = 0.
        self.font_size = max(6, round(short_side*self.font_percent/100))

    def font_sizes(self, shape):
        if self.font_percent is None:
            return (self.font_size,)*3
        return tuple(max(6, round(min(shape[:2])*percent/100))
                     for percent in font_tier_percentages(self.font_percent, self.font_step_percent))

    def label_font_sizes(self, features, shape):
        """Assign three sizes using the projected equivalent-area diameter.

        The local sphere-to-photo Jacobian includes limb foreshortening,
        finite observing distance, and the fitted camera's affine transform.
        Evaluate all centers together; no rim fitting or image analysis is
        needed when changing typography. Long formations use catalogue extent.
        """
        sizes = self.font_sizes(shape)
        result = {feature['id']: self.font_size for feature in features}
        if self.font_step_percent == 0 or self.geometry is None or self.matrix is None:
            return result
        usable = [f for f in features if all(key in f for key in ('lat', 'lon', 'diameter'))]
        if not usable:
            return result
        centers = surface_vectors([f['lat'] for f in usable], [f['lon'] for f in usable])
        longitude = np.radians([f['lon'] for f in usable])
        east = np.column_stack((-np.sin(longitude), np.cos(longitude), np.zeros(len(usable))))
        tangents = np.stack((east, np.cross(centers, east)), axis=2)
        camera = np.stack((self.geometry.right, -self.geometry.north))
        distance_ratio = MOON_RADIUS_KM/self.geometry.distance_km
        perspective = 1-distance_ratio*(centers @ self.geometry.observer)
        differential = (camera[None, :, :]/perspective[:, None, None] +
                        (centers @ camera.T)[:, :, None]*distance_ratio*
                        self.geometry.observer[None, None, :]/perspective[:, None, None]**2)
        local = self.matrix[None, :, :2] @ differential @ tangents
        diameter = np.array([f['diameter'] for f in usable])/MOON_RADIUS_KM
        apparent = diameter*np.sqrt(np.abs(np.linalg.det(local)))/min(shape[:2])
        levels = np.where(apparent >= FONT_TIER_BOUNDARIES[1], 0,
                          np.where(apparent >= FONT_TIER_BOUNDARIES[0], 1, 2))
        result.update((f['id'], sizes[level]) for f, level in zip(usable, levels))
        return result

    def save(self, path):
        path = Path(path)
        image = Path(self.image_path).resolve()
        data = {"format": "MoonLabeler", "version": 2,
                "image_path": os.path.relpath(image, path.parent.resolve()),
                "utc": self.utc, "geometry": self.geometry.to_dict() if self.geometry else None,
                "matrix": self.matrix.tolist() if self.matrix is not None else None,
                "anchors": self.anchors, "labels": self.labels,
                "crater_detection": self.crater_settings,
                "automatic_recognition": self.identification,
                "terrain_rims": self.terrain_rims,
                "observer": {"latitude": self.latitude, "longitude": self.longitude},
                "terrain": {"dem_path": os.path.relpath(Path(self.terrain_path).resolve(), path.parent.resolve()) if self.terrain_path else "",
                            "settings": self.terrain_settings},
                "style": {k: getattr(self, k) for k in ("font_size", "font_percent", "font_step_percent", "color", "language", "min_diameter", "kind", "illuminated_only", "max_labels", "optimize_layout", "crater_outlines", "crater_outline_shape")}}
        write_json(path, data)

    @classmethod
    def load(cls, path):
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") != "MoonLabeler" or data.get("version") != 2:
            raise ValueError("这不是受支持的 MoonLabeler 工程。")
        _validate_project_data(data)
        project = cls(image_path=str((path.parent / data["image_path"]).resolve()),
                      utc=data["utc"], anchors=data["anchors"], labels=data["labels"])
        project.latitude = data.get("observer", {}).get("latitude")
        project.longitude = data.get("observer", {}).get("longitude")
        terrain = data.get("terrain", {})
        project.terrain_path = str((path.parent/terrain["dem_path"]).resolve()) if terrain.get("dem_path") else ""
        project.terrain_settings = terrain.get("settings", {})
        project.crater_settings = data.get("crater_detection", {})
        project.identification = data.get("automatic_recognition", {})
        project.terrain_rims = data.get("terrain_rims", {})
        if data["geometry"]:
            project.geometry = Geometry.from_dict(data["geometry"])
        if data["matrix"] is not None:
            matrix = np.asarray(data["matrix"], float)
            determinant = np.linalg.det(matrix[:, :2]) if matrix.shape == (2, 3) else float('nan')
            if matrix.shape != (2, 3) or not np.isfinite(matrix).all() or not np.isfinite(determinant) or abs(determinant) < 1e-10:
                raise ValueError("工程配准矩阵无效。")
            project.matrix = matrix
        project.font_percent = None  # Older projects only store a pixel size.
        project.font_step_percent = 0.  # Pre-tier projects retain uniform text.
        for key, value in data["style"].items():
            if key in ("font_size", "font_percent", "font_step_percent", "color", "language", "min_diameter", "kind", "illuminated_only", "max_labels", "optimize_layout", "crater_outlines", "crater_outline_shape"):
                setattr(project, key, value)
        if project.crater_outline_shape not in ("ellipse", "terrain"):
            project.crater_outline_shape = "ellipse"
        return project

    def label_text(self, feature):
        override = self.labels.get(feature["id"], {}).get("text")
        if override is not None:
            return override
        name, zh = feature["name"], feature.get("name_zh", "")
        if self.language == "中文":
            return zh or name
        if self.language == "双语" and zh:
            return f"{zh} · {name}"
        return name

    def visible_features(self, catalog, shape, image=None, *, all_candidates=False):
        """Rank visible catalogue entries; the scene requests reserves as well.

        This estimates photographic prominence, not crater identification.
        The display budget is enforced after placement, independently of this
        convenience method's default candidate limit.
        """
        if self.geometry is None or self.matrix is None:
            return []
        points, visible, lit = self.geometry.project([f["lat"] for f in catalog], [f["lon"] for f in catalog])
        pixels = transform_points(self.matrix, points)
        h, w = shape[:2]
        # Use observed brightness when a photo is available. A crater center
        # can be in shadow even though its rim is clearly visible; incorrect
        # solar geometry must not suppress the visible named formation.
        stride = max(1, int(np.ceil(max(h, w)/1600)))
        sampled = image[::stride, ::stride] if image is not None else None
        gray = sampled.mean(axis=2) if sampled is not None and sampled.ndim == 3 else sampled
        # Separate small-scale background texture from an isolated rim. Raw
        # brightness range alone favors rugged highlands and the black sky at
        # the lunar limb over distinct craters on smoother mare surfaces.
        noise = abs(gray-cv2.GaussianBlur(gray.astype(float), (0, 0), 1.2)) if gray is not None else None
        scale = np.sqrt(abs(np.linalg.det(self.matrix[:, :2])))
        reference_font = self.font_sizes(shape)[1]
        bright = max(16., float(np.percentile(gray[::8, ::8], 95))) if gray is not None else None
        brightness_limit = max(4., bright*.08) if gray is not None else None
        offsets = np.linspace(-1, 1, 13)
        dx, dy = np.meshgrid(offsets, offsets)
        disk = dx*dx+dy*dy <= 1
        dx, dy = dx[disk], dy[disk]
        inside = (pixels[:,0] >= 0) & (pixels[:,0] < w) & (pixels[:,1] >= 0) & (pixels[:,1] < h)
        candidates = []
        depths = surface_vectors([f['lat'] for f in catalog], [f['lon'] for f in catalog]) @ self.geometry.observer
        for f, xy, okay, sunlight, depth in zip(catalog, pixels, visible & inside, lit, depths):
            if not okay:
                continue
            if f["diameter"] < self.min_diameter or (self.kind != "全部" and f["kind"] != self.kind):
                continue
            contrast, roughness = 0., 0.
            if gray is not None:
                radius = max(4., min(min(h, w)*.08, f["diameter"]*scale/(2*MOON_RADIUS_KM)*1.12))
                sx = np.clip(np.rint((xy[0]+radius*dx)/stride).astype(int), 0, gray.shape[1]-1)
                sy = np.clip(np.rint((xy[1]+radius*dy)/stride).astype(int), 0, gray.shape[0]-1)
                low, light, high = np.percentile(gray[sy, sx], (10, 80, 90))
                contrast = min(1., (high-low)/bright)
            if self.illuminated_only:
                if gray is None:
                    if not sunlight:
                        continue
                else:
                    if light < brightness_limit:
                        # A large crater can have a completely dark floor.
                        # Sample its foreshortened rim, even outside the small
                        # center neighborhood; this is independent of drawing
                        # outlines and never samples clipped off-frame points.
                        if f["kind"] not in ("Crater, craters", "Satellite Feature"):
                            continue
                        rim, rim_visible = self._project_crater_rim(f, (.85, 1., 1.15))
                        on_photo = rim_visible & (rim[:, 0] >= 0) & (rim[:, 0] < w) & (rim[:, 1] >= 0) & (rim[:, 1] < h)
                        if on_photo.sum() < 12:
                            continue
                        locations = np.rint(rim[on_photo]/stride).astype(int)
                        rx = np.clip(locations[:, 0], 0, gray.shape[1]-1)
                        ry = np.clip(locations[:, 1], 0, gray.shape[0]-1)
                        if np.percentile(gray[ry, rx], 80) < brightness_limit:
                            continue
            if gray is not None:
                if f['kind'] in ('Crater, craters', 'Satellite Feature'):
                    rim, rim_visible = self._project_crater_rim(f, (.4, .7, 1., 1.3, 1.6, 2.))
                    on_photo = rim_visible & (rim[:, 0] >= 0) & (rim[:, 0] < w) & (rim[:, 1] >= 0) & (rim[:, 1] < h)
                    inside_rim = on_photo.copy()
                    inside_rim[len(rim)//2:] = False
                    background = on_photo & ~inside_rim
                    locations = np.rint(rim/stride).astype(int)
                    rx = np.clip(locations[:, 0], 0, gray.shape[1]-1)
                    ry = np.clip(locations[:, 1], 0, gray.shape[0]-1)
                    if inside_rim.sum() >= 12:
                        low, high = np.percentile(gray[ry[inside_rim], rx[inside_rim]], (10, 90))
                        contrast = min(1., (high-low)/bright)
                    if background.sum() >= 12:
                        roughness = float(np.percentile(noise[ry[background], rx[background]], 80)/bright)
                else:
                    roughness = float(np.percentile(noise[sy, sx], 80)/bright)
            data = self.labels.get(f['id'], {})
            satellite = f['kind'] == 'Satellite Feature' or bool(re.search(r'\s[A-Z]$', f['name']))
            tier = (0 if data.get('force') or 'position' in data else
                    1 if f['name'] in COMMON_FEATURES else 3 if satellite else 2)
            # Apparent size saturates: a huge flooded floor should not always
            # outrank a smaller, high-contrast rim. Foreshortened limb features
            # receive less size credit. Long rilles/cliffs share the same cap.
            apparent = f['diameter']*scale/MOON_RADIUS_KM*np.sqrt(max(0., depth))
            score = 2.5*contrast/(1+12*roughness) + min(1., np.sqrt(apparent/max(6, reference_font)))
            score += .4*np.sqrt(max(0., depth))
            score += .4 if f['kind'] == 'Crater, craters' else 0.
            cell = (min(3, int(xy[0]*4/w)), min(3, int(xy[1]*4/h)))
            candidates.append((tier, float(score), cell, f, xy))
        # A soft per-region penalty balances coverage without giving a tiny
        # populated corner the same quota as the entire lunar disk. Hidden
        # entries remain in the checklist but spend no regional priority.
        ranked, used = [], {}
        for tier in range(4):
            cells = {}
            for group, score, cell, f, xy in candidates:
                if group == tier:
                    cells.setdefault(cell, []).append((score, f, xy))
            for values in cells.values():
                values.sort(key=lambda row: (-row[0], row[1]['id']))
            queue = []
            for cell, values in cells.items():
                heapq.heappush(queue, (-(values[0][0]-.08*used.get(cell, 0)), cell, 0))
            while queue:
                _, cell, index = heapq.heappop(queue)
                _, f, xy = cells[cell][index]
                ranked.append((f, xy))
                if not self.labels.get(f['id'], {}).get('hidden'):
                    used[cell] = used.get(cell, 0)+1
                index += 1
                if index < len(cells[cell]):
                    heapq.heappush(queue, (-(cells[cell][index][0]-.08*used.get(cell, 0)), cell, index))
        return ranked if all_candidates else ranked[:self.max_labels]

    def _project_crater_rim(self, feature, radius_factors=(1.,)):
        """Terrain crest when available; otherwise the catalogue reference rim."""
        rim = self.terrain_rims.get(feature['id']) if radius_factors == (1.,) else None
        if rim:
            coordinates = np.asarray(rim['coordinates'], float)
            if coordinates.ndim == 2 and coordinates.shape[1] == 3 and len(coordinates) >= 16 and np.isfinite(coordinates).all():
                points, visible, _ = self.geometry.project(coordinates[:, 0], coordinates[:, 1], coordinates[:, 2])
                return transform_points(self.matrix, points), visible
        center = surface_vectors([feature["lat"]], [feature["lon"]])[0]
        east = np.array([-np.sin(np.radians(feature["lon"])), np.cos(np.radians(feature["lon"])), 0.])
        north = np.cross(center, east)
        angle = feature["diameter"]/(2*MOON_RADIUS_KM)*np.asarray(radius_factors)
        theta = np.linspace(0, 2*np.pi, 97)
        tangent = np.cos(theta[:, None])*north + np.sin(theta[:, None])*east
        rim = (np.cos(angle[:, None, None])*center + np.sin(angle[:, None, None])*tangent).reshape(-1, 3)
        lat = np.degrees(np.arcsin(np.clip(rim[:, 2], -1, 1)))
        lon = np.degrees(np.arctan2(rim[:, 1], rim[:, 0]))
        xy, visible, _ = self.geometry.project(lat, lon)
        pixels = transform_points(self.matrix, xy)
        return pixels, visible

    def crater_outline(self, feature, shape):
        """An ellipse (default) or the projected rim contour in the photograph.

        Catalogue diameter describes a reference outline, not a detected rim.
        Hidden hemisphere arcs are separated so limb contours cannot connect.
        """
        if not self.crater_outlines or self.geometry is None or self.matrix is None:
            return []
        if feature["kind"] not in ("Crater, craters", "Satellite Feature"):
            return []
        if feature['diameter'] < MIN_OUTLINE_DIAMETER_KM:
            return []
        pixels, visible = self._project_crater_rim(feature)
        extent = np.ptp(pixels, axis=0)
        if min(extent) < self.font_sizes(shape)[1]*1.6 or max(extent) < min(shape[:2])*.055:
            return []
        if self.crater_outline_shape != "terrain":
            pixels = _ellipse_outline(pixels)
        # Split at any occulted vertices; do not connect across the lunar limb.
        segments, segment = [], []
        for point, okay in zip(pixels, visible):
            if okay:
                segment.append(point.tolist())
            elif segment:
                if len(segment) >= 2:
                    segments.append(segment)
                segment = []
        if len(segment) >= 2:
            segments.append(segment)
        return segments


def export_svg(path, image, entries, project, leaders=None):
    entries = list(entries)
    font_sizes = project.label_font_sizes([feature for feature, _, _ in entries], image.shape)
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    embedded = base64.b64encode(buffer.getvalue()).decode("ascii")
    h, w = image.shape[:2]
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
             '<title>MoonLabeler annotated photograph</title>',
             f'<image id="photograph" width="{w}" height="{h}" xlink:href="data:image/png;base64,{embedded}"/>',
             '<g id="annotations" font-family="PingFang SC, sans-serif">']
    for feature, anchor, position in entries:
        fid = escape(feature["id"], {'"': '&quot;'})
        color = escape(project.color, {'"': '&quot;'})
        ax, ay = anchor
        x, y = position
        font_size = font_sizes[feature['id']]
        line = (leaders or {}).get(feature["id"], (ax, ay, x, y+font_size/2))
        lines.append(f'<g id="feature-{fid}">')
        outline = project.crater_outline(feature, image.shape)
        for segment in outline:
            contour = 'M '+ ' L '.join(f'{px:.3f},{py:.3f}' for px, py in segment)
            lines.append(f'<path class="crater-outline" d="{contour}" stroke="{color}" stroke-width="{max(1.2, font_size*.045):.3f}" fill="none"/>')
        lines.extend([
                      f'<path d="M {line[0]:.3f},{line[1]:.3f} L {line[2]:.3f},{line[3]:.3f}" stroke="{color}" stroke-width="{max(1.2, font_size*.035):.3f}" fill="none"/>',
                      '' if outline else f'<circle cx="{ax:.3f}" cy="{ay:.3f}" r="{max(2.5, font_size*.06):.3f}" fill="{color}"/>',
                      f'<text xml:space="preserve" x="{x:.3f}" y="{y+font_size:.3f}" fill="{color}" font-size="{font_size}" stroke="#141923" stroke-width="{max(2., font_size*.06):.3f}" paint-order="stroke">{escape(project.label_text(feature))}</text>',
                      '</g>'])
    lines.extend(['</g>', '</svg>'])
    Path(path).write_text('\n'.join(lines), encoding="utf-8")
