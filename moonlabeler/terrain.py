# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Local LOLA terrain shading, with spherical view projection.

This is a 2.5-D reference renderer, not a full DEM ray/terrain intersection
renderer. Cast shadows are sampled at finite steps and limited to 80 km.
It uses no LTVT code. See ACKNOWLEDGEMENTS.md for algorithm/data references.
"""
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import re

import numpy as np

from .geometry import MOON_RADIUS_KM, surface_vectors
from .sources import download

LOLA_BASE = "https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/"


def download_basic_dem(cache):
    folder = Path(cache)/"terrain"
    label = download(LOLA_BASE+"LDEM_16.LBL", folder/"LDEM_16.LBL")
    download(LOLA_BASE+"LDEM_16.IMG", folder/"LDEM_16.IMG")
    return label


class ElevationMap:
    """Pixel-centered latitude/longitude grid, height in km above 1737.4 km."""
    def __init__(self, data, north, west, pixels_per_degree, scale=1., name="DEM"):
        if data.ndim != 2 or min(data.shape) < 2 or not np.isfinite([north, west, pixels_per_degree, scale]).all() or pixels_per_degree <= 0 or scale <= 0:
            raise ValueError("DEM 网格或分辨率无效。")
        if not -90 < north <= 90 or data.shape[0]/pixels_per_degree > north+90+1e-6:
            raise ValueError("DEM 纬度范围无效。")
        if data.shape[1]/pixels_per_degree > 360+1e-6:
            raise ValueError("DEM 经度范围超过 360°。")
        self.data, self.north, self.west = data, float(north), float(west)
        self.ppd, self.scale, self.name = float(pixels_per_degree), float(scale), name
        self.global_longitude = abs(data.shape[1]/self.ppd-360) < 1e-6

    @property
    def resolution_km(self):
        return np.pi*MOON_RADIUS_KM/(180*self.ppd)

    @cached_property
    def maximum_height_km(self):
        """Exact ceiling for small read-only maps; avoid scanning large DEMs."""
        if self.data.nbytes > 64*1024*1024:
            return float('inf')
        maximum = float(np.max(np.asarray(self.data))) * self.scale
        return maximum if np.isfinite(maximum) else float('inf')

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as stored:
                data = stored["height_km"].astype(np.float32)
                return cls(data, float(stored["north"]), float(stored["west"]),
                           float(stored["pixels_per_degree"]), name=path.name)
        if path.suffix.lower() == ".img":
            options = [path.with_suffix(suffix) for suffix in (".LBL", ".lbl")]
            path = next((p for p in options if p.exists()), options[0])
        if path.suffix.lower() != ".lbl" or not path.exists():
            raise ValueError("请选择 LOLA 柱面 DEM 的 LBL 文件，并将同名 IMG 放在旁边。也支持约定格式的 NPZ。")
        text = path.read_text(encoding="ascii")
        # Remove PDS comments before extracting single-line metadata fields.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        fields = dict(re.findall(r"^\s*([\w^]+)\s*=\s*([^\r\n]+)", text, re.M))
        def value(key):
            try:
                return fields[key].strip().strip('"')
            except KeyError as exc:
                raise ValueError(f"DEM 标签缺少 {key}。") from exc
        def number(key):
            return float(value(key).split()[0])
        if "LOLA" not in value("INSTRUMENT_ID") or value("TARGET_NAME") != "MOON":
            raise ValueError("目前仅支持月球 LOLA LDEM 数据，其他产品的单位和坐标需另行处理。")
        if value("MAP_PROJECTION_TYPE").replace("_", " ") != "SIMPLE CYLINDRICAL":
            raise ValueError("目前仅支持柱面经纬度 DEM，不支持极区立体投影。")
        if value("POSITIVE_LONGITUDE_DIRECTION") != "EAST" or abs(number("MAP_PROJECTION_ROTATION")) > 1e-9:
            raise ValueError("DEM 必须使用东经为正、无网格旋转的经纬度坐标。")
        if "MEAN EARTH/POLAR AXIS OF DE421" not in value("COORDINATE_SYSTEM_NAME"):
            raise ValueError("DEM 坐标系与当前 DE421 月面几何不一致。")
        if value("UNIT") != "METER" or abs(number("OFFSET")-1000*MOON_RADIUS_KM) > 1:
            raise ValueError("DEM 必须使用米及 1737.4 km 参考半径。请使用更新后的 LOLA 标签。")
        dtypes = {"LSB_INTEGER": "<i2", "MSB_INTEGER": ">i2"}
        sample_type = value("SAMPLE_TYPE")
        if number("SAMPLE_BITS") != 16 or sample_type not in dtypes:
            raise ValueError("目前支持 LOLA 16 位有符号整数 IMG。")
        filename = value("^IMAGE")
        if Path(filename).name != filename or any(char in filename for char in "()"):
            raise ValueError("仅支持同目录、独立 IMG 文件的 PDS 标签。")
        image = path.parent/filename
        if not image.exists():
            image = next((p for p in path.parent.iterdir() if p.name.casefold() == filename.casefold()), image)
        rows, columns = int(number("LINES")), int(number("LINE_SAMPLES"))
        ppd = number("MAP_RESOLUTION")
        north, south = number("MAXIMUM_LATITUDE"), number("MINIMUM_LATITUDE")
        west, east = number("WESTERNMOST_LONGITUDE"), number("EASTERNMOST_LONGITUDE")
        span = east-west if east > west else east-west+360
        if abs((north-south)*ppd-rows) > 1e-4 or abs(span*ppd-columns) > 1e-4:
            raise ValueError("DEM 边界、分辨率和像素数量不一致。")
        if not image.exists() or image.stat().st_size != rows*columns*2:
            raise ValueError("DEM 的 IMG 缺失或长度与标签不一致。请下载完整数据。")
        # Read only needed cells even for multi-GB regional products.
        data = np.memmap(image, dtype=dtypes[sample_type], mode="r", shape=(rows, columns))
        return cls(data, north, west, ppd, number("SCALING_FACTOR")/1000, value("PRODUCT_ID"))

    def close(self):
        if isinstance(self.data, np.memmap):
            self.data._mmap.close()

    def sample(self, latitude, longitude):
        latitude, longitude = np.broadcast_arrays(np.asarray(latitude, float), np.asarray(longitude, float))
        y = (self.north-latitude)*self.ppd-.5
        x = ((longitude-self.west) % 360)*self.ppd-.5
        valid = np.isfinite(x) & np.isfinite(y) & (y >= -.5) & (y <= self.data.shape[0]-.5)
        if not self.global_longitude:
            valid &= (x >= -.5) & (x <= self.data.shape[1]-.5)
            x = np.clip(x, 0, self.data.shape[1]-1)
        y = np.clip(np.nan_to_num(y), 0, self.data.shape[0]-1)
        x = np.nan_to_num(x)
        x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
        fx, fy = x-x0, y-y0
        x1, y1 = (x0+1) % self.data.shape[1], np.minimum(y0+1, self.data.shape[0]-1)
        x0 %= self.data.shape[1]
        heights = ((1-fx)*(1-fy)*self.data[y0, x0] + fx*(1-fy)*self.data[y0, x1] +
                   (1-fx)*fy*self.data[y1, x0] + fx*fy*self.data[y1, x1])*self.scale
        return np.where(valid, heights, np.nan)

    def normals(self, latitude, longitude):
        radial = surface_vectors(latitude, longitude)
        lat, lon = np.radians(latitude), np.radians(longitude)
        east = np.column_stack((-np.sin(lon), np.cos(lon), np.zeros_like(lon)))
        north = np.column_stack((-np.sin(lat)*np.cos(lon), -np.sin(lat)*np.sin(lon), np.cos(lat)))
        step = .5/self.ppd
        vertical = (self.sample(latitude+step, longitude)-self.sample(latitude-step, longitude))/(2*np.radians(step)*MOON_RADIUS_KM)
        horizontal = (self.sample(latitude, longitude+step)-self.sample(latitude, longitude-step))/(2*np.radians(step)*MOON_RADIUS_KM*np.maximum(np.cos(lat), 1e-6))
        normal = radial - horizontal[:, None]*east - vertical[:, None]*north
        return normal/np.linalg.norm(normal, axis=1)[:, None]


def terrain_shadow(dem, radial, height, sun, steps=32, maximum_km=80.):
    """Sample terrain along the Sun ray. Unknown terrain does not invent shadows."""
    position = radial*(MOON_RADIUS_KM+height)[:, None]
    shadow = np.zeros(len(position), bool)
    active = np.arange(len(position))
    ceiling = MOON_RADIUS_KM + getattr(dem, 'maximum_height_km', float('inf'))
    along_sun = position @ sun
    sun_squared = float(np.dot(sun, sun))
    for distance in np.geomspace(max(.01, dem.resolution_km*.75), maximum_km, steps):
        if not len(active):
            break
        ray = position[active] + distance*sun
        radius = np.linalg.norm(ray, axis=1)
        # Once above every DEM height and moving outward, the rest of this
        # ray cannot hit terrain. Already-shadowed rays also need no work.
        keep = ~((radius >= ceiling) & (along_sun[active] + distance*sun_squared >= 0))
        active, ray, radius = active[keep], ray[keep], radius[keep]
        if not len(active):
            break
        latitude = np.degrees(np.arcsin(ray[:, 2]/radius))
        longitude = np.degrees(np.arctan2(ray[:, 1], ray[:, 0]))
        terrain_radius = MOON_RADIUS_KM+dem.sample(latitude, longitude)
        blocked = radius < terrain_radius-1e-4
        shadow[active[blocked]] = True
        active = active[~blocked]
    return shadow


@dataclass
class TerrainReference:
    image: np.ndarray
    matrix: np.ndarray  # geometry's projected xy -> reference image pixel
    valid_fraction: float
    resolution_km: float
    width_km: float
    center_lat: float
    center_lon: float


def render_region(dem, geometry, center_lat, center_lon, width_km=300., size=768,
                  model="Lommel-Seeliger", gamma=1.6, shadows=True):
    if not 10 <= width_km <= 2000 or not 128 <= size <= 1536 or not .3 <= gamma <= 4:
        raise ValueError("模拟图的视野、尺寸或亮度参数超出范围。")
    if model not in ("Lambert", "Lommel-Seeliger"):
        raise ValueError("不支持的光照模型。")
    center, visible, _ = geometry.project([center_lat], [center_lon])
    direction = surface_vectors([center_lat], [center_lon])[0]
    if not visible[0] or direction @ geometry.observer < .2:
        raise ValueError("此区域位于背面或过于接近月缘，当前球面参考模拟不适用。")
    if not np.isfinite(dem.sample([center_lat], [center_lon]))[0]:
        raise ValueError("所选 DEM 不覆盖这个区域，请换区域或导入对应数据。")
    scale = size*MOON_RADIUS_KM/width_km
    matrix = np.array([[scale, 0, size/2-scale*center[0, 0]],
                       [0, scale, size/2-scale*center[0, 1]]])
    output = np.zeros((size, size), np.float32)
    valid_pixels = 0
    for first in range(0, size, 64):
        last = min(size, first+64)
        px, py = np.meshgrid(np.arange(size)+.5, np.arange(first, last)+.5)
        points = np.column_stack(((px.ravel()-matrix[0, 2])/scale, (py.ravel()-matrix[1, 2])/scale))
        latitude, longitude, disk = geometry.unproject(points)
        height = dem.sample(latitude, longitude)
        radial = surface_vectors(latitude, longitude)
        normals = dem.normals(latitude, longitude)
        view = geometry.observer*geometry.distance_km - radial*(MOON_RADIUS_KM+height)[:, None]
        view /= np.linalg.norm(view, axis=1)[:, None]
        incidence = np.maximum(normals @ geometry.sun, 0)
        emission = np.maximum(np.sum(normals*view, axis=1), 0)
        valid = disk & np.isfinite(height) & np.isfinite(normals).all(axis=1)
        valid_pixels += int(valid.sum())
        light = incidence if model == "Lambert" else incidence/np.maximum(incidence+emission, 1e-8)
        lit = valid & (incidence > 0) & (emission > 0)
        if shadows and lit.any():
            hidden = terrain_shadow(dem, radial[lit], height[lit], geometry.sun)
            indices = np.flatnonzero(lit)
            lit[indices[hidden]] = False
        brightness = np.where(lit, light, 0)
        output[first:last] = np.nan_to_num(brightness).reshape(last-first, size)
    fraction = valid_pixels/(size*size)
    if fraction < .5:
        raise ValueError("DEM 有效覆盖不足一半，请缩小视野或换对应区域的数据。")
    # Fixed normalization preserves lighting contrasts, including a dark field.
    boost = 1.8 if model == "Lommel-Seeliger" else 1.
    gray = np.uint8(255*np.clip(output*boost, 0, 1)**(1/gamma))
    return TerrainReference(np.repeat(gray[:, :, None], 3, axis=2), matrix,
                            fraction, dem.resolution_km, width_km, center_lat, center_lon)
