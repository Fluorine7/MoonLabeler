# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtCore import QDateTime
from PySide6.QtTest import QTest
import pytest


def test_photo_workflow_has_automatic_name_recognition():
    from PySide6.QtWidgets import QPushButton
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    buttons = [button for button in window.findChildren(QPushButton)
               if button.text() == '自动识别并标注']
    window.dirty = False
    window.close()
    assert buttons, '照片流程缺少自动地名识别入口，用户仍需逐个输入地名。'


def test_capture_time_defaults_collapsed_and_preserves_explicit_time(tmp_path):
    from datetime import timezone
    from PySide6.QtCore import QDate, QTime
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.date.displayFormat() == 'yyyy-MM-dd'
        assert not window.capture_time_toggle.isChecked()
        assert window.capture_time_block.isHidden()
        assert (window.utc().hour, window.utc().minute, window.utc().second) == (15, 0, 0)
        window.date.setDate(QDate(2025, 9, 14))
        assert window.utc().isoformat() == '2025-09-14T15:00:00+00:00'
        assert window.utc().tzinfo == timezone.utc
        # Existing calibrated projects retain their recorded time on loading.
        window.project.utc = '2025-09-13T12:34:56+00:00'
        window.sync_controls()
        assert window.utc().isoformat() == '2025-09-13T12:34:56+00:00'
        assert window.capture_time.time() == QTime(12, 34, 56)
        assert '12:34:56' in window.capture_time_toggle.text()
        # Calendar changes retain precise times; only the explicit reset resets.
        window.date.setDate(QDate(2025, 9, 15))
        assert window.utc().isoformat() == '2025-09-15T12:34:56+00:00'
        window.capture_time_toggle.click()
        assert not window.capture_time_block.isHidden()
        window.capture_time.setTime(QTime(23, 59, 42))
        assert window.utc().isoformat() == '2025-09-15T23:59:42+00:00'
        assert window.project.utc == window.utc().isoformat()
        window.capture_time_toggle.click()
        assert window.capture_time_block.isHidden()
        assert window.utc().hour == 23
        saved = tmp_path / 'time.moonlabel'
        window.project.save(saved)
        assert Project.load(saved).utc == '2025-09-15T23:59:42+00:00'
        window.reset_capture_time.click()
        assert window.utc().isoformat() == '2025-09-15T15:00:00+00:00'
        assert window.capture_time.time() == QTime(15, 0)
    finally:
        window.dirty = False
        window.close()


def test_time_edit_invalidates_registration_but_folding_does_not():
    from PySide6.QtCore import QTime
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.open_example()
        matrix = window.project.matrix.copy()
        utc = window.project.utc
        window.capture_time_toggle.click()
        window.capture_time_toggle.click()
        assert np.array_equal(window.project.matrix, matrix)
        assert window.project.utc == utc and not window.dirty
        window.capture_time.setTime(QTime(9, 25, 17))
        assert window.project.utc.endswith('T09:25:17+00:00')
        assert window.project.geometry is None and window.project.matrix is None
        assert window.dirty
    finally:
        window.dirty = False
        window.close()


def test_one_click_recognizes_real_north_polar_limb_photo(monkeypatch, tmp_path):
    import pytest
    source = Path(__file__).parents[1]
    photo = source/'250914.jpg'
    if not photo.exists() or not (source/'.cache/ephemeris/de421.bsp').exists() or not (source/'.cache/terrain/LDEM_16.IMG').exists():
        pytest.skip('Local polar photograph, JPL and DEM caches required')
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    # Execute the same UI worker without event-loop timing or supplied names.
    def run_work(message, work, success, failure=None):
        try:
            result = work()
        except ValueError as exc:
            (failure or window.error)(str(exc))
        else:
            success(result)
    monkeypatch.setattr(window, 'run_background', run_work)
    window.open_image(str(photo))
    window.date.setDateTime(QDateTime.fromString('2025-09-14T15:05:59Z', Qt.DateFormat.ISODate))
    try:
        window.identify_button.click()
        assert not errors, errors
        assert window.project.matrix is not None
        assert window.project.identification['method'].startswith('LOLA')
        assert window.project.identification['image_inliers'] >= 24
        refinement = window.project.identification['refinement']
        assert refinement['validation_after_px'] < refinement['validation_before_px']*.85
        assert len(refinement['validation_folds']) >= 4
        assert '图像微调' in window.geometry_status.text()
        # Broad independent region checks, NOT a precise crater-rim test.
        # User-observed outline offsets remain a documented limitation.
        for name, bounds in {'Archytas': (2190, 2370, 1770, 1950),
                             'Timaeus': (1550, 1750, 1370, 1570),
                             'Epigenes': (1250, 1480, 1030, 1210)}.items():
            item = next(item for item in window.annotation_items if item.feature['name'] == name)
            left, right, top, bottom = bounds
            assert left < item.anchor.x() < right and top < item.anchor.y() < bottom
        assert '参考轮廓' in window.identification_status.toolTip()
        saved = tmp_path/'refined.moonlabel'
        window.project.save(saved)
        restored = Project.load(saved)
        assert restored.identification['refinement'] == refinement
        assert restored.geometry.to_dict() == window.project.geometry.to_dict()
    finally:
        window.dirty = False
        window.close()


def test_one_click_recognizes_real_south_polar_limb_photo(monkeypatch):
    source = Path(__file__).parents[1]
    photo = source/'250914-2.jpg'
    if not photo.exists() or not (source/'.cache/ephemeris/de421.bsp').exists() or not (source/'.cache/terrain/LDEM_16.IMG').exists():
        pytest.skip('Local polar photograph and JPL cache required')
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
    window.open_image(str(photo))
    window.date.setDateTime(QDateTime.fromString('2025-09-14T15:22:06Z', Qt.DateFormat.ISODate))
    try:
        window.identify_button.click()
        assert not errors, errors
        assert window.project.matrix is not None and window.annotation_items
        assert window.project.identification['method'].startswith('LOLA')
        assert window.project.identification['image_inliers'] >= 24
        # Exact-time input is now retained. The 15:22 reference and its refined
        # view both need to pass validation, rather than assuming the old
        # date-only UI's 15:00 reference and its rejection result.
        refinement = window.project.identification['refinement']
        assert refinement['validation_after_px'] < refinement['validation_before_px']*.85
        assert len(refinement['validation_folds']) >= 4
        assert refinement['light_before_after'][1] >= .6
        assert refinement['detail_before_after'][1] >= refinement['detail_before_after'][0]+.02
        # Independently inspected large formations, never supplied to search.
        for name, bounds in {'Moretus': (950, 1170, 1900, 2170),
                             'Short': (820, 1110, 1330, 1640),
                             'Newton': (1400, 1720, 1050, 1330)}.items():
            item = next(item for item in window.annotation_items if item.feature['name'] == name)
            left, right, top, bottom = bounds
            assert left < item.anchor.x() < right and top < item.anchor.y() < bottom
    finally:
        window.dirty = False
        window.close()


def test_one_click_recognizes_real_crescent_with_few_crater_candidates(monkeypatch):
    source = Path(__file__).parents[1]
    photo = source/'0817.png'
    if not photo.exists() or not (source/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local crescent photograph and JPL cache required')
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
    window.open_image(str(photo))
    window.date.setDateTime(QDateTime.fromString('2026-08-17T15:05:59Z', Qt.DateFormat.ISODate))
    try:
        window.identify_button.click()
        assert not errors, errors
        assert window.project.matrix is not None and window.annotation_items
        main = next(item for item in window.annotation_items if item.feature['name'] == 'Mare Crisium')
        # Broad independently inspected mare-center box, never search input.
        assert 2650 < main.anchor.x() < 3020 and 1090 < main.anchor.y() < 1370
        assert window.project.font_percent == 1.5
    finally:
        window.dirty = False
        window.close()

from moonlabeler.app import MainWindow
from moonlabeler.project import Project, export_svg


def test_one_click_identifies_real_partial_photo_and_preserves_fit_on_failure(tmp_path, monkeypatch):
    import pytest
    import time
    from moonlabeler.craters import DetectionResult
    source = Path(__file__).parents[1]
    photograph = source/'微信图片_20261010155838_607_840.jpg'
    if not photograph.exists() or not (source/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local user photograph and JPL cache required')
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    window.open_image(str(photograph))
    window.date.setDateTime(QDateTime.fromString('2026-09-23T15:00:00Z',Qt.DateFormat.ISODate))
    assert not window.project.anchors and window.project.geometry is None
    # Click the real UI action: no supplied names, region, scale or mirror.
    window.identify_button.click()
    for _ in range(300):
        if not window.busy:
            break
        application.processEvents()
        time.sleep(.05)
    assert not window.busy and not errors
    names = set(window.project.identification['matched_names'])
    assert {'Aristarchus','Krieger','Wollaston','Nielsen'} <= names
    assert len(window.project.anchors) >= 7
    assert all(a['source']=='automatic' for a in window.project.anchors)
    assert window.workspace_tabs.currentIndex() == 1
    # The photo's own caption independently identifies the Aristarchus region.
    # A manually inspected broad center box is not supplied to the algorithm.
    main = next(item for item in window.annotation_items if item.feature['name']=='Aristarchus')
    assert 1280 < main.anchor.x() < 1370 and 1090 < main.anchor.y() < 1180
    window.render_png(tmp_path/'real-annotated.png')
    assert Image.open(tmp_path/'real-annotated.png').size == (2363,1833)
    saved = tmp_path/'real.moonlabel'
    window.project.save(saved)
    assert Project.load(saved).identification == window.project.identification
    original_matrix = window.project.matrix.copy()
    original_anchors = list(window.project.anchors)
    original_labels = dict(window.project.labels)
    monkeypatch.setattr('moonlabeler.app.detect_crater_rims',lambda image: DetectionResult([],(0,0,2363,1833),1.))
    def reject_terrain(*args, **kwargs):
        raise ValueError('测试模拟高程匹配失败')
    monkeypatch.setattr('moonlabeler.app.identify_from_terrain', reject_terrain)
    window.identify_button.click()
    for _ in range(100):
        if not window.busy:
            break
        application.processEvents()
        time.sleep(.02)
    assert errors and '不足七处' in errors[0]
    assert np.array_equal(window.project.matrix,original_matrix)
    assert window.project.anchors == original_anchors and window.project.labels == original_labels
    window.dirty = False
    window.close()


def test_gui_edit_save_filter_and_export(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors=[]
    window.error=errors.append
    path=Path(__file__).parents[1]/'examples/demo.moonlabel'
    assert path.exists()
    window.open_project(str(path))
    window.show()
    application.processEvents()
    assert not errors
    viewport = window.canvas.viewport().size()
    scene = window.canvas.sceneRect()
    fitted_scale = min(viewport.width()/scene.width(), viewport.height()/scene.height())
    assert 0.9*fitted_scale < window.canvas.transform().m11() <= fitted_scale
    assert window.utc().isoformat() == '2026-09-26T12:00:00+00:00'
    assert len(window.annotation_items)>5
    automatic = [item.boundingRect().translated(item.pos()) for item in window.annotation_items]
    for i, rect in enumerate(automatic):
        assert not any(rect.intersects(other) for other in automatic[i+1:])
    original=window.annotation_items[0]
    fid=original.feature['id']
    original.setPos(122,234)
    assert window.project.labels[fid]['position']==[122,234]
    window.project.labels[fid]['text']='测试名称 <A> & B'
    window.refresh_annotations()
    first=window.names.item(0)
    first.setCheckState(Qt.CheckState.Unchecked)
    assert window.project.labels[fid]['hidden']
    assert fid not in [item.feature['id'] for item in window.annotation_items]
    saved=tmp_path/'edited.moonlabel'
    window.project.save(saved)
    restored=Project.load(saved)
    assert restored.labels==window.project.labels
    assert len(window.reference_items)>0
    window.render_png(tmp_path/'annotated.png')
    assert Image.open(tmp_path/'annotated.png').size == (1600,1450)
    # Anchor guides must not leak into exported pixels.
    assert all(item.isVisible() for item in window.reference_items)
    export_svg(tmp_path/'annotated.svg',window.image,window.annotation_entries(),window.project,window.annotation_leaders())
    assert (tmp_path/'annotated.svg').stat().st_size>10000
    window.date.setDateTime(window.date.dateTime().addSecs(3600))
    assert window.project.matrix is None and window.project.geometry is None
    assert not window.annotation_items
    window.dirty=False
    window.close()


def test_manual_registration_of_partial_lunar_image_without_nasa(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from moonlabeler.geometry import compute_geometry
    from moonlabeler.registration import transform_points

    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    source = Path(__file__).parents[1]
    geometry = compute_geometry(datetime(2026,9,23,15,tzinfo=timezone.utc), source/'.cache/ephemeris')
    # Known coordinates -> a high magnification, reflected crop, no lunar limb.
    features = [next(f for f in window.catalog if f['name']==name)
                for name in ('Aristarchus','Herodotus','Väisälä')]
    points, visible, _ = geometry.project([f['lat'] for f in features],[f['lon'] for f in features])
    assert visible.all()
    center = points[0]
    matrix = np.array([[-20000.,0.,1000+20000*center[0]],
                       [0.,20000.,750-20000*center[1]]])
    pixels = transform_points(matrix,points)
    assert (pixels>0).all() and (pixels[:,0]<2200).all() and (pixels[:,1]<1700).all()
    image_path = tmp_path/'partial.png'
    Image.new('RGB',(2200,1700),(40,40,40)).save(image_path)
    window.open_image(str(image_path))
    window.project.geometry=geometry
    window.project.utc=geometry.utc
    window.sync_controls()
    def no_download(*args, **kwargs):
        raise AssertionError('Manual partial registration must remain offline')
    monkeypatch.setattr('moonlabeler.sources.download',no_download)
    for feature,pixel in zip(features,pixels):
        window.picking_id=feature['id']
        window.add_anchor(*pixel)
    window.solve_manual()
    assert not errors
    assert np.allclose(window.project.matrix,matrix,atol=1e-6)
    assert window.registration_tabs.currentIndex()==0
    assert window.workspace_tabs.currentIndex()==1
    assert '镜像' in window.registration_status.text()
    # Failed NASA operation must not invalidate already valid registration.
    before=window.project.matrix.copy()
    window.nasa_failed('HTTPS 握手超时')
    assert np.array_equal(window.project.matrix,before)
    assert len(window.project.anchors)==3
    window.search_features('Vaisala')
    ids=[window.feature_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(window.feature_list.count())]
    assert features[-1]['id'] in ids
    window.dirty=False
    window.close()


def test_multi_point_error_review_disable_and_repick(tmp_path):
    from moonlabeler.registration import transform_points
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    window.open_example()
    geometry = window.project.geometry
    names = ('Copernicus', 'Kepler', 'Aristarchus', 'Herodotus', 'Plato', 'Archimedes')
    features = [next(f for f in window.catalog if f['name'] == name) for name in names]
    points, visible, _ = geometry.project([f['lat'] for f in features], [f['lon'] for f in features])
    assert visible.all()
    truth = np.array([[-500., 30, 800], [30, 500., 725]])
    pixels = transform_points(truth, points)
    pixels[2] += [35, -50]
    window.project.anchors = [{'id':f['id'], 'pixel':xy.tolist()} for f, xy in zip(features, pixels)]
    window.solve_manual()
    assert not errors
    assert 'Aristarchus' in window.registration_status.text()
    assert window.calibration.suspect_index == 2
    assert float(window.anchor_table.item(2, 2).text()) > 5
    assert '留出' in window.anchor_table.item(2, 2).toolTip()
    window.anchor_table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not window.project.anchors[2]['enabled']
    assert window.project.matrix is None
    window.solve_manual()
    assert np.allclose(window.project.matrix, truth)
    assert window.anchor_table.item(2, 2).text() == '—'
    window.repick_anchor(2)
    assert window.canvas.picking and window.picking_id == features[2]['id']
    window.add_anchor(*transform_points(truth, points[2:3])[0])
    assert len(window.project.anchors) == 6 and window.project.anchors[-1]['enabled']
    window.solve_manual()
    assert np.allclose(window.project.matrix, truth)
    saved = tmp_path/'reviewed.moonlabel'
    window.project.save(saved)
    assert Project.load(saved).anchors == window.project.anchors
    window.dirty = False
    window.close()


def test_terrain_preview_save_reference_and_invalidate_without_photo(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from moonlabeler.terrain import ElevationMap, render_region
    from moonlabeler.geometry import Geometry
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    geometry = Geometry(np.array([1.,0,0]),np.array([0.,1,0]),np.array([0.,0,1]),
                        np.array([.8,.6,0]),384400,window.utc().isoformat())
    dem = ElevationMap(np.zeros((512,512)),2,-2,128)
    reference = render_region(dem,geometry,0,0,80,128,shadows=False)
    window.accept_terrain_reference((reference,geometry,geometry.utc,None,None))
    application.processEvents()
    assert window.terrain_dialog.isVisible()
    path=tmp_path/'reference.png'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args: (str(path),'PNG'))
    window.save_terrain_reference()
    saved=Project.load(path.with_suffix('.moonlabel'))
    assert Image.open(path).size == (128,128)
    assert np.array_equal(saved.matrix,reference.matrix)
    assert saved.geometry.utc == geometry.utc
    window.date.setDateTime(window.date.dateTime().addSecs(3600))
    assert window.project.geometry is None and window.terrain_reference is None
    assert window.terrain_dialog is None
    window.dirty=False
    window.close()


def test_dem_match_rejects_disagreement_and_preserves_calibration():
    from moonlabeler.registration import MatchResult
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors=[]
    window.error=errors.append
    window.open_example()
    matrix=window.project.matrix.copy()
    shifted=matrix.copy()
    shifted[:,2]+=[100,100]
    match=MatchResult(shifted,30,40,1.,.3,False)
    assert len(window.project.anchors)>=3
    window.accept_terrain_match((match,window.project.geometry,shifted))
    assert errors and '不一致' in errors[0]
    assert np.array_equal(window.project.matrix,matrix)
    window.dirty=False
    window.close()


def test_crater_review_worker_selection_anchor_and_clean_exports(tmp_path, monkeypatch):
    import cv2
    import time
    from PySide6.QtWidgets import QFileDialog
    from moonlabeler.geometry import Geometry

    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    image = np.full((360, 520, 3), 72, np.uint8)
    cv2.circle(image, (110, 140), 35, (215, 215, 215), 3)
    cv2.ellipse(image, (350, 190), (60, 30), 35, 0, 360, (205, 205, 205), 3)
    photo = tmp_path/'photo.png'
    Image.fromarray(image).save(photo)
    window.open_image(str(photo))
    window.show()
    window.registration_tabs.setCurrentWidget(window.crater_tab)
    application.processEvents()
    # Date remains reachable for the automatic naming action on this page.
    assert window.geometry_group.isVisible()
    assert not window.crater_settings_block.isVisible()
    window.crater_settings_toggle.click()
    assert window.crater_settings_block.isVisible()
    window.crater_min.setValue(15)
    window.crater_max.setValue(80)
    window.crater_settings_toggle.click()
    window.crater_button.click()
    deadline = time.monotonic()+10
    while window.busy and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not window.busy and not errors
    assert window.crater_list.count() >= 2
    assert window.project.geometry is None and not window.project.anchors
    # Actual canvas click selects the corresponding list row.
    target = window.crater_items[1]
    location = window.canvas.mapFromScene(target.pos())
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=location)
    assert window.crater_list.currentRow() == 1
    assert target.active
    window.crater_repick.click()
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.canvas.mapFromScene(345, 185))
    assert not window.canvas.picking
    assert window.crater_candidates[1].support is None
    assert np.hypot(window.crater_candidates[1].x-345, window.crater_candidates[1].y-185) < 2
    window.crater_search.setText('Aristarchus')
    assert window.crater_anchor_button.isEnabled()
    candidate = window.crater_candidates[1]
    window.crater_anchor_button.click()
    anchor = window.project.anchors[0]
    assert anchor['id'] == '380'
    assert np.allclose(anchor['pixel'], [candidate.x, candidate.y])
    assert window.project.matrix is None
    saved = tmp_path/'review.moonlabel'
    window.project.save(saved)
    assert Project.load(saved).anchors == window.project.anchors
    csv_path = tmp_path/'candidates.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(csv_path), 'CSV'))
    window.crater_export.click()
    assert 'center_x_px' in csv_path.read_text(encoding='utf-8-sig')
    # Keep a calibration so PNG export is allowed, and prove temporary review
    # overlays do not leak into exported pixels or get unhidden on another page.
    window.project.geometry = Geometry(np.array([1.,0,0]), np.array([0.,1,0]), np.array([0.,0,1]),
                                       np.array([1.,0,0]), 384400., window.project.utc)
    window.project.matrix = np.array([[250.,0.,260.],[0.,250.,180.]])
    window.project.min_diameter = 3000
    window.refresh_annotations()
    window.render_png(tmp_path/'clean.png')
    assert np.array_equal(np.asarray(Image.open(tmp_path/'clean.png').convert('RGB')), image)
    assert all(item.isVisible() for item in window.crater_items)
    window.workspace_tabs.setCurrentIndex(1)
    window.render_png(tmp_path/'clean-hidden.png')
    assert not any(item.isVisible() for item in window.crater_items)
    window.workspace_tabs.setCurrentIndex(0)
    window.crater_list.setCurrentRow(1)
    window.crater_remove.click()
    assert window.project.anchors == [anchor]
    window.dirty = False
    window.open_image(str(photo))
    assert not window.crater_candidates and not window.crater_items
    window.dirty = False
    window.close()


def test_one_click_recognizes_low_contrast_whole_moon(tmp_path):
    """Actual failure: faint rims and watermark must not prevent atlas matching."""
    import pytest
    import time
    source = Path(__file__).parents[1]
    photo = source/'微信图片_2026-10-10_180604_191.jpg'
    if not photo.exists() or not (source/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Local user photograph and JPL cache required')
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    window.open_image(str(photo))
    window.date.setDateTime(QDateTime.fromString('2026-09-25T10:05:35Z', Qt.DateFormat.ISODate))
    window.identify_button.click()
    for _ in range(600):
        application.processEvents()
        if not window.busy:
            break
        time.sleep(.05)
    try:
        assert not window.busy and not errors
        assert window.project.matrix is not None
        assert window.project.identification['image_inliers'] >= 50
        assert window.project.identification['coverage'] > .25
        # Independently visible complete limb: center and radius in broad boxes.
        linear = window.project.matrix[:, :2]
        assert 1180 < window.project.matrix[0, 2] < 1230
        assert 815 < window.project.matrix[1, 2] < 865
        assert 760 < np.linalg.norm(linear[:, 0]) < 805
        assert len(window.annotation_items) >= 10
        assert {'Tycho', 'Copernicus'} <= {item.feature['name'] for item in window.annotation_items}
        window.render_png(tmp_path/'whole-moon.png')
        assert Image.open(tmp_path/'whole-moon.png').size == (2426, 1656)
    finally:
        window.dirty = False
        window.close()


def test_one_click_recognizes_partial_photo_with_satellite_crater_chain(tmp_path):
    import pytest
    import time
    source = Path(__file__).parents[1]
    photo = source/'微信图片_2026-10-10_180754_011.png'
    if not photo.exists() or not (source/'.cache/ephemeris/de421.bsp').exists() or not (source/'.cache/terrain/LDEM_16.IMG').exists():
        pytest.skip('Local user photograph, JPL and DEM caches required')
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    window.open_image(str(photo))
    window.date.setDateTime(QDateTime.fromString('2026-10-04T15:05:35Z', Qt.DateFormat.ISODate))
    assert not window.project.anchors and window.project.geometry is None
    # Processing other images used to change the randomized index and outcome.
    import cv2
    cv2.setRNGSeed(8137)
    window.identify_button.click()
    for _ in range(2400):
        application.processEvents()
        if not window.busy:
            break
        time.sleep(.05)
    try:
        assert not window.busy and not errors
        names = set(window.project.identification['matched_names'])
        assert {'Rutherfurd', 'Clavius D', 'Clavius C', 'Clavius G', 'Clavius E'} <= names
        assert len(window.project.anchors) >= 7
        assert all(anchor['source'] == 'automatic' for anchor in window.project.anchors)
        # Independently inspected prominent crater and curved chain, not input.
        main = next(item for item in window.annotation_items if item.feature['name'] == 'Rutherfurd')
        assert 1580 < main.anchor.x() < 1690 and 840 < main.anchor.y() < 950
        refinement = window.project.identification['refinement']
        assert refinement['camera_alignment']['points'] >= 40
        assert refinement['validation_after_px'] < refinement['validation_before_px']*.85
        assert len(refinement['validation_folds']) >= 4
        assert refinement['light_before_after'][1] >= .6
        assert refinement['detail_before_after'][1] >= .25
        clavius = next(f for f in window.catalog if f['name'] == 'Clavius')
        assert clavius['id'] in window.project.terrain_rims
        assert len(window.project.crater_outline(clavius, window.image.shape)[0]) == 129
        small = next(f for f in window.catalog if f['name'] == 'Blancanus D')
        assert not window.project.crater_outline(small, window.image.shape)
        saved = tmp_path/'partial.moonlabel'
        window.project.save(saved)
        assert Project.load(saved).terrain_rims == window.project.terrain_rims
        window.render_png(tmp_path/'partial-moon.png')
        assert Image.open(tmp_path/'partial-moon.png').size == (2628,2256)
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('manual', [False, True])
def test_new_recognition_replaces_old_detections_but_respects_manual_anchors(manual):
    from moonlabeler.identification import IdentificationResult
    from moonlabeler.craters import DetectionResult
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    try:
        window.open_example()
        geometry, old_matrix = window.project.geometry, window.project.matrix.copy()
        features = window.project.visible_features(window.catalog, window.image.shape)[:3]
        window.project.anchors = [dict(id=f['id'], pixel=xy.tolist(), enabled=True,
                                      **({} if manual else {'source': 'automatic'})) for f, xy in features]
        new_matrix = old_matrix.copy()
        new_matrix[:, 2] += [40., 0.]
        result = IdentificationResult(new_matrix, [], 1., 10., 0, image_inliers=24, coverage=.4)
        window.accept_identification((DetectionResult([], (0, 0, 1200, 1200), 1.), result, geometry, None, None))
        if manual:
            assert errors and np.array_equal(window.project.matrix, old_matrix)
            assert len(window.project.anchors) == 3
        else:
            assert not errors and np.array_equal(window.project.matrix, new_matrix)
            assert not window.project.anchors
    finally:
        window.dirty = False
        window.close()


def test_candidate_outline_toggle_is_independent_of_exported_crater_style():
    from PySide6.QtWidgets import QCheckBox
    from moonlabeler.craters import CraterCandidate, DetectionResult
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.open_example()
        window.workspace_tabs.setCurrentIndex(0)
        window.registration_tabs.setCurrentWidget(window.crater_tab)
        window.accept_crater_candidates(DetectionResult([
            CraterCandidate(100., 120., 25., 20., 0., .8, 'edge-drawing'),
            CraterCandidate(180., 200., 20., 15., 0., .8, 'edge-drawing'),
        ], (0, 0, 1600, 1450), 1.))
        review = next(c for c in window.findChildren(QCheckBox) if c.text() == '显示全部候选轮廓')
        review.setChecked(False)
        window.show_crater_overlays()
        assert not window.crater_items[1].outline
        review.setChecked(True)
        assert window.crater_items[1].outline
        assert not window.style_pending
        window.crater_outlines.setChecked(False)
        assert window.style_pending and window.project.crater_outlines
        window.apply_label_settings()
        assert not window.project.crater_outlines
        assert review.isChecked() and window.crater_items[1].outline
        window.sync_controls()
        assert not window.crater_outlines.isChecked() and review.isChecked()
    finally:
        window.dirty = False
        window.close()
