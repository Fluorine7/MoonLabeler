# SPDX-License-Identifier: GPL-3.0-or-later
"""Real landform data, viewing geometry, edits and matching native/SVG output."""
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtGui import QImage, QPainter, QTextLayout
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from moonlabeler._opencv import cv2
from moonlabeler import feature_paths
from moonlabeler.annotation_style import ART_STYLES, caption_text, path_caption_typography, path_caption_rows, caption_font
from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry, geometry_from_nasa
from moonlabeler.project import Project, export_svg


ROOT = Path(__file__).parents[1]
CATALOG = {f['id']: f for f in json.loads((ROOT/'moonlabeler/data/catalog.json').read_text(encoding='utf-8'))['features']}


def closeup(fid='5067', *, scale=4500., **options):
    g = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                 np.array([1., 0, 0]), 384400., '2025-05-03T11:36:15+00:00')
    f = CATALOG[fid]
    center = g.project([f['lat']], [f['lon']])[0][0]
    matrix = np.column_stack((np.eye(2)*scale, np.array([600., 500.])-center*scale))
    return Project(geometry=g, matrix=matrix, image_size=(1200, 1000), font_percent=None,
                   font_size=24, font_step_percent=0, language='英文', illuminated_only=False,
                   optimize_layout=False, crater_outlines=False, **options)


def test_small_offline_layer_retains_true_lines_and_area_axes_without_rectangular_extents():
    layer = feature_paths._landforms()
    assert (ROOT/'moonlabeler/data/feature_paths.json').stat().st_size < 250_000
    assert layer['5067']['method'] == 'source_line'
    assert layer['4004']['method'] == 'area_cross_sections'
    assert '5040' not in layer  # Rima Ariadaeus has only a rectangular extent.
    assert '1296' not in layer  # Crater circles are already handled separately.
    assert set(layer).issubset(CATALOG)
    hadley = np.concatenate(layer['5064']['paths'])
    assert hadley[:, 1].min() == pytest.approx(24.53264, abs=.00001)
    assert hadley[:, 1].max() == pytest.approx(26.70234, abs=.00001)


@pytest.mark.parametrize('fid,scale', [('5067', 4500.), ('4004', 1600.), ('4011', 2400.)])
def test_real_rille_and_mountain_names_have_baselines_that_follow_the_landform(fid, scale):
    p = closeup(fid, scale=scale)
    f = CATALOG[fid]
    text = caption_text(p, f)
    typography = path_caption_typography(p, f, text, 24)
    assert typography.origin is not None and ''.join(g[0] for g in typography.glyphs) == text
    assert abs(np.mean([g[3] for g in typography.glyphs])) > 1
    assert np.ptp([g[3] for g in typography.glyphs]) <= 55
    assert not typography.arc  # These are source-specific paths, not preset arcs.


def test_brayley_bilingual_path_keeps_shaped_text_and_chinese_on_its_own_row():
    application = QApplication.instance() or QApplication([])
    p = closeup('5045', scale=4000.)
    p.language = '双语'
    feature = dict(CATALOG['5045'], name_zh='布雷利月溪')
    typography = path_caption_typography(p, feature, caption_text(p, feature), 24)
    assert typography.glyphs
    units = [glyph[0] for glyph in typography.glyphs]
    assert ''.join(units) == '布雷利月溪Rima Brayley'
    assert '·' not in units, 'Separate language rows do not need a middle-dot separator'
    assert max(getattr(typography, 'glyph_scales', (1.,))) > min(getattr(typography, 'glyph_scales', (1.,)))
    assert np.ptp([glyph[3] for glyph in typography.glyphs]) <= 55


def test_path_clusters_and_advances_match_complete_qt_shaping_with_kerning_and_combining_marks():
    application = QApplication.instance() or QApplication([])
    p = closeup(art_style='manuscript')
    feature = CATALOG['5067']
    text = 'AV fi A\u0308rcus'
    units, size, widths, _, _ = path_caption_rows(p, feature, text, 30)[0]
    layout = QTextLayout(text, caption_font(size, p, feature))
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(1e6)
    layout.endLayout()
    positions = {}
    for run in layout.glyphRuns(0, -1, QTextLayout.GlyphRunRetrievalFlag.RetrieveAll):
        for index, point in zip(run.stringIndexes(), run.positions()):
            positions[index] = min(positions.get(index, point.x()), point.x())
    assert ''.join(units) == text
    # Qt's font backends may keep A + diaeresis and following letters in one
    # cluster (Windows). Require intact graphemes, not identical segmentation.
    boundary = 0
    for unit in units:
        boundary += len(unit.encode('utf-16-le'))//2
        assert layout.isValidCursorPosition(boundary)
    assert len(units) == len(positions)
    assert np.cumsum([0., *widths[:-1]]) == pytest.approx([positions[i] for i in sorted(positions)], abs=.001)
    assert sum(widths) == pytest.approx(line.horizontalAdvance(), abs=.001)


def test_parallel_language_rows_keep_natural_spacing_on_the_inner_and_outer_bend():
    angle = np.linspace(-.7, .7, 281)
    path = tuple(map(tuple, np.column_stack((240*np.sin(angle), 240*(1-np.cos(angle))))))
    placed = feature_paths._place_rows((path,), (((15.,)*10, 20., -30.), ((15.,)*10, 20., 30.)))
    assert placed is not None
    _, glyphs = placed
    for row in (glyphs[:10], glyphs[10:]):
        points = np.asarray([[g[0], g[1]] for g in row])
        assert np.linalg.norm(np.diff(points, axis=0), axis=1) == pytest.approx(np.full(9, 15.), abs=.5)


def test_path_smoothing_keeps_a_broad_s_bend_but_removes_digitization_ripples():
    x = np.linspace(-160., 160., 321)
    y = 25*np.sin(x/80)+1.2*np.sin(x*1.5)
    source = (tuple(map(tuple, np.column_stack((x, y)))),)
    placed = feature_paths._place(source, (26.,)*8, 0., 24.)
    assert placed is not None
    _, glyphs = placed
    angles = np.array([g[2] for g in glyphs])
    assert np.ptp(angles) > 6, 'The broad S-shaped route must not become a straight label'
    assert np.max(np.abs(np.diff(angles))) < 12, 'Tiny source ripples must not shake individual letters'


def test_brayley_retains_a_visible_bend_instead_of_falling_back_at_normal_photo_scale():
    application = QApplication.instance() or QApplication([])
    p = closeup('5045', scale=3200.)
    p.language = '双语'
    feature = dict(CATALOG['5045'], name_zh='布雷利月溪')
    typography = path_caption_typography(p, feature, caption_text(p, feature), 30)
    assert typography.glyphs, 'A readable curved route must not silently become an ordinary label'
    assert np.ptp([glyph[3] for glyph in typography.glyphs]) > 8


def test_disabled_and_ordinary_crater_labels_do_not_load_the_path_layer(monkeypatch):
    def unexpected():
        pytest.fail('Ordinary labels must not load the optional path layer')
    monkeypatch.setattr(feature_paths, '_landforms', unexpected)
    p = closeup(follow_feature_paths=False)
    assert not path_caption_typography(p, CATALOG['5067'], 'Rima Hyginus', 24).glyphs
    p.follow_feature_paths = True
    assert not path_caption_typography(p, CATALOG['1296'], 'Copernicus', 24).glyphs
    assert p.label_font_sizes([CATALOG['1296']], (1000, 1200, 3))['1296'] == 24


def test_projection_cache_tracks_libration_rotation_reflection_and_lens_distortion():
    from datetime import datetime, timezone
    p, f = closeup(), CATALOG['5067']
    original = feature_paths.projected_paths(p, f)
    assert feature_paths.projected_paths(p, f) is original
    p.geometry = geometry_from_nasa({'subearth': {'lat': 2., 'lon': 1.},
                                     'subsolar': {'lat': 0., 'lon': 0.},
                                     'distance': 384400., 'posangle': 0.}, datetime(2025, 5, 3, tzinfo=timezone.utc))
    assert feature_paths.projected_paths(p, f) != original
    p = closeup()
    p.matrix[:, 0] *= -1
    p.matrix[0, 2] += 2*600-2*p.matrix[0, 2]
    mirrored = feature_paths.projected_paths(p, f)
    assert mirrored and mirrored != original
    p = closeup()
    p.identification['lens_distortion'] = {'center': [600., 500.], 'scale': 600., 'k': .3}
    assert feature_paths.projected_paths(p, f) != original


@pytest.mark.parametrize('camera', ['plain', 'rotated', 'mirrored', 'distorted'])
def test_baseline_endpoints_use_the_same_physical_projection_as_catalogue_points(camera):
    p, f = closeup(), CATALOG['5067']
    if camera == 'rotated':
        angle = .7
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        p.matrix[:, :2] = rotation @ p.matrix[:, :2]
        p.matrix[:, 2] = rotation @ (p.matrix[:, 2]-[600., 500.])+[600., 500.]
    elif camera == 'mirrored':
        p.matrix[0] *= -1
        p.matrix[0, 2] += 1200
    elif camera == 'distorted':
        p.identification['lens_distortion'] = {'center': [600., 500.], 'scale': 600., 'k': .3}
    coordinates = np.asarray(feature_paths._landforms()['5067']['paths'][0])[[0, -1]]
    projected = p.geometry.project(coordinates[:, 1], coordinates[:, 0])[0]
    expected = p.photo_points(projected)
    actual = np.asarray(feature_paths.projected_paths(p, f)[0])[[0, -1]]
    assert np.allclose(actual, expected if expected[0, 0] <= expected[1, 0] else expected[::-1])


def test_preparation_rejects_scaled_coordinates_and_preserves_special_geometry():
    from tools.prepare_feature_paths import build
    source = {'meta': {'fetched_utc': '2026-11-03T00:00:00+00:00'}, 'classifications': [
        {'features': [
            {'feature_id': '5040', 'feature': 'Rima Ariadaeus', 'type': 'Rima, rimae', 'diameter': '247',
             'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[17.3, 5.1], [9.4, 5.1], [9.4, 8.1], [17.3, 8.1], [17.3, 5.1]]]]}},
            {'feature_id': '5067', 'feature': 'Rima Hyginus', 'type': 'Rima, rimae', 'diameter': '204',
             'geometry': {'type': 'MultiLineString', 'coordinates': [[[4.55, 9.95], [6.77, 7.6]], [[6.77, 7.6], [9.85, 6.34]]]}}
        ]}]}
    result = build(source)['features']
    assert set(result) == {'5067'} and len(result['5067']['paths']) == 2
    assert result['5067']['paths'][0][0] == [4.55, 9.95]
    source['meta']['radius_correction'] = {'factor': .272704}
    with pytest.raises(ValueError, match='unscaled'):
        build(source)


def test_missing_tiny_and_sharply_turning_paths_fall_back_without_inventing_routes():
    for fid in ('5040', '3970'):
        p = closeup(fid)
        assert not path_caption_typography(p, CATALOG[fid], caption_text(p, CATALOG[fid]), 24).glyphs
    p = closeup(scale=20.)
    assert not path_caption_typography(p, CATALOG['5067'], 'Rima Hyginus', 24).glyphs
    hairpin = (((0., 0.), (120., 0.), (0., 1.)),)
    assert feature_paths._place(hairpin, (20.,)*10, 0., 24.) is None


@pytest.mark.parametrize('style', ART_STYLES)
@pytest.mark.parametrize('language', ['英文', '双语'])
def test_native_png_svg_opacity_and_drag_share_the_same_landform_glyphs(tmp_path, style, language):
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win.project = closeup(art_style=style)
        win.project.language = language
        feature = dict(CATALOG['5067'], name_zh='许吉努斯月溪')
        win.catalog = [feature]
        win.set_image(np.full((1000, 1200, 3), 50, np.uint8))
        win.sync_controls()
        label, = win.annotation_items
        assert label.typography.glyphs and not label.line.isVisible()
        assert 'position' not in win.project.labels.get('5067', {})
        assert tuple(label.pos().toTuple()) == pytest.approx(label.preferred_position)
        before, revision = label.path, label._text_revision
        win.label_opacity.setValue(42)
        assert label.opacity() == .42 and label.path == before and label._text_revision == revision
        png, svg = tmp_path/'curved.png', tmp_path/'curved.svg'
        win.render_png(png)
        export_svg(svg, win.image, win.annotation_entries(), win.project, win.annotation_leaders())
        root = ET.parse(svg)
        ns = {'s': 'http://www.w3.org/2000/svg'}
        group = root.find('.//s:g[@id="label-text-0"]', ns)
        text = caption_text(win.project, feature)
        assert group.attrib['aria-label'] == text
        assert ''.join(group.itertext()) == text.replace(' · ', '')
        assert [node.text for node in group.findall('.//s:text', ns)] == [glyph[0] for glyph in label.typography.glyphs]
        assert not root.findall('.//s:circle', ns)
        native = QImage(str(png)).convertToFormat(QImage.Format.Format_RGB32)
        rendered = QImage(1200, 1000, QImage.Format.Format_RGB32)
        rendered.fill(0xff323232)
        painter = QPainter(rendered)
        QSvgRenderer(str(svg)).render(painter)
        painter.end()
        def ink(image):
            pixels = np.asarray(image.constBits()).reshape(1000, 1200, 4)[:, :, :3].astype(float)
            return np.max(np.abs(pixels-50), axis=2) > 12
        first, second = ink(native), ink(rendered)
        assert first.sum() > 100 and second.sum() > 100
        for expected, actual in ((first, second), (second, first)):
            nearby = cv2.dilate(actual.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            assert (expected & nearby).sum()/expected.sum() > .98
        label.setPos(label.pos().x()+10, label.pos().y()+15)
        pin = list(label.pos().toTuple())
        assert win.project.labels['5067']['position'] == pin
        win.refresh_annotations()
        label, = win.annotation_items
        assert list(label.pos().toTuple()) == pin and label.typography.glyphs
    finally:
        win.dirty = False
        win.close()


def test_setting_is_staged_persisted_and_old_projects_preserve_their_layout(tmp_path):
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        assert win.project.follow_feature_paths and win.follow_feature_paths.isChecked()
        win.follow_feature_paths.setChecked(False)
        assert win.project.follow_feature_paths and win.style_pending
        win.apply_label_settings()
        assert not win.project.follow_feature_paths
    finally:
        win.dirty = False
        win.close()
    path = tmp_path/'paths.moonlabel'
    closeup().save(path)
    assert Project.load(path).follow_feature_paths
    data = json.loads(path.read_text(encoding='utf-8'))
    del data['style']['follow_feature_paths']
    path.write_text(json.dumps(data), encoding='utf-8')
    assert not Project.load(path).follow_feature_paths
    for invalid in (1, 'true', None):
        data['style']['follow_feature_paths'] = invalid
        path.write_text(json.dumps(data), encoding='utf-8')
        with pytest.raises(ValueError, match='follow_feature_paths'):
            Project.load(path)
