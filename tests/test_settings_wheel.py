# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Scrolling a settings page must never edit a value under the pointer."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QAbstractSpinBox, QComboBox, QDateTimeEdit,
                               QScrollArea, QStyle, QStyleOptionSpinBox, QSlider, QWidget)

from moonlabeler.app import MainWindow


@pytest.fixture
def window():
    application = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.workspace_tabs.setCurrentIndex(1)
    win.map_styles_toggle.setChecked(True)
    win.grid_spacing.setCurrentIndex(win.grid_spacing.findData(15))
    win.elevation_toggle.setChecked(True)
    win.contour_toggle.setChecked(True)
    win.terminator_toggle.setChecked(True)
    win.map_light_toggle.setChecked(True)
    win.show()
    application.processEvents()
    yield win
    win.dirty = False
    win.close()


def wheel(widget, delta=120, *, touchpad=False):
    position = widget.rect().center()
    event = QWheelEvent(QPointF(position), QPointF(widget.mapToGlobal(position)),
                        QPoint(0, delta) if touchpad else QPoint(),
                        QPoint() if touchpad else QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate if touchpad else Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize('field', ['toggle', 'all_checkbox', 'type'])
@pytest.mark.parametrize('focused', [False, True])
def test_feature_type_checklist_wheel_scrolls_panel_without_changing_selection(window, field, focused):
    selector = window.kind
    selector.toggle.setChecked(True)
    selector.all_checkbox.setChecked(False)
    checkbox = selector.checks['Crater, craters']
    checkbox.setChecked(True)
    control = checkbox if field == 'type' else getattr(selector, field)
    QApplication.processEvents()
    control.setFocus() if focused else window.catalog_button.setFocus()
    QApplication.processEvents()
    assert control.hasFocus() == focused
    area = window.annotation_scroll
    bar = area.verticalScrollBar()
    before = selector.selection()
    window.style_pending = False
    for touchpad in (False, True):
        bar.setValue(0)
        wheel(control, -120, touchpad=touchpad)
        assert selector.selection() == before and selector.toggle.isChecked()
        assert not window.style_pending
        assert bar.value() > 0
    selector.all_checkbox.setChecked(True)
    assert not checkbox.isEnabled()
    bar.setValue(0)
    wheel(checkbox, -120)
    assert selector.selection() == '全部' and bar.value() > 0


@pytest.mark.parametrize("field", ["font_size", "ui_font_step", "grid_opacity", "elevation_opacity",
                                   "diameter", "maximum", "art_style", "grid_spacing",
                                   "elevation_palette", "contour_interval", "contour_opacity", "terminator_opacity", "terminator_source", "map_light_threshold", "language", "font_weight",
                                   "grid_opacity_value", "elevation_opacity_value", "contour_opacity_value", "terminator_opacity_value", "map_light_readout"])
@pytest.mark.parametrize("focused", [False, True])
def test_wheel_over_setting_never_changes_value(window, field, focused):
    control = getattr(window, field)
    if focused:
        control.setFocus()
    else:
        window.catalog_button.setFocus()
    QApplication.processEvents()
    assert control.hasFocus() == focused
    before = setting_value(control)
    window.style_pending = False
    for touchpad, delta in ((False, 120), (False, -120), (True, 24), (True, -24)):
        wheel(control, delta, touchpad=touchpad)
        assert setting_value(control) == before, f"Scrolling changed {field}: {before} → {setting_value(control)}"
        assert not window.style_pending, "Scrolling must not mark settings as edited"


def setting_value(control):
    if isinstance(control, QComboBox):
        return control.currentIndex()
    if isinstance(control, QDateTimeEdit):
        return control.dateTime()
    return control.value()


def test_every_native_parameter_including_date_time_ignores_wheel(window):
    controls = [control for control in window.findChildren(QWidget)
                if isinstance(control, (QAbstractSpinBox, QComboBox, QSlider))]
    assert window.date in controls and window.capture_time in controls
    for control in controls:
        before = setting_value(control)
        for delta in (120, -120):
            wheel(control, delta)
            assert setting_value(control) == before


@pytest.mark.parametrize("field,editor", [("font_size", False), ("font_size", True),
                                         ("grid_opacity", False), ("grid_spacing", False),
                                         ("grid_opacity_value", True), ("map_light_readout", True)])
def test_wheel_over_parameter_scrolls_outer_panel(window, field, editor):
    control = getattr(window, field)
    area = control.parentWidget()
    while not isinstance(area, QScrollArea):
        area = area.parentWidget()
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    before = setting_value(control)
    wheel(control.lineEdit() if editor else control, -120)
    assert setting_value(control) == before
    assert bar.value() > 0, "The parameter must pass the gesture to the surrounding page"


@pytest.mark.parametrize("field,readout", [
    ("grid_opacity", "grid_opacity_value"), ("elevation_opacity", "elevation_opacity_value"),
    ("contour_opacity", "contour_opacity_value"), ("terminator_opacity", "terminator_opacity_value"),
    ("map_light_threshold", "map_light_readout"),
])
def test_slider_numbers_accept_precise_typing_and_stay_in_sync(window, field, readout):
    slider, editor = getattr(window, field), getattr(window, readout)
    maximum = 255 if field == "map_light_threshold" else 100
    editor.setFocus()
    editor.selectAll()
    before = slider.value()
    QTest.keyClicks(editor, "37")
    assert slider.value() == before, "Do not apply a partially typed multi-digit number"
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert slider.value() == editor.value() == 37
    for value in (0, maximum):
        slider.setValue(value)
        assert editor.value() == value
        assert editor.fontMetrics().horizontalAdvance(editor.text()) <= editor.lineEdit().width()
    editor.selectAll()
    QTest.keyClicks(editor, "23")
    window.catalog_button.setFocus()
    QApplication.processEvents()
    assert not editor.hasFocus()
    assert slider.value() == editor.value() == 23
    before = slider.value()
    for touchpad in (False, True):
        wheel(editor.lineEdit(), -120, touchpad=touchpad)
    assert slider.value() == editor.value() == before
    assert (editor.minimum(), editor.maximum()) == (0, maximum)


def test_number_field_follows_layer_enablement_through_background_work(window):
    window.lit.setChecked(False)
    window.map_light_toggle.setChecked(False)
    assert not window.map_light_threshold.isEnabled() and not window.map_light_readout.isEnabled()
    window.sidebar.setEnabled(False)
    window.map_light_toggle.setChecked(True)
    window.sidebar.setEnabled(True)
    assert window.map_light_threshold.isEnabled() and window.map_light_readout.isEnabled()
    window.map_light_toggle.setChecked(False)
    window.lit.setChecked(True)
    assert window.map_light_threshold.isEnabled() and window.map_light_readout.isEnabled()


def test_new_dropdown_popup_can_scroll_without_changing_selection(window):
    combo = window.ui_combo()
    combo.setParent(window)
    combo.addItems([f"Choice {number}" for number in range(60)])
    combo.setMaxVisibleItems(5)
    combo.show()
    wheel(combo, -120)
    assert combo.currentIndex() == 0, "Controls created later need the same protection"
    combo.showPopup()
    try:
        view = combo.view()
        view.setFixedHeight(120)
        QApplication.processEvents()
        bar = view.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(0)
        before = combo.currentIndex()
        wheel(view.viewport(), -120)
        assert bar.value() > 0 and combo.currentIndex() == before
    finally:
        combo.hidePopup()


def test_keyboard_buttons_and_explicit_selection_still_change_settings(window):
    control = window.font_size
    before = control.value()
    control.setFocus()
    QTest.keyClick(control, Qt.Key.Key_Up)
    assert control.value() > before
    before = control.value()
    option = QStyleOptionSpinBox()
    option.initFrom(control)
    option.stepEnabled = QAbstractSpinBox.StepEnabledFlag.StepUpEnabled | QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
    rect = control.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option,
                                         QStyle.SubControl.SC_SpinBoxUp, control)
    QTest.mouseClick(control, Qt.MouseButton.LeftButton, pos=rect.center())
    assert control.value() > before
    control.selectAll()
    QTest.keyClicks(control, "2.40")
    QTest.keyClick(control, Qt.Key.Key_Return)
    assert control.value() == 2.4
    combo = window.art_style
    combo.showPopup()
    view = combo.view()
    rect = view.visualRect(combo.model().index(1, 0))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert combo.currentIndex() == 1
