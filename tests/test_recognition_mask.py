# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Shared exclusions: real detectors, gesture editing, persistence and exports."""
import json
import os
from copy import deepcopy
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider

from moonlabeler._opencv import cv2
from moonlabeler.craters import detect_craters, detect_crater_rims
from moonlabeler.project import Project
from moonlabeler.recognition_mask import PhotoMask
from moonlabeler.registration import prepare_registration_photo, auto_register


def rectangle(x0, y0, x1, y1):
    return {'kind': 'polygon', 'points': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def brush(points, radius):
    return {'kind': 'paint', 'points': points, 'radius': radius}


def circles():
    image = np.full((360, 520), 72, np.uint8)
    cv2.circle(image, (130, 180), 35, 215, 3)
    cv2.circle(image, (390, 180), 35, 215, 3)
    return image


def test_union_eraser_order_cached_resolutions_and_crop_coordinates():
    ops = [rectangle(40, 20, 120, 140), rectangle(80, 40, 170, 160),
           {'kind': 'erase', 'points': [[90, 60], [120, 90]], 'radius': 12}]
    mask = PhotoMask(ops, (200, 400))
    assert not mask._rasters
    pixels = mask.raster((200, 400))
    assert pixels[45, 90] == 0  # overlaps are excluded, not even-odd holes
    assert pixels[75, 105] == 255 and pixels[180, 200] == 255
    assert mask.raster((200, 400)) is pixels
    assert not pixels.flags.writeable
    ops[0]['points'][0][0] = 300  # caller changes cannot mutate a running search
    small = mask.raster((100, 200))
    assert small[22, 45] == 0 and small[37, 52] == 255
    crop = mask.cropped((60, 40), (100, 160))
    assert crop is mask.cropped((60, 40), (100, 160))
    assert crop.raster((100, 160))[5, 30] == 0
    assert crop.raster((100, 160))[35, 45] == 255
    later = PhotoMask([*ops[1:], rectangle(95, 65, 115, 85)], (200, 400))
    assert later.raster((200, 400))[75, 105] == 0


def test_brush_strokes_have_round_caps_connected_segments_and_ordered_eraser():
    mask = PhotoMask([brush([[30, 40], [130, 40]], 12),
                      {'kind': 'erase', 'points': [[70, 40]], 'radius': 8},
                      brush([[110, 90]], 10)], (120, 160))
    pixels = mask.raster((120, 160))
    assert pixels[40, 20] == pixels[40, 140] == pixels[50, 50] == 0
    assert pixels[40, 70] == pixels[54, 50] == 255
    assert pixels[90, 110] == 0 and pixels[75, 110] == 255
    assert mask.cropped((10, 20), (80, 140)).raster((80, 140))[20, 20] == 0
    assert mask.raster((60, 80))[20, 35] == 255


@pytest.mark.parametrize('detect', [detect_craters, detect_crater_rims])
def test_crater_detection_excludes_selected_rim_without_mutating_photo(detect):
    image = circles()
    original = image.copy()
    mask = PhotoMask([rectangle(80, 120, 180, 240)], image.shape)
    result = detect(image, photo_mask=mask)
    assert len(result.candidates) == 1
    assert np.hypot(result.candidates[0].x-390, result.candidates[0].y-180) < 5
    assert np.array_equal(image, original)
    if detect is detect_craters:
        assert not detect(image, region=(50, 80, 200, 210), photo_mask=mask).candidates
        from moonlabeler.craters import DetectionOptions
        smaller = detect(image, DetectionOptions(max_dimension=300), (270, 80, 240, 220), photo_mask=mask)
        assert any(np.hypot(c.x-390, c.y-180) < 5 for c in smaller.candidates)


def test_partial_exclusion_cannot_leave_an_accepted_crater_crossing_the_mask():
    image = circles()
    mask = PhotoMask([rectangle(150, 140, 180, 220)], image.shape)
    assert not any(c.x < 250 for c in detect_craters(image, photo_mask=mask).candidates)


def test_masked_feature_matching_uses_unexcluded_texture_and_original_coordinates():
    image = np.random.default_rng(31).integers(0, 256, (400, 600), dtype=np.uint8)
    mask = PhotoMask([rectangle(0, 0, 220, 400)], image.shape)
    prepared = prepare_registration_photo(image, photo_mask=mask)
    assert len(prepared.keypoints) > 12
    assert all(point.pt[0] > 220 for point in prepared.keypoints)
    match = auto_register(image, image, photo_mask=mask, prepared_photo=prepared)
    assert np.allclose(match.matrix, [[1, 0, 0], [0, 1, 0]], atol=.1)
    assert (match.target_points[:, 0] > 220).all()
    with pytest.raises(ValueError, match='不一致'):
        auto_register(image, image, prepared_photo=prepared)
    full = PhotoMask([rectangle(0, 0, 600, 400)], image.shape)
    with pytest.raises(ValueError, match='照片细节不足'):
        prepare_registration_photo(image, photo_mask=full)


def test_disabled_path_does_not_rasterize_or_copy_a_mask(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unmasked searches must not build mask images')
    monkeypatch.setattr(PhotoMask, 'raster', forbidden)
    assert len(detect_craters(circles()).candidates) == 2
    image = np.random.default_rng(4).integers(0, 256, (300, 400), dtype=np.uint8)
    prepared = prepare_registration_photo(image)
    assert prepared.image is image and prepared.photo_mask is None


def test_masked_dense_verification_ignores_excluded_corruption():
    from moonlabeler.terrain_identification import terrain_agreement
    reference = np.random.default_rng(15).integers(20, 230, (300, 500), dtype=np.uint8)
    photo = reference.copy()
    photo[:, :200] = 255-photo[:, :200]
    identity = np.array([[1., 0, 0], [0, 1., 0]])
    before = terrain_agreement(reference, photo, identity, require_match=False)
    mask = PhotoMask([rectangle(0, 0, 205, 300)], photo.shape)
    after = terrain_agreement(reference, photo, identity, photo_mask=mask)
    assert after[0] > .99 and after[1] > .99 and after[0] > before[0]+.3


def test_masking_a_limb_arc_does_not_create_a_false_straight_boundary():
    from moonlabeler.limb import fit_lunar_limb
    image = np.zeros((400, 520), np.uint8)
    cv2.circle(image, (260, 200), 160, 160, -1)
    mask = PhotoMask([rectangle(0, 0, 180, 400)], image.shape)
    center, radius, _, _ = fit_lunar_limb(image, photo_mask=mask)
    assert np.linalg.norm(center-[260, 200]) < 2 and abs(radius-160) < 2
    with pytest.raises(ValueError, match='弧度不足'):
        fit_lunar_limb(image, photo_mask=PhotoMask([rectangle(0, 0, 520, 400)], image.shape))


def photo_with_masked_inset(brightness=100):
    photo = np.zeros((700, 900), np.uint8)
    cv2.circle(photo, (220, 350), 190, brightness, -1)
    cv2.rectangle(photo, (500, 30), (890, 680), 255, -1)
    mask = PhotoMask([brush([[700, 200], [700, 500]], 280)], photo.shape)
    return photo, mask


@pytest.mark.parametrize('brightness', [10, 100])
def test_excluded_bright_inset_cannot_select_the_limb_or_set_its_threshold(brightness):
    from moonlabeler.limb import fit_lunar_limb
    photo, mask = photo_with_masked_inset(brightness)
    center, radius, _, _ = fit_lunar_limb(photo, photo_mask=mask)
    assert np.linalg.norm(center-[220, 350]) < 2 and abs(radius-190) < 2


@pytest.mark.parametrize('detect', [detect_craters, detect_crater_rims])
def test_excluded_large_inset_cannot_replace_the_search_surface(detect):
    photo, mask = photo_with_masked_inset()
    cv2.circle(photo, (220, 350), 35, 215, 3)
    candidates = detect(photo, photo_mask=mask).candidates
    assert any(np.hypot(c.x-220, c.y-350) < 5 and c.major < 50 for c in candidates)


def test_excluded_inset_cannot_replace_dense_terrain_verification_domain():
    from moonlabeler.terrain_identification import terrain_agreement
    photo, mask = photo_with_masked_inset()
    disk = (photo == 100)
    photo[disk] = np.random.default_rng(18).integers(30, 200, disk.sum(), dtype=np.uint8)
    reference = photo.copy()
    reference[:, 500:] = 0
    light, detail = terrain_agreement(reference, photo, np.array([[1., 0, 0], [0, 1., 0]]), photo_mask=mask)
    assert light > .99 and detail > .99


def test_excluded_inset_cannot_replace_eyepiece_limb_validation():
    from moonlabeler.eyepiece import _limb_check
    from moonlabeler.geometry import Geometry
    photo, mask = photo_with_masked_inset(40)
    geometry = Geometry(np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]),
                        np.array([1., 0., 0.]), 384400., '2023-05-27T11:51:00+00:00')
    _, error, arc = _limb_check(photo, geometry, np.array([1., 0, 0, 0, 0, 0, 0, 0, 0]),
                                np.array([220., 350.]), 190., 1, photo_mask=mask)
    assert error < 2 and arc >= 120


@pytest.mark.parametrize('center_x', [20, 25, 30])
def test_unrelated_exclusion_keeps_valid_partial_craters_at_the_photo_edge(center_x):
    photo = np.full((360, 520), 72, np.uint8)
    cv2.circle(photo, (center_x, 180), 35, 215, 3)
    candidates = detect_crater_rims(photo).candidates
    assert any(np.hypot(c.x-center_x, c.y-180) < 3 for c in candidates)
    mask = PhotoMask([brush([[480, 20]], 10)], photo.shape)
    assert detect_crater_rims(photo, photo_mask=mask).candidates == candidates
    # A paint stroke over the visible rim must still exclude this candidate.
    blocked = PhotoMask([brush([[center_x+35, 180]], 10)], photo.shape)
    assert not detect_crater_rims(photo, photo_mask=blocked).candidates


def test_project_roundtrip_and_legacy_default_keep_mask_separate_from_annotations(tmp_path):
    project = Project(image_path=str(tmp_path/'photo.png'), image_size=(520, 360))
    project.labels = {'example': {'text': 'User label', 'position': [20, 30], 'hidden': False}}
    project.anchors = [{'id': 'example', 'pixel': [130, 180], 'enabled': True}]
    project.matrix = np.array([[2., 0, 10], [0, 2., 20]])
    project.recognition_mask = {'enabled': False, 'operations': [rectangle(50, 50, 200, 200),
                               brush([[250, 90], [330, 170]], 24),
                               {'kind': 'erase', 'points': [[100, 100]], 'radius': 20}]}
    path = tmp_path/'test.moonlabel'
    project.save(path)
    loaded = Project.load(path)
    assert loaded.recognition_mask == project.recognition_mask
    assert loaded.labels == project.labels and loaded.anchors == project.anchors
    assert np.array_equal(loaded.matrix, project.matrix)
    data = json.loads(path.read_text(encoding='utf-8'))
    data.pop('recognition_mask')
    path.write_text(json.dumps(data), encoding='utf-8')
    assert Project.load(path).recognition_mask == {'enabled': True, 'operations': []}


@pytest.mark.parametrize('state', [
    {'enabled': 'yes', 'operations': []},
    {'enabled': True, 'operations': [{'kind': 'polygon', 'points': [[1, 2]]}]},
    {'enabled': True, 'operations': [{'kind': 'erase', 'points': [[float('nan'), 3]], 'radius': 20}]},
    {'enabled': True, 'operations': [{'kind': 'erase', 'points': [[10, 20]], 'radius': -1}]},
    {'enabled': True, 'operations': [{'kind': 'paint', 'points': [[10, 20]], 'radius': 0}]},
    {'enabled': True, 'operations': [rectangle(0, 0, 800, 800)]},
])
def test_invalid_persisted_masks_are_rejected(tmp_path, state):
    path = tmp_path/'bad.moonlabel'
    project = Project(image_size=(520, 360))
    project.save(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['recognition_mask'] = state
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='recognition_mask'):
        Project.load(path)


@pytest.fixture
def window():
    from moonlabeler.app import MainWindow
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.set_image(np.repeat(circles()[..., None], 3, axis=2))
    win.show()
    win.fit_canvas()
    application.processEvents()
    yield win
    win.dirty = False
    win.close()


def gesture(window, points):
    target = window.canvas.viewport()
    positions = [window.canvas.mapFromScene(QPointF(*p)) for p in points]
    QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=positions[0])
    for point in positions[1:]:
        QTest.mouseMove(target, point)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=positions[-1])


def test_brush_eraser_undo_redo_and_cache_invalidation(window, monkeypatch):
    def no_raster(*args, **kwargs):
        raise AssertionError('Drawing must not rasterize the photo')
    with monkeypatch.context() as patch:
        patch.setattr(PhotoMask, 'raster', no_raster)
        window.mask_brush.click()
        gesture(window, [(70, 120), (190, 240)])
    first = window.current_photo_mask()
    assert first is window.current_photo_mask()
    assert not first._rasters
    assert not first.allows(np.array([[130, 180]]), window.image.shape)[0]
    assert 0 < window.mask_editor.overlay.brush().color().alpha() < 255
    window.mask_brush_size.setValue(60)
    window.mask_eraser.click()
    gesture(window, [(130, 175), (130, 185)])
    erased = window.current_photo_mask()
    assert erased is not first and erased.allows(np.array([[130, 180]]), window.image.shape)[0]
    assert window.mask_editor.overlay.path().contains(QPointF(130, 180)) is False
    window.mask_undo.click()
    assert not window.current_photo_mask().allows(np.array([[130, 180]]), window.image.shape)[0]
    window.mask_redo.click()
    assert window.current_photo_mask().allows(np.array([[130, 180]]), window.image.shape)[0]
    window.mask_brush.click()
    gesture(window, [(340, 180), (440, 180)])
    assert not window.current_photo_mask().allows(np.array([[390, 180]]), window.image.shape)[0]
    window.mask_finish.click()
    assert window.mask_editor.mode is None and window.mask_finish.isEnabled() is False
    window.mask_enabled.setChecked(False)
    assert window.current_photo_mask() is None
    window.mask_enabled.setChecked(True)
    window.mask_clear.click()
    assert window.current_photo_mask() is None
    window.mask_undo.click()
    assert window.current_photo_mask() is not None


def test_mask_controls_precede_identification_and_do_not_change_annotation_or_png(window, tmp_path):
    window.mask_section_toggle.setChecked(True)
    QApplication.processEvents()
    assert window.mask_section_toggle.mapTo(window.scroll.widget(), window.mask_section_toggle.rect().topLeft()).y() < \
           window.identify_button.mapTo(window.scroll.widget(), window.identify_button.rect().topLeft()).y()
    window.project.matrix = np.array([[1., 0, 0], [0, 1., 0]])
    window.project.labels = {'test': {'text': 'Keep me', 'position': [25, 30], 'hidden': False}}
    window.project.anchors = [{'id': 'test', 'pixel': [130, 180], 'enabled': True}]
    saved = deepcopy((window.project.labels, window.project.anchors, window.project.matrix))
    before, after = tmp_path/'before.png', tmp_path/'after.png'
    window.render_png(before)
    window.show_mask.setChecked(True)
    window.mask_editor.add(rectangle(10, 10, 510, 350))
    assert window.mask_editor.overlay.isVisible()
    window.render_png(after)
    assert np.array_equal(np.asarray(Image.open(before)), np.asarray(Image.open(after)))
    assert window.mask_editor.overlay.isVisible()
    window.workspace_tabs.setCurrentIndex(1)
    assert not window.mask_editor.overlay.isVisible()
    assert window.project.labels == saved[0] and window.project.anchors == saved[1]
    assert np.array_equal(window.project.matrix, saved[2])


def test_canvas_zoom_and_brush_controls_keep_wheel_contract(window):
    from tests.test_settings_wheel import wheel
    window.mask_section_toggle.setChecked(True)
    window.mask_eraser.click()
    before = window.canvas.transform().m11()
    wheel(window.canvas.viewport(), 120)
    assert window.canvas.transform().m11() > before
    for control in (window.mask_brush_size, window.mask_brush_readout):
        for focused in (False, True):
            control.setFocus() if focused else window.canvas.setFocus()
            value = control.value()
            wheel(control, -120)
            wheel(control, 24, touchpad=True)
            if control is window.mask_brush_readout:
                wheel(control.lineEdit(), 24, touchpad=True)
            assert control.value() == value


def test_dragging_diameter_slider_changes_round_brush_and_eraser_without_reprocessing(window, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Adjusting or painting a brush must not process the photo')
    monkeypatch.setattr(PhotoMask, 'raster', forbidden)
    window.mask_brush.click()
    QApplication.processEvents()
    slider = window.mask_brush_size
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                          QStyle.SubControl.SC_SliderHandle, slider).center()
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=handle)
    QTest.mouseMove(slider, QPoint(slider.width()*2//3, handle.y()))
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()*2//3, handle.y()))
    assert slider.value() > 80
    assert window.mask_brush_readout.value() == slider.value()
    assert window.mask_editor.radius == slider.value()/2
    gesture(window, [(130, 180)])
    assert window.mask_editor.overlay.path().contains(QPointF(130, 180))
    operation = window.project.recognition_mask['operations'][-1]
    assert operation['kind'] == 'paint' and operation['radius'] == slider.value()/2
    assert window.mask_editor.brush_cursor.rect().width() == slider.value()
    window.mask_eraser.click()
    gesture(window, [(130, 180)])
    assert window.mask_editor.overlay.path().isEmpty()
    # Erasing the entire mask also restores the no-mask detection fast path.
    assert window.current_photo_mask() is None
    window.mask_undo.click()
    assert window.current_photo_mask() is not None


def test_eraser_click_and_cancelled_gesture_keep_preview_and_detection_in_sync(window):
    window.mask_brush.click()
    gesture(window, [(70, 120), (190, 240)])
    window.mask_eraser.click()
    gesture(window, [(130, 180)])
    assert not window.mask_editor.overlay.path().contains(QPointF(130, 180))
    assert window.current_photo_mask().allows(np.array([[130, 180]]), window.image.shape)[0]
    window.mask_undo.click()
    assert window.mask_editor.overlay.path().contains(QPointF(130, 180))
    assert not window.current_photo_mask().allows(np.array([[130, 180]]), window.image.shape)[0]
    saved = deepcopy(window.project.recognition_mask)
    window.mask_brush.click()
    target = window.canvas.viewport()
    QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=window.canvas.mapFromScene(QPointF(300, 120)))
    QTest.mouseMove(target, window.canvas.mapFromScene(QPointF(420, 220)))
    QTest.keyClick(target, Qt.Key.Key_Escape)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton)
    assert window.project.recognition_mask == saved


def test_toolbar_visibility_preserves_annotations_filtering_exports_and_mask_state(window, tmp_path, monkeypatch):
    from moonlabeler.project import export_svg
    window.open_project(str(Path(__file__).parents[1]/'examples/demo.moonlabel'))
    assert window.annotation_items
    labels = list(window.annotation_items)
    positions = [item.pos() for item in labels]
    saved_labels = deepcopy(window.project.labels)
    # A mask drawn over actual labels must not regenerate or filter them.
    def no_rebuild(*args, **kwargs):
        raise AssertionError('Preview and recognition exclusions must reuse annotations')
    monkeypatch.setattr(window, 'refresh_annotations', no_rebuild)
    window.show_mask.setChecked(True)
    window.mask_editor.add(brush([[50, 50], [170, 170]], 40))
    mask = window.current_photo_mask()
    state = deepcopy(window.project.recognition_mask)
    entries, leaders = window.annotation_entries(), window.annotation_leaders()
    first = next(item for item in labels if item.isVisible())
    assert first.parentItem() is window.annotation_group and first.line.isVisible()
    window.render_png(tmp_path/'shown.png')
    export_svg(tmp_path/'shown.svg', window.image, entries, window.project, leaders)
    window.dirty = False
    window.show_annotations.setChecked(False)
    window.show_mask.setChecked(False)
    assert not any(item.isVisible() or item.line.isVisible() for item in labels)
    assert not window.mask_editor.overlay.isVisible()
    assert window.current_photo_mask() is mask and window.project.recognition_mask == state
    assert window.annotation_entries() == entries and window.annotation_leaders() == leaders
    window.render_png(tmp_path/'hidden.png')
    export_svg(tmp_path/'hidden.svg', window.image, window.annotation_entries(), window.project,
               window.annotation_leaders())
    assert np.array_equal(np.asarray(Image.open(tmp_path/'shown.png')), np.asarray(Image.open(tmp_path/'hidden.png')))
    assert (tmp_path/'shown.svg').read_bytes() == (tmp_path/'hidden.svg').read_bytes()
    assert not first.isVisible() and not window.mask_editor.overlay.isVisible()
    assert not window.dirty and window.project.labels == saved_labels
    assert window.annotation_items == labels and [item.pos() for item in labels] == positions
    # Content filtering while hidden must still apply when preview is restored.
    first.setVisible(False)
    first.update_map_leader()
    assert len(window.annotation_entries()) == len(entries)-1
    window.show_annotations.setChecked(True)
    assert not first.isVisible() and not first.line.isVisible()
    assert any(item.isVisible() for item in labels)
    # The toolbar can show the overlay even on the annotation page, without
    # turning editing on or changing whether recognition excludes the region.
    window.workspace_tabs.setCurrentIndex(1)
    window.show_mask.setChecked(True)
    assert window.mask_editor.overlay.isVisible() and window.mask_editor.mode is None
    assert window.current_photo_mask() is mask
    window.mask_enabled.setChecked(False)
    assert window.current_photo_mask() is None and window.mask_editor.overlay.isVisible()


def test_reopening_project_restores_exclusions_with_a_fresh_undo_history(window, tmp_path):
    path = tmp_path/'masked.moonlabel'
    photo = tmp_path/'photo.png'
    Image.fromarray(window.image).save(photo)
    window.project.image_path = str(photo)
    window.mask_brush.click()
    gesture(window, [(70, 120), (190, 240)])
    window.mask_eraser.click()
    gesture(window, [(130, 180)])
    window.project.save(path)
    expected = window.current_photo_mask().raster(window.image.shape).copy()
    window.mask_clear.click()
    window.dirty = False
    window.open_project(str(path))
    assert np.array_equal(window.current_photo_mask().raster(window.image.shape), expected)
    assert not window.mask_undo.isEnabled() and window.mask_editor.mode is None


@pytest.mark.parametrize('mask_visible', [False, True])
def test_mask_preview_never_blocks_label_editing_or_modifier_dragging(window, mask_visible):
    from tests.test_label_drag import mouse
    from PySide6.QtCore import QEvent
    window.open_project(str(Path(__file__).parents[1]/'examples/demo.moonlabel'))
    QApplication.processEvents()
    window.fit_canvas()
    label = next(item for item in window.annotation_items if item.isVisible() and
                 window.canvas.viewport().rect().contains(
                     window.canvas.mapFromScene(item.sceneBoundingRect().center())))
    center = label.sceneBoundingRect().center()
    window.mask_editor.add(brush([[center.x(), center.y()]], 60))
    window.show_mask.setChecked(mask_visible)
    clicked = []
    label.edit = clicked.append
    position = window.canvas.mapFromScene(center)
    QTest.mouseDClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert clicked == [label.feature]
    original = label.pos()
    control = Qt.KeyboardModifier.ControlModifier
    mouse(window.canvas, QEvent.Type.MouseButtonPress, position, control)
    mouse(window.canvas, QEvent.Type.MouseMove, position+QPoint(12, 8), control)
    mouse(window.canvas, QEvent.Type.MouseButtonRelease, position+QPoint(12, 8), control)
    assert label.pos() != original


def test_assisted_detection_uses_the_hidden_brush_mask_and_respects_enable_switch(window, monkeypatch):
    window.mask_brush_size.setValue(130)
    window.mask_brush.click()
    gesture(window, [(130, 180)])
    window.show_mask.setChecked(False)
    monkeypatch.setattr(window, 'run_background', lambda title, work, success: success(work()))
    window.crater_button.click()
    assert len(window.crater_candidates) == 1 and window.crater_candidates[0].x > 250
    window.mask_enabled.setChecked(False)
    window.crater_button.click()
    assert len(window.crater_candidates) == 2
