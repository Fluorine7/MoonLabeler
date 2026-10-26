# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Collapsed, explicit multi-selection of catalogue feature types."""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolButton, QCheckBox

from ..i18n import tr, trf


class FeatureTypeSelector(QWidget):
    selectionChanged = Signal()

    def __init__(self, choices, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName('sectionToggle')
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setAccessibleName(tr('地形类别'))
        layout.addWidget(self.toggle)
        self.panel = QWidget()
        self.choices_layout = QVBoxLayout(self.panel)
        self.choices_layout.setContentsMargins(16, 4, 0, 4)
        self.choices_layout.setSpacing(7)
        self.all_checkbox = QCheckBox(tr('全部'))
        self.all_checkbox.setChecked(True)
        self.choices_layout.addWidget(self.all_checkbox)
        self.checks = {}
        for value, label in choices:
            self.add_choice(value, label)
        self.all_checkbox.toggled.connect(self._selection_changed)
        layout.addWidget(self.panel)
        self.toggle.toggled.connect(self._set_expanded)
        self._set_expanded(False)
        self._refresh()

    def add_choice(self, value, label):
        checkbox = QCheckBox(label)
        checkbox.toggled.connect(self._selection_changed)
        self.checks[value] = checkbox
        self.choices_layout.addWidget(checkbox)

    def selection(self):
        if self.all_checkbox.isChecked():
            return '全部'
        return sorted(value for value, checkbox in self.checks.items() if checkbox.isChecked())

    def set_selection(self, value):
        selected = {value} if isinstance(value, str) else set(value)
        for missing in sorted(selected-{'全部'}-self.checks.keys()):
            # Retain filters from an older or extended catalogue on reopening.
            self.add_choice(missing, missing)
        with QSignalBlocker(self.all_checkbox):
            self.all_checkbox.setChecked(value == '全部')
        for kind, checkbox in self.checks.items():
            with QSignalBlocker(checkbox):
                checkbox.setChecked(kind in selected)
        self._refresh()

    def _set_expanded(self, expanded):
        self.panel.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _refresh(self):
        all_types = self.all_checkbox.isChecked()
        for checkbox in self.checks.values():
            checkbox.setEnabled(not all_types)
        selected = [checkbox.text() for checkbox in self.checks.values() if checkbox.isChecked()]
        summary = tr('全部') if all_types else (trf('已选 {count} 类', count=len(selected)) if selected else tr('未选择'))
        self.toggle.setText(trf('地形类别 · {selection}', selection=summary))
        self.toggle.setToolTip(tr('全部') if all_types else ('\n'.join(selected) if selected else tr('未选择')))

    def _selection_changed(self):
        self._refresh()
        self.selectionChanged.emit()
