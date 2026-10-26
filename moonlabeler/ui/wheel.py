# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Keep wheel gestures for navigation, including over focused settings."""
from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QAbstractSpinBox, QAbstractButton, QComboBox, QLineEdit, QSlider


class SettingsWheelGuard(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        control = watched.parentWidget() if isinstance(watched, QLineEdit) else watched
        if not isinstance(control, (QAbstractSpinBox, QAbstractButton, QComboBox, QSlider)):
            return False
        # Forward to the surrounding page rather than swallowing navigation.
        # Open combo popups are item views, so their lists still scroll normally.
        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                if event.angleDelta().isNull() and not event.pixelDelta().isNull():
                    # Native scroll bars can ignore pixel-only trackpad events.
                    # Move the surrounding panel by those pixels directly.
                    delta = event.pixelDelta()
                    for bar, pixels in ((parent.horizontalScrollBar(), delta.x()),
                                        (parent.verticalScrollBar(), delta.y())):
                        if pixels:
                            bar.setValue(bar.value()-pixels)
                    event.accept()
                    return True
                viewport = parent.viewport()
                forwarded = QWheelEvent(
                    QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())), event.globalPosition(),
                    event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(),
                    event.phase(), event.inverted(), event.source(), event.pointingDevice())
                QApplication.sendEvent(viewport, forwarded)
                event.accept()
                return True
            parent = parent.parentWidget()
        event.ignore()
        return True


def protect_settings_from_wheel():
    """Install once for all windows, dialogs, and controls created later."""
    application = QApplication.instance()
    if application.findChild(SettingsWheelGuard) is None:
        guard = SettingsWheelGuard(application)
        application.installEventFilter(guard)
