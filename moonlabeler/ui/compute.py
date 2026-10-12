# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Local compute preferences; never saved in a shared photo project."""
import os

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox

from .. import terrain_metal


class ComputeDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle('计算设置')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(QLabel('计算方式'))
        self.mode = QComboBox()
        self.mode.setObjectName('computeMode')
        self.mode.addItem('自动选择（推荐）', 'auto')
        self.mode.addItem('仅 CPU · 关闭 GPU', 'cpu')
        self.mode.addItem('Apple GPU', 'metal')
        available, detail = terrain_metal.metal_support()
        self.mode.model().item(2).setEnabled(available)
        configured = terrain_metal.configured_mode()
        self.mode.setCurrentIndex(self.mode.findData(configured))
        override = os.environ.get('MOONLABELER_COMPUTE', '').lower() in terrain_metal.MODES
        self.mode.setEnabled(not override)
        layout.addWidget(self.mode)
        info = QLabel(detail)
        info.setWordWrap(True)
        info.setMaximumWidth(450)
        layout.addWidget(info)
        note = QLabel('设置保存在本机，下次计算生效。GPU 不可用时自动改用 CPU。')
        note.setWordWrap(True)
        layout.addWidget(note)
        if override:
            environment = QLabel('当前由 MOONLABELER_COMPUTE 环境变量指定，界面设置暂不生效。')
            environment.setWordWrap(True)
            environment.setMaximumWidth(450)
            layout.addWidget(environment)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
            buttons.accepted.connect(self.save)
            buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        mode = self.mode.currentData()
        terrain_metal.set_mode(mode)
        self.preferences.setValue('compute/mode', mode)
        self.preferences.sync()
        self.accept()
