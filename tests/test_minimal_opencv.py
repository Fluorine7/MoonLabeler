# SPDX-License-Identifier: GPL-3.0-or-later
"""The application must use its private algorithm build, never a PyPI fallback."""
import json
from pathlib import Path
import re

import cv2
from moonlabeler._opencv import cv2 as private_cv2


def test_private_native_build_has_exact_algorithm_modules_and_no_codec_api():
    assert cv2 is private_cv2
    assert Path(cv2.__file__).parent.name == '_moonlabeler_opencv'
    modules = set(re.search(r'^\s*To be built:\s*(.+)$', cv2.getBuildInformation(), re.MULTILINE)[1].split())
    assert modules == {'core', 'imgproc', 'flann', 'features2d', 'calib3d', 'ximgproc', 'python3'}
    for name in ('imread', 'imdecode', 'imwrite', 'imencode', 'VideoCapture', 'VideoWriter', 'imshow'):
        assert not hasattr(cv2, name), name
    manifest = json.loads((Path(cv2.__file__).parent/'build-manifest.json').read_text(encoding='utf-8'))
    assert manifest['opencv_version'] == cv2.__version__
    assert manifest['codec_sources'] == []


def test_edge_drawing_is_present_with_its_real_native_implementation():
    import numpy as np
    image = np.full((360, 520), 72, np.uint8)
    cv2.ellipse(image, (350, 190), (60, 30), 35, 0, 360, 205, 3)
    detector = cv2.ximgproc.createEdgeDrawing()
    params = cv2.ximgproc_EdgeDrawing_Params()
    params.MinPathLength = 20
    params.NFAValidation = True
    detector.setParams(params)
    detector.detectEdges(image)
    ellipses = detector.detectEllipses()
    assert ellipses is not None
    assert any(np.hypot(row[0]-350, row[1]-190) < 3 for row in ellipses.reshape(-1, 6))
