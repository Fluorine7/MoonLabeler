# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from datetime import datetime,timezone
import json
import os
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PIL import Image

from moonlabeler.geometry import Geometry
from moonlabeler.project import Project, export_svg
from moonlabeler.sources import read_image


@pytest.mark.parametrize('field,value', [
    ('style.font_percent', 'bad'), ('style.font_percent', float('nan')),
    ('style.font_step_percent', -.1), ('style.font_step_percent', float('inf')),
    ('style.font_step_percent', True),
    ('style.font_size', 0), ('style.max_labels', '200'),
    ('capture_mode', 'unknown'), ('capture_mode', None), ('capture_mode', []),
    ('style.max_labels', 0), ('style.min_diameter', -1),
    ('style.illuminated_only', 'false'), ('style.language', []),
    ('anchors', [{'id': '42', 'pixel': [1]}]),
    ('anchors', [{'id': '42', 'pixel': ['x', 2]}]),
    ('anchors', [{'id': '42', 'pixel': [1, 2], 'enabled': 'yes'}]),
    ('labels', {'42': {'position': [1, float('inf')]}}),
    ('labels', {'42': {'text': ['Name']}}),
    ('labels', {'42': {'hidden': 'false'}}),
    ('terrain.settings.width_km', 'bad'),
    ('crater_detection.min_radius', 'bad'),
    ('automatic_recognition.matched_names', [None]),
    ('terrain_rims', {'42': {'source': 'missing coordinates'}}),
    ('matrix', {'unexpected': 'mapping'}),
    ('matrix', [[True, 0, 0], [0, 1, 0]]),
])
def test_project_rejects_invalid_fields_before_gui_consumes_them(tmp_path, field, value):
    path = tmp_path/'invalid.moonlabel'
    Project(image_path=str(tmp_path/'photo.png')).save(path)
    data = json.loads(path.read_text())
    owner = data
    parts = field.split('.')
    for part in parts[:-1]:
        owner = owner[part]
    owner[parts[-1]] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='工程'):
        Project.load(path)


def test_legacy_project_preserves_unknown_ids_extensions_and_pixel_font(tmp_path):
    path = tmp_path/'legacy.moonlabel'
    project = Project(image_path=str(tmp_path/'photo.png'), font_size=80,
                      anchors=[{'id': 'catalogue-entry-no-longer-present', 'pixel': [12, 34]}],
                      labels={'unavailable': {'text': None, 'position': [-5, 8], 'future_option': 'keep'}},
                      terrain_settings={'center_id': None})
    project.save(path)
    data = json.loads(path.read_text())
    data['style'].pop('font_percent')
    data['style']['future_option'] = 'ignore'
    path.write_text(json.dumps(data))
    loaded = Project.load(path)
    loaded.update_font_size((100, 100, 3))
    assert loaded.font_size == 80
    assert loaded.anchors == project.anchors and loaded.labels == project.labels


def test_svg_render_preserves_spaces_in_edited_names(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    application = QApplication.instance() or QApplication([])
    widths = []
    for text in ('A B', 'A   B'):
        path = tmp_path/f'spaces-{len(text)}.svg'
        export_svg(path, np.zeros((200, 400, 3), np.uint8),
                   [({'id': '42', 'name': text}, [0, 0], [20, 60])],
                   Project(font_size=40), {'42': (0, 0, 0, 0)})
        renderer = QSvgRenderer(str(path))
        assert renderer.isValid()
        result = QImage(400, 200, QImage.Format.Format_RGB32)
        result.fill(0xff000000)
        painter = QPainter(result)
        renderer.render(painter, QRectF(0, 0, 400, 200))
        painter.end()
        pixels = np.asarray(result.constBits()).reshape(200, 400, 4)
        _, x = np.where(np.all(pixels[50:130, :, :3] > 220, axis=2))
        widths.append(x.max()-x.min()+1)
        text_node = ET.parse(path).find('.//{http://www.w3.org/2000/svg}text')
        assert text_node.text == text  # Names remain editable SVG text.
    assert widths[1] > widths[0]+10, 'SVG collapsed spaces which the PNG keeps'


def test_project_roundtrip_preserves_editing_and_site(tmp_path):
    image = tmp_path / "photo.png"
    Image.new("RGB",(800,600)).save(image)
    geometry = Geometry(np.array([1.,0,0]),np.array([0.,1,0]),np.array([0.,0,1]),
                        np.array([1.,0,0]),384400,"2026-01-01T00:00:00+00:00")
    project = Project(image_path=str(image),utc=geometry.utc,geometry=geometry,
                      matrix=np.array([[200.,0,400],[0,200.,300]]),latitude=31.2,longitude=121.5,
                      labels={"42":{"position":[100,120],"text":"地形 <A> & B","hidden":True}},
                      anchors=[{"id":"42", "pixel":[30, 40], "enabled":False}],
                      terrain_path=str(tmp_path/"terrain.lbl"), terrain_settings={"center_id":"42", "width_km":200}, optimize_layout=False,
                      crater_settings={"min_radius": 10, "max_radius": 120, "sensitivity": 70, "viewport": True})
    project.save(tmp_path / "photo.moonlabel")
    loaded = Project.load(tmp_path / "photo.moonlabel")
    assert loaded.labels == project.labels
    assert loaded.image_path == str(image)
    assert loaded.latitude == 31.2 and loaded.longitude == 121.5
    assert np.array_equal(loaded.matrix,project.matrix)
    assert loaded.anchors == project.anchors
    assert loaded.terrain_path == project.terrain_path
    assert loaded.terrain_settings == project.terrain_settings
    assert not loaded.optimize_layout
    assert loaded.crater_settings == project.crater_settings


def test_svg_embeds_image_and_keeps_editable_text(tmp_path):
    feature = {"id":"42", "name":"<A> & B", "name_zh":""}
    project = Project()
    path = tmp_path / "photo.svg"
    export_svg(path,np.zeros((200,300,3),np.uint8),[(feature,[70,80],[90,100])],project,
               {"42":(73,82,88,103)})
    root = ET.parse(path).getroot()
    ns = {"s":"http://www.w3.org/2000/svg"}
    assert root.find(".//s:text",ns).text == "<A> & B"
    assert root.find("s:image",ns).attrib["{http://www.w3.org/1999/xlink}href"].startswith("data:image/png;base64,")
    assert root.attrib["width"] == "300"
    assert root.find('.//s:path',ns).attrib['d'] == 'M 73.000,82.000 L 88.000,103.000'


def test_sixteen_bit_tiff_import_is_display_scaled(tmp_path):
    pixels = np.linspace(0,65535,300*200,dtype=np.uint16).reshape(200,300)
    path = tmp_path / "linear.tif"
    Image.fromarray(pixels).save(path)
    result = read_image(path)
    assert result.shape == (200,300,3) and result.dtype == np.uint8
    assert result.max() == 255 and result.min() == 0
