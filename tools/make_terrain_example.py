# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Generate a reference from real cached LOLA terrain; never a real photograph."""
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from moonlabeler.geometry import compute_geometry
from moonlabeler.project import Project
from moonlabeler.sources import load_catalog
from moonlabeler.terrain import ElevationMap, render_region


def main():
    root = Path(__file__).resolve().parents[1]
    cache = root/".cache"
    path = cache/"terrain/LDEM_16.LBL"
    utc = datetime(2026, 9, 23, 15, tzinfo=timezone.utc)
    geometry = compute_geometry(utc, cache/"ephemeris")
    feature = next(f for f in load_catalog(cache) if f["name"] == "Aristarchus")
    dem = ElevationMap.load(path)
    try:
        reference = render_region(dem, geometry, feature["lat"], feature["lon"], width_km=350, size=768)
    finally:
        dem.close()
    image_path = root/"examples/lola-aristarchus.png"
    Image.fromarray(reference.image).save(image_path)
    project = Project(image_path=str(image_path), utc=utc.isoformat(), geometry=geometry,
                      matrix=reference.matrix, terrain_path=str(path), min_diameter=5,
                      font_size=16, max_labels=25,
                      terrain_settings={"center_id":feature["id"], "width_km":350, "size":768,
                                        "model":"Lommel-Seeliger", "gamma":1.6, "shadows":True})
    project.save(image_path.with_suffix(".moonlabel"))
    print(f"Saved real LOLA terrain simulation: {image_path}")


if __name__ == "__main__":
    main()
