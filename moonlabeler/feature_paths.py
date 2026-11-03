# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Display-only baselines for named linear landforms, in lunar coordinates.

The small bundled layer is loaded on demand. Projected segments are cached by
the actual viewing geometry and fitted camera, including reflection and lens
distortion. No recognition, DEM sampling, or network access belongs here.
"""
from functools import lru_cache
import json
import math
from pathlib import Path

import numpy as np

from .geometry import Geometry
from .registration import transform_points
from .eyepiece import distort_points


PATH_KINDS = frozenset(("Rima", "Mons", "Dorsum", "Vallis", "Rupes", "Catena"))


@lru_cache(maxsize=1)
def _landforms():
    data = json.loads((Path(__file__).parent / "data/feature_paths.json").read_text(encoding="utf-8"))
    return data["features"]


def _view_key(project):
    g = project.geometry
    return (tuple(g.observer), tuple(g.right), tuple(g.north), g.distance_km,
            tuple(project.matrix.ravel()),
            json.dumps(project.identification.get("lens_distortion"), sort_keys=True),
            tuple(project.image_size) if project.image_size else None)


def _resample(points, step):
    points = np.asarray(points, dtype=float)
    lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    distinct = np.r_[True, np.diff(lengths) > 1e-8]
    points, lengths = points[distinct], lengths[distinct]
    if len(points) < 2 or lengths[-1] < 1e-5:
        return None
    along = np.linspace(0, lengths[-1], min(2048, max(2, math.ceil(lengths[-1]/step)+1)))
    return np.column_stack([np.interp(along, lengths, points[:, axis]) for axis in range(2)])


@lru_cache(maxsize=512)
def _projected(fid, view):
    record = _landforms().get(fid)
    if not record:
        return ()
    observer, right, north, distance, matrix, lens, image_size = view
    geometry = Geometry(np.array(observer), np.array(right), np.array(north), np.zeros(3), distance, "")
    matrix, lens = np.array(matrix).reshape(2, 3), json.loads(lens)
    result = []
    for line in record["paths"]:
        # Unwrap longitudes before interpolating across the date line. Small
        # angular steps also prevent a line jumping across the hidden limb.
        coordinates = np.array(line, dtype=float)
        coordinates[:, 0] = np.degrees(np.unwrap(np.radians(coordinates[:, 0])))
        dense = _resample(coordinates, .1)
        if dense is None:
            continue
        xy, visible, _ = geometry.project(dense[:, 1], dense[:, 0])
        pixels = distort_points(transform_points(matrix, xy), lens)
        valid = visible & np.isfinite(pixels).all(axis=1)
        if image_size:
            width, height = image_size
            valid &= ((pixels[:, 0] >= 0) & (pixels[:, 0] <= width) &
                      (pixels[:, 1] >= 0) & (pixels[:, 1] <= height))
        # Keep disconnected/occulted pieces separate; never join them with an
        # invented baseline. Captions later choose a sufficiently long piece.
        for indices in np.split(np.flatnonzero(valid), np.flatnonzero(np.diff(np.flatnonzero(valid)) > 1)+1):
            if len(indices) < 2:
                continue
            segment = _resample(pixels[indices], 2.)
            if segment is None:
                continue
            if segment[-1, 0] < segment[0, 0] or (abs(segment[-1, 0]-segment[0, 0]) < 1e-5 and segment[-1, 1] > segment[0, 1]):
                segment = segment[::-1]
            result.append(tuple(map(tuple, segment)))
    return tuple(sorted(result, key=lambda line: -np.linalg.norm(np.diff(line, axis=0), axis=1).sum()))


def projected_paths(project, feature):
    if (not project.follow_feature_paths or feature.get("kind", "").split(",")[0] not in PATH_KINDS
            or project.geometry is None or project.matrix is None):
        return ()
    return _projected(str(feature["id"]), _view_key(project))


def fitted_path_size(project, feature, size, span):
    """Allow a modest local size reduction; tiny targets keep normal captions."""
    paths = projected_paths(project, feature)
    if not paths or span <= 0:
        return size
    length = np.linalg.norm(np.diff(paths[0], axis=0), axis=1).sum()
    fitted = min(size, math.floor(length*.92/span))
    return fitted if fitted >= max(8, math.ceil(size*.65)) else size


@lru_cache(maxsize=1024)
def _place(paths, advances, tracking, size):
    widths = tuple(advance+(tracking if index < len(advances)-1 else 0.) for index, advance in enumerate(advances))
    return _place_rows(paths, ((widths, size, .15*size),))


@lru_cache(maxsize=1024)
def _place_rows(paths, rows):
    width = max(sum(advances) for advances, _, _ in rows)
    size = max(row_size for _, row_size, _ in rows)
    if width <= 0:
        return None
    for line in paths:
        source = _resample(line, max(1., size*.12))
        if source is None:
            continue
        step = np.linalg.norm(np.diff(source, axis=0), axis=1).mean()
        # Smooth in arc length, preserving broad bends and inflection points.
        # Try the least smoothing first; whole Latin words retain their shape.
        for smoothness in (.4, .65):
            sigma = max(1., size*smoothness/step)
            radius = max(2, math.ceil(sigma*3))
            kernel = np.exp(-.5*(np.arange(-radius, radius+1)/sigma)**2)
            kernel /= kernel.sum()
            points = np.column_stack([np.convolve(np.pad(source[:, axis], (radius, radius), mode="edge"),
                                                  kernel, mode="valid") for axis in range(2)])
            along = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
            length = along[-1]
            if width > length*.95:
                continue
            directions = np.gradient(points, axis=0)
            directions /= np.maximum(1e-8, np.linalg.norm(directions, axis=1))[:, None]
            normals = np.column_stack((-directions[:, 1], directions[:, 0]))
            candidates = []
            for fraction in (.5, .4, .6, .3, .7):
                center = float(np.clip(length*fraction, width/2+length*.025, length*.975-width/2))
                selected = np.abs(along-center) <= width/2
                deviation = float(np.linalg.norm(points[selected]-source[selected], axis=1).max())
                if deviation > max(2., size*.85):
                    continue
                placements, corners, all_angles, turn_costs = [], [], [], []
                for advances, row_size, offset in rows:
                    advances = np.array(advances)
                    centers = np.cumsum(np.r_[0., advances[:-1]])+advances/2
                    # Each language follows its own offset curve's arc length.
                    # Sharing base-line stations would squeeze the inner row.
                    row_points = points+normals*offset
                    row_along = np.r_[0., np.cumsum(np.linalg.norm(np.diff(row_points, axis=0), axis=1))]
                    row_center = float(np.interp(center, along, row_along))
                    distances = row_center-advances.sum()/2+centers
                    if distances[0]-advances[0]/2 < 0 or distances[-1]+advances[-1]/2 > row_along[-1]:
                        break
                    def row_sample(distance):
                        return np.column_stack([np.interp(distance, row_along, row_points[:, axis]) for axis in range(2)])
                    centers_xy = row_sample(distances)
                    # Font-shaped clusters keep their internal relative shape;
                    # the local baseline supplies only translation and rotation.
                    reach = np.maximum(row_size*.5, advances*.45)
                    tangent = row_sample(distances+reach)-row_sample(distances-reach)
                    norms = np.linalg.norm(tangent, axis=1)
                    if (norms < 1e-6).any():
                        break
                    tangent /= norms[:, None]
                    normal = np.column_stack((-tangent[:, 1], tangent[:, 0]))
                    angles = np.degrees(np.arctan2(tangent[:, 1], tangent[:, 0]))
                    short_neighbors = (advances[:-1] <= row_size*1.5) & (advances[1:] <= row_size*1.5)
                    if ((np.abs(angles) > 95).any() or np.ptp(angles) > 55 or
                            (np.abs(np.diff(angles))[short_neighbors] > 14).any()):
                        break
                    baselines = centers_xy-advances[:, None]/2*tangent
                    corners.extend(baselines+dx*advances[:, None]*tangent+dy*row_size*normal
                                   for dx in (0, 1) for dy in (-1, .25))
                    placements.extend((float(x), float(y), float(angle)) for (x, y), angle in zip(baselines, angles))
                    all_angles.extend(angles)
                    turn_costs.append(float(np.abs(np.diff(angles)).mean()) if len(angles) > 1 else 0.)
                else:
                    if np.ptp(all_angles) > 55:
                        continue
                    origin = np.concatenate(corners).min(axis=0)
                    glyphs = tuple((x-origin[0], y-origin[1], angle) for x, y, angle in placements)
                    # Prefer the formation's middle, not its straightest piece.
                    score = abs(fraction-.5)*2+deviation/size*.1+sum(turn_costs)/max(1, len(rows))*.01
                    candidates.append((score, tuple(origin), glyphs))
            if candidates:
                _, origin, glyphs = min(candidates, key=lambda candidate: candidate[0])
                return origin, glyphs
    return None


def caption_on_path(project, feature, rows):
    paths = projected_paths(project, feature)
    return _place_rows(paths, tuple((tuple(widths), size, offset) for widths, size, offset in rows)) if paths else None
