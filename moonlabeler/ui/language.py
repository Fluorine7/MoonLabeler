# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Interface language picker; the choice is saved locally and applies after restart."""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox

from .. import i18n
from ..i18n import tr


class LanguageDialog(QDialog):
    def __init__(self, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('界面语言'))
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.combo = QComboBox()
        self.combo.setObjectName('uiLanguage')
        for code in i18n.LANGUAGES:
            self.combo.addItem(i18n.LANGUAGE_NAMES[code], code)
        self.combo.setCurrentIndex(max(0, self.combo.findData(current)))
        layout.addWidget(self.combo)
        note = QLabel(tr('切换后需重新启动 MoonLabeler 才会生效。设置保存在本机，不写入工程文件。'))
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('确定'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self):
        return self.combo.currentData()
