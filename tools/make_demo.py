# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Generate an explicitly synthetic lunar geometry / editing fixture."""
from datetime import datetime, timezone
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from moonlabeler.geometry import compute_geometry
from moonlabeler.project import Project
from moonlabeler.sources import load_catalog
from moonlabeler.registration import transform_points

root = Path(__file__).resolve().parents[1]
utc = datetime(2026,9,26,12,0,tzinfo=timezone.utc)
geometry = compute_geometry(utc,root / ".cache/ephemeris")
catalog = load_catalog(root / ".cache")
w,h,cx,cy,radius = 1600,1450,800,700,570
yy,xx = np.mgrid[:h,:w]
dx,dy = (xx-cx)/radius,-(yy-cy)/radius
z = np.sqrt(np.clip(1-dx*dx-dy*dy,0,1))
normals = dx[...,None]*geometry.right + dy[...,None]*geometry.north + z[...,None]*geometry.observer
mu = np.maximum(normals @ geometry.sun,0)
rng = np.random.default_rng(22)
noise = cv2.GaussianBlur(rng.normal(0,1,(h,w)).astype(np.float32),(0,0),1.7)
gray = np.clip(60 + 110 * mu**.35 + 28*noise,0,255)
mask = dx*dx+dy*dy < 1
gray[~mask]=10
image = np.uint8(np.repeat(gray[...,None],3,axis=2))
matrix = np.array([[radius,0.,cx],[0.,radius,cy]])
points,visible,lit = geometry.project([f['lat'] for f in catalog],[f['lon'] for f in catalog])
pixels = transform_points(matrix,points)
for f,point,okay in sorted(zip(catalog,pixels,visible & lit),key=lambda row:row[0]['diameter'],reverse=True):
    if not okay or 'Crater' not in f['kind'] or f['diameter'] < 15:
        continue
    scale = radius*f['diameter']/3474.8
    x,y = np.rint(point).astype(int)
    if scale > 1:
        cv2.circle(image,(x,y),max(1,int(scale)),(115,115,115),-1,cv2.LINE_AA)
        cv2.circle(image,(x,y),max(1,int(scale)),(194,194,194),1,cv2.LINE_AA)
        if scale>5:
            cv2.circle(image,(x,y),max(1,int(scale/5)),(175,175,175),-1,cv2.LINE_AA)
picture = Image.fromarray(image)
draw = ImageDraw.Draw(picture)
font_candidates = ('/System/Library/Fonts/PingFang.ttc',
                   '/System/Library/Fonts/STHeiti Medium.ttc',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
font_path = next((path for path in font_candidates if Path(path).exists()), None)
font = ImageFont.truetype(font_path,26) if font_path else ImageFont.load_default(size=26)
draw.text((54,40),'MoonLabeler · 模拟验证图',fill='#f4cc83',font=font)
draw.text((54,78),'2026-09-26 12:00 UTC · 地形位置按 JPL 星历投影',fill='#8fa4bf',font=font)
draw.text((54,h-70),'此图为程序生成的测试数据，不是实拍照片。',fill='#8fa4bf',font=font)
image_path = root / 'examples/synthetic-moon.png'
picture.save(image_path)
project = Project(image_path=str(image_path),utc=utc.isoformat(),geometry=geometry,matrix=matrix,
                  min_diameter=80,max_labels=22,font_size=23,kind='Crater, craters')
for name in ('Copernicus','Tycho','Plato','Clavius'):
    f=next(f for f in catalog if f['name']==name)
    point,seen,_=geometry.project([f['lat']],[f['lon']])
    if seen[0]:
        project.anchors.append({'id':f['id'],'pixel':transform_points(matrix,point)[0].tolist()})
project.save(root / 'examples/demo.moonlabel')
print('Created synthetic editing / registration example')
