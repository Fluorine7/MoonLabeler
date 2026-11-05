#!/usr/bin/env python3
"""Development-only reference from the real Python Annotation / Qt scene."""
import json
import math
import os
from pathlib import Path
import sys
import argparse
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene
from moonlabeler.app import Annotation
from moonlabeler.project import Project

app = QApplication([])
project = Project(font_size=24, color='#f5f5f2')
feature = dict(id='decoration-fixture', name='Fixture', kind='Crater, craters', diameter=60, lat=0, lon=0)
rim = [(170+120*math.cos(i*math.tau/128), 220+50*math.sin(i*math.tau/128)) for i in range(129)]

def annotation(text, anchor, position, outline=(), size=24):
    item = Annotation(feature, anchor, text, project, lambda *a: None, lambda *a: None, font_size=size)
    item.set_crater_outline(outline)
    item.setPos(*position)
    return item

def render(reverse):
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, 360, 480)
    items = [annotation('XXXXXX', (50, 200), (100, 160)),
             annotation('Crater', (170, 220), (20, 30), [rim])]
    for item in reversed(items) if reverse else items:
        scene.addItem(item.line)
        scene.addItem(item)
    image = QImage(360, 480, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#282828'))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    scene.render(painter, QRectF(0, 0, 360, 480), scene.sceneRect())
    painter.end()
    return bytes(image.constBits())

normal, reversed_order = render(False), render(True)
changed = sum(max(abs(normal[i+j]-reversed_order[i+j]) for j in range(3)) > 3
              for i in range(0, len(normal), 4))
assert changed == 0, f'Python reference unexpectedly depends on annotation insertion order: {changed}'
square = [(80, 80), (120, 80), (120, 120), (80, 120), (80, 80)]
item = annotation('Crater', (100, 100), (0, 0), [square], size=14)
bounds = item.boundingRect()
item.setPos(150-bounds.x(), 100-bounds.center().y())
line = item.line.line()
oracle = dict(caption_z=item.zValue(), locator_z=item.line.zValue(), order_changed_pixels=changed,
              rim_leader=[line.x1(), line.y1(), line.x2(), line.y2()])
assert oracle['rim_leader'] == [120.0, 100.0, 150.0, 100.0]
locators = {}
for name, shape, art, landing, dragging, exporting in [
    ('plain', False, False, False, False, False),
    ('shape', True, False, False, False, False),
    ('dragged_shape', True, False, False, True, False),
    ('exported_dragged_shape', True, False, False, True, True),
    ('art_plain', False, True, False, False, False),
    ('art_landing', False, True, True, False, False),
]:
    probe_feature = dict(feature, kind='Landing Site' if landing else 'Crater, craters')
    probe = Annotation(probe_feature, (60, 120), 'AB', project, lambda *a: None, lambda *a: None)
    probe.typography = replace(probe.typography, glyphs=(('A', 0, 18, 10), ('B', 14, 20, 10)) if shape else ())
    probe.appearance = replace(probe.appearance, map_style=art)
    probe._drag_offset = (0, 0) if dragging else None
    probe._export_mode = exporting
    probe.update_map_leader()
    locators[name] = probe.line.isVisible()
oracle['locators'] = locators
target = ROOT/'swift/Tests/MoonEditorTests/Fixtures/decoration-python-oracle.json'
payload = json.dumps(oracle, indent=2)+'\n'
if not target.exists() or target.read_text(encoding='utf-8') != payload:
    target.write_text(payload, encoding='utf-8')
print(json.dumps(oracle))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--render-native', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
if args.render_native:
    from PySide6.QtGui import QPixmap
    from PIL import Image
    from moonlabeler.sources import load_catalog
    from moonlabeler.photo_overview import build_overview
    from moonlabeler.ui.photo_overview import PhotoOverview
    native = json.loads(args.render_native.read_text(encoding='utf-8'))
    output = args.output or args.render_native.parent/'python-reference'
    output.mkdir(parents=True, exist_ok=True)
    photo = (args.render_native.parent/native['imagePath']).resolve()
    legacy = dict(native['projectState']['legacy'])
    legacy.update(format='MoonLabeler', version=2, image_path=str(photo),
                  matrix=native['calibration']['matrix'], geometry=native['calibration']['geometry'],
                  style=native['projectState']['style']['values'])
    compatible = output/'reference.moonlabel'
    compatible.write_text(json.dumps(legacy, ensure_ascii=False), encoding='utf-8')
    reference = Project.load(compatible)
    reference.image_size = (native['imageWidth'], native['imageHeight'])
    width, height = reference.image_size
    rgb = Image.open(photo).convert('RGB')
    image = QImage(rgb.tobytes(), width, height, width*3, QImage.Format.Format_RGB888).copy()
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, width, height)
    scene.addPixmap(QPixmap.fromImage(image))
    catalog = {f['id']: f for f in load_catalog(ROOT/'.cache')}
    # A rendered snapshot can also contain illumination-filtered labels.
    # Compare the same visible annotation set, not a second selection policy.
    import xml.etree.ElementTree as ET
    svg = args.render_native.with_suffix('.svg')
    visible_ids = None
    if svg.exists():
        visible_ids = {node.get('id')[8:] for node in ET.parse(svg).iter()
                       if (node.get('id') or '').startswith('locator-')}
    leaders = []
    items = []
    for saved in native['annotations']:
        if saved['hidden'] or saved.get('visual', {}).get('layoutHidden', False):
            continue
        if visible_ids is not None and saved['id'] not in visible_ids:
            continue
        feature = catalog.get(saved.get('featureID'))
        if feature is None:
            continue
        visual = saved.get('visual', {})
        anchor, pos = saved['anchor'], saved['position']
        size = native['settings']['fontSize']*visual.get('fontScale', 1)
        item = Annotation(feature, (anchor['x'], anchor['y']), saved['text'], reference,
                          lambda *a: None, lambda *a: None, font_size=round(size))
        item.set_crater_outline([[(p['x'], p['y']) for p in line] for line in visual.get('outline', [])])
        item.setPos(pos['x'], pos['y'])
        item.set_export_mode(True)
        scene.addItem(item.line)
        scene.addItem(item)
        line = item.line.line()
        leaders.append(dict(id=saved['id'], feature=feature['id'], text=saved['text'],
                            visible=item.line.isVisible(), points=[line.x1(), line.y1(), line.x2(), line.y2()]))
        items.append(item)
    if reference.overview_enabled:
        model = build_overview(reference, (height, width, 3))
        overview = PhotoOverview((height, width, 3), reference, model)
        overview.set_export_mode(True)
        scene.addItem(overview)
    target_image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    target_image.fill(QColor('#282828'))
    painter = QPainter(target_image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    scene.render(painter, QRectF(0, 0, width, height), scene.sceneRect())
    painter.end()
    assert target_image.save(str(output/'python.png'))
    (output/'leaders.json').write_text(json.dumps(leaders, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Python Qt reference: {len(items)} annotations, {output}')
