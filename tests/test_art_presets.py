# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable typography and reversible, display-only artistic presets."""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from moonlabeler import i18n
from moonlabeler.annotation_style import ART_PRESETS, appearance, caption_typography, photo_for_style
from moonlabeler.map_layers import ELEVATION_PALETTES, ElevationRaster, colorize_elevation, elevation_colors, legend_style
from moonlabeler.project import Project, export_svg, label_font_families


NEW_STYLES = ('cyanotype', 'copperplate', 'inkwash', 'redalert')


@pytest.mark.parametrize('style', NEW_STYLES[:3])
def test_palette_has_cool_warm_contrast_within_common_mare_heights(style):
    # The Copernicus photograph mostly occupies this narrow interval. A vivid
    # -9/+9 km ramp alone left the actual picture almost monochrome.
    low, high = elevation_colors(np.array([-1.7, -.3]), style).astype(float)
    assert np.linalg.norm(high-low) > 100
    assert low[2]-low[0] > 20 and high[0]-high[2] > 10


def test_inkwash_uses_cinnabar_for_landmarks_without_replacing_original_colour():
    p = Project(art_style='inkwash', color='#123456')
    large = {'id': 'large', 'name': 'Copernicus', 'kind': 'Crater', 'diameter': 95}
    small = {'id': 'small', 'name': 'Copernicus A', 'kind': 'Satellite Feature', 'diameter': 3}
    assert p.label_color(large) == '#a63f32'
    assert p.label_color(small) == appearance(p).text
    p.art_style = 'standard'
    assert p.label_color(large) == p.label_color(small) == '#123456'


def test_redalert_terrain_separates_grass_sand_and_rock_without_changing_heights():
    heights = np.full((100, 120), -2., np.float32)
    heights[:, 60:] = .5
    heights[:4, :4] = np.nan
    before = heights.copy()
    raster = ElevationRaster(heights, 'test', 1.)
    p = Project(art_style='redalert', elevation_palette='redalert', elevation_opacity=1.)
    dark = np.zeros((200, 240, 3), np.uint8)
    bright = np.full_like(dark, 255)
    rgba = colorize_elevation(raster, p, image=dark)
    assert np.array_equal(rgba, colorize_elevation(raster, p, image=bright)), 'Terrain shading must be independent of photographic shadows'
    grass, sand, wall = rgba[50, 30, :3].astype(int), rgba[50, 90, :3].astype(int), rgba[50, 60, :3].astype(int)
    assert grass[1] > grass[0]+20 and grass[1] > grass[2]+30
    assert sand[0] > sand[1]+10 and sand[1] > sand[2]+30
    assert wall.max() < sand.max()*.85, 'Steep walls need a visible rock face'
    assert np.array_equal(rgba[:, :, 3] > 0, np.isfinite(heights))
    assert np.array_equal(heights, before, equal_nan=True) and not dark.any() and (bright == 255).all()


@pytest.mark.parametrize('style', NEW_STYLES)
@pytest.mark.parametrize('traditional', [False, True])
def test_new_styles_offer_windows_fonts_for_both_chinese_scripts(style, traditional):
    language = '双语（繁体）' if traditional else '双语'
    fonts = label_font_families(language, 'win32', art_style=style)
    expected = ('Microsoft JhengHei' if traditional else 'Microsoft YaHei') if style in ('cyanotype', 'redalert') else ('PMingLiU' if traditional else 'SimSun')
    assert expected in fonts
    assert all(not name.startswith(('PingFang', 'Songti', 'Baskerville', 'Avenir')) for name in fonts)
    # CJK script selection also exists on the other supported desktop systems.
    assert label_font_families(language, 'darwin', art_style=style)
    assert label_font_families(language, 'linux', art_style=style)


@pytest.mark.parametrize('style', NEW_STYLES)
def test_new_style_projects_preserve_custom_labels_and_utf8(tmp_path, style):
    p = Project(art_style=style, elevation_palette=ART_PRESETS[style].palette,
                language='双语（繁体）', color='#123456', font_weight='bold',
                labels={'a': {'text': '自訂地名 · Tycho', 'position': [12.25, 37.5], 'hidden': False}})
    path = tmp_path/'繁體工程.moonlabel'
    p.save(path)
    loaded = Project.load(path)
    assert loaded.art_style == style and loaded.elevation_palette == p.elevation_palette
    assert loaded.labels == p.labels and loaded.color == p.color and loaded.font_weight == p.font_weight
    assert json.loads(path.read_text(encoding='utf-8'))['style']['art_style'] == style
    loaded.art_style = 'standard'
    assert loaded.label_text({'id': 'a', 'name': 'Tycho'}) == '自訂地名 · Tycho'
    assert appearance(loaded).text == '#123456' and appearance(loaded).weight == 'bold'


@pytest.mark.parametrize('style', NEW_STYLES)
def test_new_style_colour_and_type_hierarchy_leave_source_untouched(style):
    photo = np.full((80, 120, 3), [210, 92, 35], np.uint8)
    original = photo.copy()
    gray = photo_for_style(photo, style)
    assert np.array_equal(gray[:, :, 0], gray[:, :, 1]) and np.array_equal(photo, original)
    p = Project(art_style=style, elevation_palette=ART_PRESETS[style].palette, elevation_opacity=.8)
    heights = np.tile(np.linspace(-9, 9, 60), (40, 1)).astype(np.float32)
    heights[0, 0] = np.nan
    before = heights.copy()
    raster = ElevationRaster(heights, 'test', 1.)
    rgba = colorize_elevation(raster, p, image=photo)
    assert rgba[0, 0, 3] == 0 and np.all(rgba[1:, :, 3] == 204)
    assert not np.array_equal(rgba[20, 0, :3], rgba[20, -1, :3])
    assert np.array_equal(before, heights, equal_nan=True) and np.array_equal(photo, original)
    assert p.elevation_palette in ELEVATION_PALETTES
    assert caption_typography(p, {'kind': 'Mare'}).scale > caption_typography(p, {'kind': 'Satellite Feature'}).scale
    assert appearance(p).map_style and appearance(p).text != appearance(p, landing=True).text
    assert legend_style(p).foreground != legend_style(p).background


@pytest.mark.parametrize('style', NEW_STYLES)
def test_new_style_svg_has_readable_editable_ink_on_light_and_dark_photos(tmp_path, style):
    app = QApplication.instance() or QApplication([])
    p = Project(art_style=style, font_size=32, font_percent=None)
    expected = appearance(p).text.lstrip('#')
    ink = np.array([int(expected[i:i+2], 16) for i in (0, 2, 4)])
    for background in (0, 240):
        path = tmp_path/f'{style}-{background}.svg'
        export_svg(path, np.full((200, 480, 3), background, np.uint8),
                   [({'id': 'a', 'name': 'Tycho', 'kind': 'Crater'}, [0, 0], [20, 25])], p)
        source = path.read_text(encoding='utf-8')
        assert '<text ' in source and ('Tycho' in source or 'TYCHO' in source)
        image = QImage(480, 200, QImage.Format.Format_RGBA8888)
        image.fill(0)
        painter = QPainter(image)
        renderer = QSvgRenderer(str(path))
        assert renderer.isValid()
        renderer.render(painter)
        painter.end()
        pixels = np.asarray(image.constBits()).reshape(200, 480, 4)[:, :, :3].astype(int)
        assert np.count_nonzero(np.max(abs(pixels-ink), axis=2) < 18) > 100


def test_new_style_names_are_translated_in_all_interface_languages():
    previous = i18n._language, i18n._explicit
    expected = {
        'zh-CN': ('蓝晒星图', '铜版图录', '水墨朱砂', '红警地形图'),
        'zh-TW': ('藍曬星圖', '銅版圖錄', '水墨硃砂', '紅警地形圖'),
        'en': ('Cyanotype chart', 'Copperplate atlas', 'Ink and cinnabar', 'Red Alert terrain'),
    }
    try:
        for language, titles in expected.items():
            i18n.set_language(language)
            assert tuple(i18n.tr(ART_PRESETS[style].title) for style in NEW_STYLES) == titles
    finally:
        i18n._language, i18n._explicit = previous
