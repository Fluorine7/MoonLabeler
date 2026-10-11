# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional blind extreme-polar photographs; copyrighted inputs stay local.

Richard Rik Hill, WASP December 2020 p.21 (embedded original JPEG):
https://warrenastro.org/newsletter/WASP-2020-12.pdf
Tom Bash, LPOD Polar Dryness (original, not its labeled comparison):
https://www.astronet.ru/db/msg/1200115
Landmark tolerances come from the sources' separate labeled comparisons;
they are assertions only and never supplied as registration reference points.
"""
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QApplication

from moonlabeler.app import MainWindow

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'examples/auto-online-20261011-058'


@pytest.mark.parametrize('photo,utc,landmarks', [
    ('north-extracted-2.jpg', '2020-08-06T07:24:00Z',
     {'Anaxagoras': (395., 488., 55.), 'Meton': (970., 517., 75.)}),
    ('south-drygalski-original.jpg', '2004-10-08T09:46:00Z',
     {'Wilson': (75., 75., 25.), 'Casatus': (480., 90., 40.),
      'Drygalski': (350., 333., 65.)}),
])
def test_one_click_blind_extreme_polar_photo(monkeypatch, photo, utc, landmarks):
    if not (DATA / photo).exists() or not (ROOT / '.cache/ephemeris/de421.bsp').exists() or not (ROOT / '.cache/terrain/LDEM_16.IMG').exists():
        pytest.skip('Private polar photographs and cached reference data required')
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append

    def run_work(message, work, success, failure=None):
        try:
            result = work()
        except ValueError as exc:
            (failure or window.error)(str(exc))
        else:
            success(result)

    monkeypatch.setattr(window, 'run_background', run_work)
    window.open_image(str(DATA / photo))
    window.date.setDateTime(QDateTime.fromString(utc, Qt.DateFormat.ISODate))
    try:
        assert not window.manual_reference_points()
        window.identify_button.click()
        assert not errors, errors
        assert window.project.matrix is not None and window.annotation_items
        for name, (x, y, tolerance) in landmarks.items():
            item = next(item for item in window.annotation_items if item.feature['name'] == name)
            assert np.linalg.norm([item.anchor.x() - x, item.anchor.y() - y]) < tolerance
    finally:
        window.dirty = False
        window.close()
        window.deleteLater()
        application.processEvents()
