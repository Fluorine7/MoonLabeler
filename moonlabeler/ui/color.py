# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""A colour picker that follows the application's language on every platform."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QLabel, QAbstractButton

from ..i18n import tr


class ColorDialog(QColorDialog):
    def __init__(self, color, parent=None):
        super().__init__(QColor(color), parent)
        # Native dialogs follow the OS locale; our minimal Qt packages do not
        # ship qtbase translations. Translate this standard widget explicitly.
        self.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        self.setWindowTitle(tr('选择颜色'))
        captions = {
            'Basic colors': tr('基本颜色'), 'Custom colors': tr('自定义颜色'),
            'Hue:': tr('色相：'), 'Sat:': tr('饱和度：'), 'Val:': tr('明度：'),
            'Red:': tr('红：'), 'Green:': tr('绿：'), 'Blue:': tr('蓝：'),
            'Alpha channel:': tr('不透明度：'), 'HTML:': tr('颜色代码：'),
            'Pick Screen Color': tr('拾取屏幕颜色'), 'Add to Custom Colors': tr('添加到自定义颜色'),
            'OK': tr('确定'), 'Cancel': tr('取消'),
        }
        for widget in self.findChildren(QLabel)+self.findChildren(QAbstractButton):
            key = widget.text().replace('&', '')
            if key in captions:
                widget.setText(captions[key])

    @classmethod
    def choose(cls, color, parent=None):
        dialog = cls(color, parent)
        try:
            return dialog.selectedColor() if dialog.exec() == QDialog.DialogCode.Accepted else QColor()
        finally:
            dialog.deleteLater()
