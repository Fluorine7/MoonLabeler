# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Local compute preferences; never saved in a shared photo project."""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox

from .. import compute
from ..i18n import tr


class ComputeDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle(tr('计算设置'))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(QLabel(tr('计算方式')))
        self.mode = QComboBox()
        self.mode.setObjectName('computeMode')
        self.mode.addItem(tr('自动选择（推荐）'), 'auto')
        self.mode.addItem(tr('仅 CPU · 关闭 GPU'), 'cpu')
        configured = compute.configured_mode()
        self.mode.setCurrentIndex(self.mode.findData(configured))
        override = compute.environment_override()
        self.mode.setEnabled(not override)
        layout.addWidget(self.mode)
        info = QLabel(tr(compute.status()))
        info.setWordWrap(True)
        info.setMaximumWidth(450)
        layout.addWidget(info)
        self.mode.currentIndexChanged.connect(lambda: info.setText(tr(compute.status(self.mode.currentData()))))
        note = QLabel(tr('设置保存在本机，下次计算生效。GPU 不可用时自动改用 CPU。'))
        note.setWordWrap(True)
        layout.addWidget(note)
        if override:
            environment = QLabel(tr('当前由 MOONLABELER_COMPUTE 环境变量指定，界面设置暂不生效。'))
            environment.setWordWrap(True)
            environment.setMaximumWidth(450)
            layout.addWidget(environment)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr('关闭'))
            buttons.rejected.connect(self.reject)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr('保存'))
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
            buttons.accepted.connect(self.save)
            buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        mode = self.mode.currentData()
        compute.set_mode(mode)
        self.preferences.setValue('compute/mode', mode)
        self.preferences.sync()
        self.accept()
