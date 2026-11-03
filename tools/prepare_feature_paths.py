# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Build the offline label-path layer from the reviewed lunar GeoJSON.

Usage: .venv/bin/python tools/prepare_feature_paths.py moon_outlines_raw.json
Area axes are representative label baselines, not surveyed mountain crests.
"""
import argparse
import json
from pathlib import Path

import numpy as np


KINDS = {"Rima", "Mons", "Dorsum", "Vallis", "Rupes", "Catena"}


def source_features(source):
    correction = source["meta"].get("radius_correction", {}).get("factor", 1)
    if correction != 1:
        raise ValueError("Use unscaled lunar coordinates, not radius-corrected outlines")
    if "features" in source:
        yield from source["features"]
        return
    for classification in source["classifications"]:
        for feature in classification["features"]:
            geometry = feature["geometry"]
            kind = geometry.get("type") if geometry else None
            if kind in ("LineString", "MultiLineString"):
                role = "linear"
            elif kind in ("Polygon", "MultiPolygon"):
                polygons = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"]
                def rectangle(polygon):
                    ring = np.asarray(polygon[0])
                    return (len(polygon) == 1 and len(ring) == 5 and np.array_equal(ring[0], ring[-1])
                            and len(np.unique(ring[:, 0])) == len(np.unique(ring[:, 1])) == 2)
                role = "extent" if all(rectangle(polygon) for polygon in polygons) else "boundary"
            else:
                role = "unavailable"
            yield {"properties": {"id": str(feature["feature_id"]), "name": feature["feature"],
                                  "type": feature["type"], "geometry_role": role,
                                  "diameter_km": float(feature["diameter"])}, "geometry": geometry}


def simplify_line(line, diameter):
    """Bound source-vertex deviation to 100 m, stricter for small formations."""
    coordinates = np.asarray(line, dtype=float)
    lon, lat = np.radians(coordinates).T
    points = 1737.4*np.column_stack((np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)))
    tolerance = max(0, min(.1, diameter*.005)-.000215)
    keep, pending = {0, len(points)-1}, [(0, len(points)-1)]
    while pending:
        first, last = pending.pop()
        if last <= first+1:
            continue
        delta = points[last]-points[first]
        offsets = points[first+1:last]-points[first]
        length2 = float(delta @ delta)
        fraction = np.clip(offsets @ delta/length2, 0, 1) if length2 > 1e-20 else np.zeros(len(offsets))
        distances = np.linalg.norm(offsets-fraction[:, None]*delta, axis=1)
        maximum = int(np.argmax(distances))
        if distances[maximum] > tolerance:
            middle = first+1+maximum
            keep.add(middle)
            pending.extend(((first, middle), (middle, last)))
    return np.round(coordinates[sorted(keep)], 5).tolist()


def area_axis(ring):
    """Follow successive interior cross-section centers of an elongated area."""
    coordinates = np.radians(np.asarray(ring, dtype=float))
    lon, lat = coordinates.T
    vectors = np.column_stack((np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)))
    center = vectors.mean(axis=0)
    center /= np.linalg.norm(center)
    east = np.cross([0., 0., 1.], center)
    east /= np.linalg.norm(east)
    north = np.cross(center, east)
    flat = vectors @ np.column_stack((east, north))
    # Uniform edge sampling makes the principal direction independent of how
    # densely the source happened to digitize either side of the boundary.
    lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(flat, axis=0), axis=1))]
    sampled = np.column_stack([np.interp(np.linspace(0, lengths[-1], 256), lengths, flat[:, axis]) for axis in range(2)])
    _, axes = np.linalg.eigh(np.cov(sampled.T))
    local = flat @ axes[:, ::-1]
    extent = np.ptp(local, axis=0)
    if extent[0] < extent[1]*1.7:
        return []  # A compact peak/area has no defensible linear label axis.
    result = []
    for x in np.linspace(local[:, 0].min()+extent[0]*.03, local[:, 0].max()-extent[0]*.03, 48):
        a, b = local[:-1], local[1:]
        mask = (a[:, 0] > x) != (b[:, 0] > x)
        intersections = np.sort(a[mask, 1]+(x-a[mask, 0])*(b[mask, 1]-a[mask, 1])/(b[mask, 0]-a[mask, 0]))
        intervals = list(zip(intersections[::2], intersections[1::2]))
        if not intervals:
            return []
        low, high = max(intervals, key=lambda pair: pair[1]-pair[0])
        result.append([x, (low+high)/2])
    result = np.array(result)
    if (np.linalg.norm(np.diff(result, axis=0), axis=1) > extent[0]*.12).any():
        return []  # Disjoint branches must not be bridged across empty terrain.
    flat_axis = result @ axes[:, ::-1].T
    xyz = flat_axis[:, :1]*east+flat_axis[:, 1:]*north+np.sqrt(np.maximum(0., 1-np.sum(flat_axis**2, axis=1)))[:, None]*center
    return np.round(np.column_stack((np.degrees(np.arctan2(xyz[:, 1], xyz[:, 0])),
                                    np.degrees(np.arcsin(np.clip(xyz[:, 2], -1, 1))))), 5).tolist()


def build(source):
    features = {}
    for feature in source_features(source):
        properties, geometry = feature["properties"], feature["geometry"]
        if properties["type"].split(",")[0] not in KINDS or not geometry:
            continue
        kind, coordinates = geometry["type"], geometry["coordinates"]
        role = properties["geometry_role"]
        if role == "linear":
            paths = [simplify_line(line, properties["diameter_km"])
                     for line in ([coordinates] if kind == "LineString" else coordinates)]
            method = "source_line"
        elif role == "boundary" and kind == "Polygon" and len(coordinates) == 1:
            # Named mountain ranges and ridges can have areal outlines. A Mons
            # alone is a peak; giving it an invented mountain-chain path is wrong.
            if properties["type"].startswith("Mons") and not properties["name"].startswith("Montes "):
                continue
            axis = area_axis(coordinates[0])
            paths = [axis] if axis else []
            method = "area_cross_sections"
        else:
            continue  # Includes Rima Ariadaeus's rectangular extent.
        if paths:
            features[properties["id"]] = {"name": properties["name"], "kind": properties["type"],
                                         "method": method, "paths": paths}
    return {"meta": {"source": "IAU / USGS Gazetteer of Planetary Nomenclature",
                     "url": "https://planetarynames.wr.usgs.gov/",
                     "provided_by": "樊仕达 (10deg)", "source_fetched_utc": source["meta"]["fetched_utc"],
                     "source_line_max_vertex_deviation_km": .1,
                     "coordinates": "Moon LOLA 2011, [east longitude, latitude], degrees; no positional scaling",
                     "derivation": "Source lines and representative interior axes for elongated areas; not surveyed crests",
                     "excluded": "Crater circles, compact peaks, absent geometry and rectangular extents (including feature 5040)"},
            "features": features}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]/"moonlabeler/data/feature_paths.json")
    args = parser.parse_args()
    data = build(json.loads(args.source.read_text(encoding="utf-8")))
    data['meta']['source_file'] = args.source.name
    args.output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)+"\n", encoding="utf-8")
    print(f"{len(data['features'])} landform paths; {args.output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
