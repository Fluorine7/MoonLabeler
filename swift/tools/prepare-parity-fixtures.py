#!/usr/bin/env python3
"""Development-only numeric oracles from the checked-out Python 0.12.1 source."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from moonlabeler.annotation_relief import _sample
from moonlabeler.annotation_style import caption_text, path_caption_rows
from moonlabeler.annotation_style import path_caption_typography
from moonlabeler.feature_paths import _place_rows, projected_paths
from moonlabeler.project import Project
from moonlabeler.registration import calibration_report, transform_points
from moonlabeler.sources import load_catalog
from moonlabeler.terrain import ElevationMap

app = QApplication([])
catalog = load_catalog(ROOT / '.cache')
by_name = {f['name']: f for f in catalog}
project = Project.load(ROOT / 'examples/demo.moonlabel')
project.image_size = (1600, 1450)
project.update_font_size((1450, 1600, 3))
fixtures = ROOT / 'swift/Tests/MoonCoreTests/Fixtures'
caption_cases = []
project.follow_feature_paths = True
for name in ('Montes Apenninus', 'Vallis Alpes', 'Rima Hadley'):
    feature = by_name[name]
    size = project.label_font_sizes([feature], (1450, 1600, 3))[feature['id']]
    text = caption_text(project, feature)
    typography = path_caption_typography(project, feature, text, size)
    caption_cases.append(dict(id=feature['id'], text=text, size=size, origin=typography.origin,
                              glyphs=typography.glyphs, scales=typography.glyph_scales, advances=typography.glyph_advances))
editor_fixtures = ROOT/'swift/Tests/MoonEditorTests/Fixtures'
editor_fixtures.mkdir(exist_ok=True)
(editor_fixtures/'caption-0121-oracle.json').write_text(json.dumps(caption_cases, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
if '--captions-only' in sys.argv:
    print(f'Wrote {len(caption_cases)} shaped caption cases.'); sys.exit(0)
dem = ElevationMap.load(ROOT / 'swift/Sources/MoonCore/Resources/LDEM_16.LBL')
features = [by_name[n] for n in ('Copernicus', 'Tycho', 'Clavius', 'Plato')]
manual = []
for mirrored in (False, True):
    matrix = np.array([[-570., 30., 800.], [30., 570., 700.]]) if mirrored else np.array([[570., -30., 800.], [30., 570., 700.]])
    truth = _sample(catalog, project.geometry, matrix, (1450, 1600, 3), dem, None)
    for shape in ('ellipse', 'terrain'):
        original = replace(project, matrix=matrix, labels={}, terrain_rims={}, annotation_relief=truth, projection_surface='terrain', crater_outline_shape=shape)
        target = original.annotation_points(features)[0]
        sphere = project.geometry.project([f['lat'] for f in features], [f['lon'] for f in features])[0]
        coarse = calibration_report(sphere, target, 'auto')
        relief = _sample(catalog, project.geometry, coarse.matrix, (1450, 1600, 3), dem, None)
        provisional = replace(original, matrix=coarse.matrix, annotation_relief=relief)
        predicted = provisional.annotation_points(features)[0]
        inverse = np.linalg.inv(np.vstack((coarse.matrix, [0, 0, 1])))[:2]
        report = calibration_report(transform_points(inverse, predicted), target, 'auto')
        final = replace(provisional, matrix=report.matrix)
        manual.append(dict(shape=shape, ids=[f['id'] for f in features], target=target.tolist(), matrix=report.matrix.tolist(), rms=report.rms_px,
                           anchors=final.annotation_points(features)[0].tolist(), point_ids=sorted(relief['points']), rim_ids=sorted(relief['rims'])))
dem.close()
(fixtures/'manual-relief-0121-oracle.json').write_text(json.dumps(manual, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

curves = [
    ([[[0, 80], [500, 80]]], [([18]*8, 20, 3)]),
    ([[[0, 90], [60, 70], [130, 50], [210, 60], [300, 90], [420, 100]]], [([20]*6, 22, -4.84), ([9, 12, 10, 11, 8, 12, 10, 11, 9, 10, 12], 18, 21.56)]),
    ([[[0, 0], [0, 100], [100, 100]]], [([25]*8, 22, 3.3)]),
    ([[[0, 0], [10, 0]], [[100, 100], [220, 100], [450, 150]]], [([10]*12, 16, 2.4)]),
]
projection = []
project.follow_feature_paths = True
for name in ('Montes Apenninus', 'Vallis Alpes', 'Rima Hadley'):
    feature = by_name[name]
    paths = projected_paths(project, feature)
    projection.append(dict(id=feature['id'], paths=paths))
    rows = path_caption_rows(project, feature, caption_text(project, feature), 22)
    curves.append((paths, [(advances, size, offset) for _, size, advances, offset, _ in rows]))
cases = []
for paths, rows in curves:
    paths = tuple(tuple(tuple(float(v) for v in p) for p in line) for line in paths)
    rows = tuple((tuple(float(v) for v in widths), float(size), float(offset)) for widths, size, offset in rows)
    result = _place_rows(paths, rows)
    cases.append(dict(paths=paths, rows=[dict(advances=w, size=s, offset=o) for w, s, o in rows], origin=result[0] if result else None, glyphs=result[1] if result else None))
(fixtures/'path-0121-oracle.json').write_text(json.dumps(dict(cases=cases, projections=projection), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(f'Wrote {len(manual)} manual-DEM cases and {len(cases)} path-layout cases from Python source.')
