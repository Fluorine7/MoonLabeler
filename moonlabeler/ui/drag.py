# SPDX-License-Identifier: GPL-3.0-or-later
"""Modifier-dragging shared by captions and movable map decorations."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsItem

# Qt maps ControlModifier to Command on macOS, Ctrl on Windows/Linux.
DRAG_KEY = 'Cmd' if sys.platform == 'darwin' else 'Ctrl'


class ModifierDragItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def drag_state_changed(self):
        pass

    def mousePressEvent(self, event):
        self._drag_offset = None
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._drag_offset = event.scenePos()-self.pos()
            self.scene().clearSelection()
            self.setSelected(True)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.drag_state_changed()
            event.accept()
        else:
            self.end_drag()
            event.ignore()  # Allow ordinary drags to pan the canvas.

    def mouseMoveEvent(self, event):
        if (self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.setPos(event.scenePos()-self._drag_offset)
        else:
            self.end_drag()
        event.accept()

    def end_drag(self):
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_state_changed()

    def mouseReleaseEvent(self, event):
        self.end_drag()
        event.accept()
