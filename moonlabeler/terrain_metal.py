# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional Apple GPU shading for the coarse, full-disk terrain search.

Projection stays in CPU float64. The Metal kernel evaluates the same bilinear
DEM, slope and twelve-step shadow model in float32. Final pose refinement and
validation still use the existing CPU path. No MLX import on other platforms.
"""
import logging
import os
import platform
import threading

import numpy as np

from .geometry import MOON_RADIUS_KM
from .terrain import shade_atlas_points

_LOG = logging.getLogger(__name__)
_lock = threading.Lock()
_disabled = False
_kernel = None

_HEADER = r'''
float sample_grid(device const float* dem, int xbase, int ybase, float fx, float fy,
                  int rows, int cols, float scale) {
    int dx = int(floor(fx)), dy = int(floor(fy));
    fx -= float(dx); fy -= float(dy);
    int x0 = (xbase+dx) % cols, y0 = ybase+dy;
    if (y0 < -1 || (y0 == -1 && fy < .5f) || y0 >= rows || (y0 == rows-1 && fy > .5f)) return NAN;
    if (y0 < 0) { y0 = 0; fy = 0; }
    if (y0 >= rows-1) { y0 = rows-1; fy = 0; }
    x0 = (x0+cols) % cols;
    int x1 = (x0+1) % cols, y1 = min(y0+1, rows-1);
    return ((1-fx)*(1-fy)*dem[y0*cols+x0] + fx*(1-fy)*dem[y0*cols+x1]
          + (1-fx)*fy*dem[y1*cols+x0] + fx*fy*dem[y1*cols+x1])*scale;
}
float sample_height(device const float* dem, float lat, float lon,
                    int rows, int cols, float north, float west, float ppd, float scale) {
    float y = (north-lat)*ppd-0.5f;
    if (!isfinite(lat) || !isfinite(lon) || y < -0.5f || y > float(rows)-0.5f) return NAN;
    float longitude = lon-west;
    longitude -= 360.0f*floor(longitude/360.0f);
    float x = longitude*ppd-0.5f;
    y = clamp(y, 0.0f, float(rows-1));
    int x0 = int(floor(x)), y0 = int(floor(y));
    float fx = x-float(x0), fy = y-float(y0);
    x0 = (x0 % cols + cols) % cols;
    int x1 = (x0+1) % cols, y1 = min(y0+1, rows-1);
    return ((1-fx)*(1-fy)*dem[y0*cols+x0] + fx*(1-fy)*dem[y0*cols+x1]
          + (1-fx)*fy*dem[y1*cols+x0] + fx*fy*dem[y1*cols+x1])*scale;
}
'''

_SOURCE = r'''
uint i = thread_position_in_grid.x;
if (i >= uint(coords_shape[0])) return;
float lat = coords[6*i], lon = coords[6*i+1];
repair[i] = fabs(lat) > 89.0f;
int rows = int(params[0]), cols = int(params[1]);
float north = params[2], west = params[3], ppd = params[4], scale = params[5];
float radius0 = params[6], ceiling = params[7];
float3 sun = float3(params[8], params[9], params[10]);
float3 observer = float3(params[11], params[12], params[13]);
float rad = 0.017453292519943295f;
float a = lat*rad, b = lon*rad;
float3 radial = float3(cos(a)*cos(b), cos(a)*sin(b), sin(a));
int xbase = int(coords[6*i+2]), ybase = int(coords[6*i+3]);
float fx = coords[6*i+4], fy = coords[6*i+5];
float height = sample_grid(dem, xbase, ybase, fx, fy, rows, cols, scale);
float step = 0.5f/ppd;
float vertical = (sample_grid(dem, xbase, ybase, fx, fy-.5f, rows, cols, scale)
                -sample_grid(dem, xbase, ybase, fx, fy+.5f, rows, cols, scale))
                /(2*step*rad*radius0);
float horizontal = (sample_grid(dem, xbase, ybase, fx+.5f, fy, rows, cols, scale)
                  -sample_grid(dem, xbase, ybase, fx-.5f, fy, rows, cols, scale))
                  /(2*step*rad*radius0*max(cos(a), 1e-6f));
float3 east = float3(-sin(b), cos(b), 0);
float3 northward = float3(-sin(a)*cos(b), -sin(a)*sin(b), cos(a));
float3 normal = normalize(radial-horizontal*east-vertical*northward);
float sun_dot = dot(normal, sun), view_dot = dot(normal, observer);
float incidence = max(sun_dot, 0.0f);
float emission = max(view_dot, 0.0f);
if (fabs(sun_dot) < 1e-5f || fabs(view_dot) < 1e-5f) repair[i] = 1;
if (!isfinite(height) || !all(isfinite(normal)) || incidence <= 0 || emission <= 0) {
    out[i] = 0; return;
}
float3 position = radial*(radius0+height);
float along_sun = dot(position, sun), sun_squared = dot(sun, sun);
for (int j = 0; j < 12; ++j) {
    float distance = distances[j];
    float3 ray = position+distance*sun;
    float radius = length(ray);
    if (fabs(radius-ceiling) < .004f) repair[i] = 1;
    if (radius >= ceiling && along_sun+distance*sun_squared >= 0) break;
    float ray_lat = asin(clamp(ray.z/radius, -1.0f, 1.0f))/rad;
    float ray_lon = atan2(ray.y, ray.x)/rad;
    float terrain = radius0+sample_height(dem, ray_lat, ray_lon, rows, cols, north, west, ppd, scale);
    if (fabs(radius-terrain+1e-4f) < .004f) repair[i] = 1;
    if (radius < terrain-1e-4f) { out[i] = 0; return; }
}
float light = sqrt(clamp(2*incidence/(incidence+emission+1e-8f), 0.0f, 1.0f));
float brightness = light*220.0f;
float ratio = 2*incidence/(incidence+emission+1e-8f);
if ((light < 1 && fabs(brightness-round(brightness)) < .02f) || fabs(ratio-1) < 1e-5f) repair[i] = 1;
out[i] = uchar(brightness);
'''


def _eligible(dem, size):
    return (platform.system() == 'Darwin' and platform.machine() == 'arm64'
            and size >= 512 and getattr(dem, 'global_longitude', False)
            and dem.data.nbytes <= 64*1024*1024)


def try_render(dem, geometry, size):
    """Return a GPU atlas, or None so the caller uses the CPU implementation."""
    global _disabled
    if os.environ.get('MOONLABELER_COMPUTE', 'auto').lower() == 'cpu' or not _eligible(dem, size):
        return None
    # Qt workers may run on different threads. Serialize the small GPU entry
    # point and use a per-call stream rather than a thread-bound global stream.
    with _lock:
        if _disabled:
            return None
        try:
            return _render(dem, geometry, size)
        except (ImportError, RuntimeError, OSError, MemoryError) as exc:
            _disabled = True
            _LOG.warning('Metal terrain unavailable; using CPU: %s', exc)
            return None


def _render(dem, geometry, size):
    import mlx.core as mx
    global _kernel
    if not mx.metal.is_available():
        raise RuntimeError('No Metal device')
    if _kernel is None:
        _kernel = mx.fast.metal_kernel(
            name='moonlabeler_terrain', input_names=['dem', 'coords', 'params', 'distances'],
            output_names=['out', 'repair'], header=_HEADER, source=_SOURCE)
    scale, center = size*.47, (size-1)/2
    reference = np.zeros((size, size), np.uint8)
    with mx.stream(mx.new_stream(mx.gpu)):
        # Copy only once per atlas; never retain a view of a subsequently closed
        # memmap. Limit eligibility above so large user DEMs remain on the CPU.
        data = mx.array(np.asarray(dem.data, dtype=np.float32))
        params = mx.array(np.array([
            *dem.data.shape, dem.north, dem.west, dem.ppd, dem.scale,
            MOON_RADIUS_KM, MOON_RADIUS_KM+dem.maximum_height_km,
            *geometry.sun, *geometry.observer], dtype=np.float32))
        distances = mx.array(np.geomspace(max(.01, dem.resolution_km*.75), 80., 12).astype(np.float32))
        for first in range(0, size, 64):
            x, y = np.meshgrid(np.arange(size), np.arange(first, min(size, first+64)))
            points = np.column_stack(((x.ravel()-center)/scale, (y.ravel()-center)/scale))
            lat, lon, disk = geometry.unproject(points)
            indices = np.flatnonzero(disk)
            if not len(indices):
                continue
            # Preserve DEM subpixel fractions separately: rounding a large
            # absolute grid coordinate to float32 can change SIFT features.
            latitude, longitude = lat[indices], lon[indices]
            gx = ((longitude-dem.west) % 360)*dem.ppd-.5
            gy = (dem.north-latitude)*dem.ppd-.5
            ix, iy = np.floor(gx), np.floor(gy)
            coords = mx.array(np.column_stack((latitude, longitude, ix, iy, gx-ix, gy-iy)).astype(np.float32))
            result, repair = _kernel(inputs=[data, coords, params, distances],
                             grid=(len(indices), 1, 1), threadgroup=(256, 1, 1),
                             output_shapes=[(len(indices),), (len(indices),)], output_dtypes=[mx.uint8, mx.uint8])
            mx.eval(result, repair)
            slab = reference[first:first+x.shape[0]].reshape(-1)
            slab[indices] = np.asarray(result)
            uncertain = indices[np.asarray(repair).astype(bool)]
            if len(uncertain):
                slab[uncertain] = shade_atlas_points(dem, geometry, lat[uncertain], lon[uncertain])
    return reference, np.array([[scale, 0., center], [0., scale, center]])
