# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Default names and real colour conversion through the public export workflow."""
import base64
import io
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PIL import Image, ImageCms
from PySide6.QtGui import QColorSpace, QImage
from PySide6.QtWidgets import QApplication, QFileDialog

from moonlabeler.app import MainWindow
from moonlabeler.geometry import Geometry
from moonlabeler.project import Project, export_svg


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.error = lambda error: (_ for _ in ()).throw(AssertionError(str(error)))
    win.catalog = []
    win.project.geometry = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                                    np.array([1., 0, 0]), 384400., win.project.utc)
    win.project.matrix = np.array([[40., 0, 80.], [0, 40., 48.]])
    yield win
    win.dirty = False
    win.close()


@pytest.mark.parametrize('art_style', ['standard', 'manuscript', 'topographic'])
@pytest.mark.parametrize('landing', [False, True])
def test_pinned_caption_locators_match_native_png_and_svg_after_reopening(window, tmp_path, art_style, landing):
    from moonlabeler.app import Annotation
    from moonlabeler.annotation_style import caption_text
    win = window
    source = tmp_path/'moon.png'
    image = np.zeros((400, 640, 3), np.uint8)
    Image.fromarray(image).save(source)
    p = win.project
    p.image_path, p.art_style = str(source), art_style
    p.font_percent, p.font_step_percent = 6., 0.
    p.labels['test'] = {'position': [300., 200.]}
    p.crater_outlines = False
    project_path = tmp_path/'pinned.moonlabel'
    p.save(project_path)
    win.project = p = Project.load(project_path)
    win.set_image(image)
    feature = {'id': 'test', 'name': 'Test', 'kind': 'Landing Site' if landing else 'Crater, craters',
               'diameter': 0. if landing else 80., 'lat': 0., 'lon': 0.}
    label = Annotation(feature, [80., 48.], caption_text(p, feature), p, win.move_label, win.edit_label,
                       font_size=p.label_font_sizes([feature], image.shape)['test'])
    win.canvas.scene().addItem(label)
    win.canvas.scene().addItem(label.line)
    label.setPos(*p.labels['test']['position'])
    win.annotation_items = [label]
    expected = art_style == 'standard' or landing
    assert label.line.isVisible() == expected
    png, svg = tmp_path/'pinned.png', tmp_path/'pinned.svg'
    win.render_png(png)
    export_svg(svg, image, win.annotation_entries(), p, win.annotation_leaders())
    pixels = np.asarray(Image.open(png).convert('RGB'))
    assert bool(pixels[35:65, 65:95].any()) == expected, 'PNG must not acquire a dot/line just because a label was pinned'
    ns = {'s': 'http://www.w3.org/2000/svg'}
    group = ET.parse(svg).find('.//s:g[@id="feature-test"]', ns)
    assert bool(group.findall('s:path', ns)) == expected
    assert bool(group.findall('s:circle', ns)) == (expected and not landing)
    assert p.labels['test']['position'] == [300., 200.]


@pytest.mark.parametrize('method,suffix,extension', [('export_png', 'annotated', 'png'),
    ('export_vector', 'annotated', 'svg'), ('export_crater_candidates', 'crater-candidates', 'csv'),
    ('save_terrain_reference', 'dem-reference', 'png')])
def test_export_dialog_keeps_source_folder_and_unicode_stem(window, tmp_path, monkeypatch, method, suffix, extension):
    win = window
    win.project.image_path = str(tmp_path/'彩月 2026.10.23.TIF')
    win.set_image(np.full((96, 160, 3), 80, np.uint8))
    win.crater_candidates = [object()]
    win.terrain_reference = object()
    captured = []
    def save_dialog(parent, title, suggested, formats):
        captured.append(Path(suggested))
        return '', ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', save_dialog)
    getattr(win, method)()
    assert captured == [tmp_path/f'彩月 2026.10.23-{suffix}.{extension}']


@pytest.mark.parametrize('art_style', ['standard', 'manuscript', 'topographic'])
@pytest.mark.parametrize('profiled', [False, True])
def test_png_converts_wide_gamut_before_labels_and_embeds_srgb(window, tmp_path, art_style, profiled):
    win = window
    raw = np.zeros((96, 160, 3), np.uint8)
    raw[:, :40] = [190, 80, 80]
    raw[:, 40:80] = [70, 180, 100]
    raw[:, 80:120] = [100, 70, 180]
    raw[:, 120:] = [128, 128, 128]
    source = tmp_path/'彩月.tif'
    space = QColorSpace(QColorSpace.NamedColorSpace.DisplayP3)
    kwargs = {'icc_profile': bytes(space.iccProfile())} if profiled else {}
    Image.fromarray(raw).save(source, **kwargs)
    win.project.image_path = str(source)
    win.project.art_style = art_style
    win.set_image(raw)
    expected = raw
    if profiled:
        reference = QImage(raw.data, 160, 96, raw.strides[0], QImage.Format.Format_RGB888).copy()
        reference.setColorSpace(space)
        reference = reference.convertedToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        reference = reference.convertToFormat(QImage.Format.Format_RGB888)
        expected = np.asarray(reference.constBits()).reshape(96, reference.bytesPerLine())[:, :480].reshape(96, 160, 3).copy()
        assert not np.array_equal(expected, raw)
    if art_style != 'standard':
        expected = np.asarray(Image.fromarray(expected).convert('L').convert('RGB'))
    output = tmp_path/'converted.png'
    win.render_png(output)
    with Image.open(output) as photo:
        assert photo.info.get('icc_profile'), 'PNG must carry its sRGB colour profile'
        profile = ImageCms.ImageCmsProfile(io.BytesIO(photo.info['icc_profile']))
        assert 'srgb' in ImageCms.getProfileDescription(profile).lower()
        actual = np.asarray(photo.convert('RGB'))
        assert np.max(abs(actual.astype(int)-expected.astype(int))) <= 2
    assert win.image is raw and np.array_equal(raw[:, 0], [[190, 80, 80]]*96)
    with Image.open(source) as original:
        assert np.array_equal(np.asarray(original.convert('RGB')), raw)
        assert original.info.get('icc_profile') == kwargs.get('icc_profile')
    path = tmp_path/'converted.svg'
    export_svg(path, raw, [], win.project)
    base = ET.parse(path).find('.//{http://www.w3.org/2000/svg}image[@id="photograph"]')
    encoded = base.attrib['{http://www.w3.org/1999/xlink}href'].split(',', 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as background:
        assert background.info.get('icc_profile')
        assert np.max(abs(np.asarray(background).astype(int)-expected.astype(int))) <= 2


@pytest.mark.parametrize('kind', ['photo', 'project'])
def test_failed_colour_conversion_keeps_the_current_document(window, tmp_path, kind):
    win = window
    current = tmp_path/'current.png'
    raw = np.full((96, 160, 3), 80, np.uint8)
    Image.fromarray(raw).save(current)
    win.project.image_path = str(current)
    win.project_path = tmp_path/'current.moonlabel'
    win.set_image(raw)
    win.dirty = True
    previous = win.project
    title = win.canvas_title.text()
    win.render_png(tmp_path/'before.png')
    invalid = tmp_path/'broken-profile.png'
    Image.fromarray(raw+70).save(invalid, icc_profile=b'invalid ICC profile')
    errors = []
    win.error = errors.append
    win.confirm_discard = lambda: True
    if kind == 'photo':
        win.open_image(str(invalid))
    else:
        incoming = tmp_path/'incoming.moonlabel'
        Project(image_path=str(invalid), art_style='manuscript').save(incoming)
        win.open_project(str(incoming))
    assert errors and 'ICC' in str(errors[0])
    assert win.project is previous and win.image is raw
    assert win.project_path == tmp_path/'current.moonlabel'
    assert win.canvas_title.text() == title and win.dirty
    win.render_png(tmp_path/'after.png')
    assert np.array_equal(np.array(Image.open(tmp_path/'before.png')), np.array(Image.open(tmp_path/'after.png')))


def test_gui_saves_oriented_dimensions_and_reopens_without_recognition(window, tmp_path, monkeypatch):
    win = window
    source = tmp_path/'侧放的月面.tif'
    raw = np.arange(96*160*3, dtype=np.uint8).reshape(96, 160, 3)
    exif = Image.Exif()
    exif[274] = 6
    Image.fromarray(raw).save(source, exif=exif)
    win.confirm_discard = lambda: True
    win.open_image(str(source))
    assert win.project.image_size == (96, 160)  # EXIF rotation, not the stored raster size.
    g = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                 np.array([1., 0, 0]), 384400., win.project.utc)
    win.project.geometry = g
    win.project.matrix = np.array([[30., 0, 48.], [0, 30., 80.]])
    win.project.labels = {'42': {'text': '手工地名', 'position': [20., 30.]}}
    path = tmp_path/'侧放的月面.moonlabel'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    assert win.save_project()
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['image_size'] == [96, 160]
    assert data['coordinate_system']['pixel_axes'] == ['right', 'down']
    original_pixels = win.image.copy()
    original_geometry = win.project.geometry.to_dict()
    original_matrix = win.project.matrix.copy()
    monkeypatch.setattr(win, 'run_background', lambda *args, **kwargs: pytest.fail('Reopening must not launch recognition'))
    win.open_project(str(path))
    assert win.project.geometry.to_dict() == original_geometry
    np.testing.assert_array_equal(win.project.matrix, original_matrix)
    np.testing.assert_array_equal(win.image, original_pixels)
    assert win.project.labels['42'] == {'text': '手工地名', 'position': [20., 30.]}


def test_opening_config_with_resized_photo_keeps_the_current_document(window, tmp_path):
    win = window
    win.set_image(np.zeros((96, 160, 3), np.uint8))
    previous = win.project
    source = tmp_path/'改过尺寸.png'
    Image.new('RGB', (80, 48)).save(source)
    path = tmp_path/'原工程.moonlabel'
    Project(image_path=str(source), image_size=(160, 96)).save(path)
    errors = []
    win.error = errors.append
    win.confirm_discard = lambda: True
    win.open_project(str(path))
    assert len(errors) == 1 and '尺寸' in str(errors[0])
    assert win.project is previous and win.image.shape == (96, 160, 3)
