# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from dataclasses import dataclass, field
from pathlib import Path
import base64
import io
import json
import os
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image

from .geometry import Geometry, MOON_RADIUS_KM, surface_vectors
from .sources import read_image, write_json, COMMON_FEATURES
from .registration import transform_points

DEFAULT_FONT_PERCENT = 1.5


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

    def update_font_size(self, shape):
        short_side = min(shape[:2])
        if self.font_percent is None:
            # Migrate old pixel-size projects without changing their appearance.
            self.font_percent = self.font_size*100/short_side
        self.font_size = max(6, round(short_side*self.font_percent/100))

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
                "observer": {"latitude": self.latitude, "longitude": self.longitude},
                "terrain": {"dem_path": os.path.relpath(Path(self.terrain_path).resolve(), path.parent.resolve()) if self.terrain_path else "",
                            "settings": self.terrain_settings},
                "style": {k: getattr(self, k) for k in ("font_size", "font_percent", "color", "language", "min_diameter", "kind", "illuminated_only", "max_labels", "optimize_layout", "crater_outlines")}}
        write_json(path, data)

    @classmethod
    def load(cls, path):
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != "MoonLabeler" or data.get("version") != 2:
            raise ValueError("这不是受支持的 MoonLabeler 工程。")
        project = cls(image_path=str((path.parent / data["image_path"]).resolve()),
                      utc=data["utc"], anchors=data["anchors"], labels=data["labels"])
        project.latitude = data.get("observer", {}).get("latitude")
        project.longitude = data.get("observer", {}).get("longitude")
        terrain = data.get("terrain", {})
        project.terrain_path = str((path.parent/terrain["dem_path"]).resolve()) if terrain.get("dem_path") else ""
        project.terrain_settings = terrain.get("settings", {})
        project.crater_settings = data.get("crater_detection", {})
        project.identification = data.get("automatic_recognition", {})
        if data["geometry"]:
            project.geometry = Geometry.from_dict(data["geometry"])
        if data["matrix"] is not None:
            matrix = np.asarray(data["matrix"], float)
            if matrix.shape != (2, 3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix[:,:2])) < 1e-10:
                raise ValueError("工程配准矩阵无效。")
            project.matrix = matrix
        project.font_percent = None  # Older projects only store a pixel size.
        for key, value in data["style"].items():
            if key in ("font_size", "font_percent", "color", "language", "min_diameter", "kind", "illuminated_only", "max_labels", "optimize_layout", "crater_outlines"):
                setattr(project, key, value)
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

    def visible_features(self, catalog, shape, image=None):
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
        scale = np.sqrt(abs(np.linalg.det(self.matrix[:, :2])))
        brightness_limit = max(4., float(np.percentile(gray[::8, ::8], 95))*.08) if gray is not None else None
        offsets = np.linspace(-1, 1, 13)
        dx, dy = np.meshgrid(offsets, offsets)
        disk = dx*dx+dy*dy <= 1
        dx, dy = dx[disk], dy[disk]
        inside = (pixels[:,0] >= 0) & (pixels[:,0] < w) & (pixels[:,1] >= 0) & (pixels[:,1] < h)
        candidates = []
        for f, xy, okay, sunlight in zip(catalog, pixels, visible & inside, lit):
            if not okay:
                continue
            if f["diameter"] < self.min_diameter or (self.kind != "全部" and f["kind"] != self.kind):
                continue
            if self.illuminated_only:
                if gray is None:
                    if not sunlight:
                        continue
                else:
                    radius = max(4., min(min(h, w)*.08, f["diameter"]*scale/(2*MOON_RADIUS_KM)*1.12))
                    sx = np.clip(np.rint((xy[0]+radius*dx)/stride).astype(int), 0, gray.shape[1]-1)
                    sy = np.clip(np.rint((xy[1]+radius*dy)/stride).astype(int), 0, gray.shape[0]-1)
                    if np.percentile(gray[sy, sx], 80) < brightness_limit:
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
            candidates.append((f, xy))
        # A rille's catalogue diameter is its length: sorting every kind by
        # that number can crowd Tycho/Copernicus out of a whole-Moon result.
        # Explicitly requested labels and named craters/seas get first choice.
        primary = {"Crater, craters", "Mare, maria", "Oceanus, oceani"}
        candidates.sort(key=lambda pair: (bool(self.labels.get(pair[0]["id"], {}).get("force")),
                                          pair[0]["kind"] in primary,
                                          pair[0]["name"] in COMMON_FEATURES, pair[0]["diameter"]), reverse=True)
        return candidates[:self.max_labels]

    def _project_crater_rim(self, feature, radius_factors=(1.,)):
        """Catalogue rim coordinates shared by lighting and outline drawing."""
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
        """A geodesic catalogue rim projected into the registered photograph.

        Catalogue diameter describes a reference outline, not a detected rim.
        Hidden hemisphere arcs are separated so limb contours cannot connect.
        """
        if not self.crater_outlines or self.geometry is None or self.matrix is None:
            return []
        if feature["kind"] not in ("Crater, craters", "Satellite Feature"):
            return []
        pixels, visible = self._project_crater_rim(feature)
        extent = np.ptp(pixels, axis=0)
        if min(extent) < self.font_size*1.6 or max(extent) < min(shape[:2])*.055:
            return []
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
        line = (leaders or {}).get(feature["id"], (ax, ay, x, y+project.font_size/2))
        lines.append(f'<g id="feature-{fid}">')
        outline = project.crater_outline(feature, image.shape)
        for segment in outline:
            contour = 'M '+ ' L '.join(f'{px:.3f},{py:.3f}' for px, py in segment)
            lines.append(f'<path class="crater-outline" d="{contour}" stroke="{color}" stroke-width="{max(1.2, project.font_size*.045):.3f}" fill="none"/>')
        lines.extend([
                      f'<path d="M {line[0]:.3f},{line[1]:.3f} L {line[2]:.3f},{line[3]:.3f}" stroke="{color}" stroke-width="{max(1.2, project.font_size*.035):.3f}" fill="none"/>',
                      '' if outline else f'<circle cx="{ax:.3f}" cy="{ay:.3f}" r="{max(2.5, project.font_size*.06):.3f}" fill="{color}"/>',
                      f'<text x="{x:.3f}" y="{y+project.font_size:.3f}" fill="{color}" font-size="{project.font_size}" stroke="#141923" stroke-width="{max(2., project.font_size*.06):.3f}" paint-order="stroke">{escape(project.label_text(feature))}</text>',
                      '</g>'])
    lines.extend(['</g>', '</svg>'])
    Path(path).write_text('\n'.join(lines), encoding="utf-8")
