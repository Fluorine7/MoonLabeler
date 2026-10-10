# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from datetime import datetime,timezone
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from moonlabeler.geometry import Geometry
from moonlabeler.project import Project, export_svg
from moonlabeler.sources import read_image


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
