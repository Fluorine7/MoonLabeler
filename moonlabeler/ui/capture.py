# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Separate numeric fields with deliberate keyboard focus progression."""
from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit


class CaptureField(QLineEdit):
    def __init__(self, digits, minimum, maximum, label):
        super().__init__()
        self.digits, self.minimum, self.maximum = digits, minimum, maximum
        self.next_field = None
        self.setMaxLength(digits)
        self.setValidator(QRegularExpressionValidator(QRegularExpression(f'[0-9]{{0,{digits}}}'), self))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAccessibleName(label)
        self.setToolTip(label)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def focusOutEvent(self, event):
        if self.text() and self.minimum <= int(self.text()) <= self.maximum:
            self.setText(self.text().zfill(self.digits))
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if (event.text().isdigit() and len(self.text()) == self.digits
                and self.minimum <= int(self.text()) <= self.maximum
                and self.next_field is not None and self.next_field.isVisible()):
            self.next_field.setFocus(Qt.FocusReason.TabFocusReason)
            self.next_field.selectAll()
