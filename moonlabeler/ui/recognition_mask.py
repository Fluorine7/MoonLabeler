# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Vector-only exclusion editing. No image processing on pointer movement."""
from copy import deepcopy
from shiboken6 import isValid

from PySide6.QtCore import QObject, Signal, Qt, QEvent, QPointF
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen, QAction, QKeySequence
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsRectItem


def operation_path(operation):
    points = operation['points']
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    if operation['kind'] == 'polygon':
        path.closeSubpath()
        return path
    radius = operation['radius']
    if path.isEmpty():
        path.addEllipse(QPointF(*points[0]), radius, radius)
        return path
    stroke = QPainterPathStroker()
    stroke.setWidth(radius*2)
    stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroke.createStroke(path)


class MaskEditor(QObject):
    changed = Signal()
    mode_changed = Signal()
    too_complex = Signal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.mode = None
        self.radius = 40.
        self.enabled = True
        self.operations = []
        self._undo, self._redo = [], []
        self._points = []
        self._panning = False
        self._cursor_position = None
        self._mouse_tracking = canvas.hasMouseTracking()
        self.layer = self.overlay = self.preview = self.brush_cursor = None
        canvas.viewport().installEventFilter(self)
        canvas.installEventFilter(self)
        for shortcut, callback in ((QKeySequence.StandardKey.Undo, self.undo),
                                   (QKeySequence.StandardKey.Redo, self.redo)):
            action = QAction(canvas)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            canvas.addAction(action)

    @property
    def items(self):
        return tuple(item for item in (self.overlay, self.preview, self.brush_cursor) if item is not None)

    def before_scene_clear(self):
        self.finish()
        self.layer = self.overlay = self.preview = self.brush_cursor = None

    def reset(self, state, shape):
        self.mode = None
        self.enabled = state['enabled']
        self.operations = deepcopy(state['operations'])
        self._undo, self._redo, self._points = [], [], []
        self._cursor_position = None
        self.layer = QGraphicsRectItem(0, 0, shape[1], shape[0])
        self.layer.setPen(QPen(Qt.PenStyle.NoPen))
        self.layer.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents)
        self.layer.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
        self.layer.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.layer.setZValue(5000)
        self.canvas.scene().addItem(self.layer)
        for attribute in ('overlay', 'preview'):
            item = QGraphicsPathItem(self.layer)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.setZValue(0 if attribute == 'overlay' else 1)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setBrush(QColor(240, 65, 65, 85))
            setattr(self, attribute, item)
        self.brush_cursor = QGraphicsEllipseItem(self.layer)
        self.brush_cursor.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.brush_cursor.setZValue(2)
        pen = QPen(QColor(255, 255, 255, 220), 1.)
        pen.setCosmetic(True)
        self.brush_cursor.setPen(pen)
        self.brush_cursor.hide()
        self.redraw()
        self.preview.hide()

    def state(self):
        return {'enabled': self.enabled, 'operations': deepcopy(self.operations)}

    def redraw(self):
        path = QPainterPath()
        for op in self.operations:
            part = operation_path(op)
            path = path.subtracted(part) if op['kind'] == 'erase' else path.united(part)
        if self.overlay is not None:
            self.overlay.setPath(path)

    def start(self, mode):
        self._points = []
        self.mode = mode
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        self.canvas.setMouseTracking(True)
        self.canvas.setFocus()
        self.preview.hide()
        self.mode_changed.emit()

    def finish(self):
        self.mode = None
        self._points = []
        self._panning = False
        self._cursor_position = None
        if self.preview is not None:
            self.preview.hide()
            self.brush_cursor.hide()
        self.canvas.setMouseTracking(self._mouse_tracking)
        self.canvas.unsetCursor()
        self.mode_changed.emit()

    def cancel(self):
        if self._points:
            self._points = []
            self.preview.hide()
        else:
            self.finish()

    def _remember(self):
        self._undo.append(self._snapshot())
        self._undo = self._undo[-50:]
        self._redo.clear()

    def _snapshot(self):
        # Qt paths are implicitly shared: undo/redo does not rebuild every
        # earlier brush stroke or allocate any photo-sized mask.
        return self.state(), self.overlay.path() if self.overlay is not None else QPainterPath()

    def set_radius(self, radius):
        self.radius = radius
        if self._cursor_position is not None:
            self._show_cursor(self._cursor_position)

    def set_enabled(self, enabled):
        if enabled != self.enabled:
            self._remember()
            self.enabled = enabled
            if not enabled:
                self.finish()
            self.changed.emit()

    def add(self, operation):
        if len(self.operations) >= 128 or sum(len(op['points']) for op in self.operations)+len(operation['points']) > 16384:
            self.too_complex.emit()
            return
        self._remember()
        self.enabled = True
        self.operations.append(deepcopy(operation))
        part, path = operation_path(operation), self.overlay.path()
        self.overlay.setPath(path.subtracted(part) if operation['kind'] == 'erase' else path.united(part))
        self.changed.emit()

    def clear(self):
        if self.operations:
            self._remember()
            self.operations = []
            self.cancel()
            self.redraw()
            self.changed.emit()

    def _restore(self, source, destination):
        if not source:
            return
        destination.append(self._snapshot())
        state, path = source.pop()
        self.enabled, self.operations = state['enabled'], state['operations']
        self._points = []
        if not self.enabled:
            self.finish()
        if self.preview is not None:
            self.preview.hide()
        self.overlay.setPath(path)
        self.changed.emit()

    def undo(self):
        self._restore(self._undo, self._redo)

    def redo(self):
        self._restore(self._redo, self._undo)

    def _position(self, event):
        p = self.canvas.mapToScene(event.position().toPoint())
        rect = self.canvas.sceneRect()
        return [min(max(p.x(), 0.), rect.width()), min(max(p.y(), 0.), rect.height())]

    def _operation(self):
        return {'kind': self.mode, 'points': self._points, 'radius': self.radius}

    def _show_cursor(self, point):
        self._cursor_position = point
        self.brush_cursor.setRect(point[0]-self.radius, point[1]-self.radius, self.radius*2, self.radius*2)
        self.brush_cursor.show()

    def _preview(self):
        self.preview.setBrush(QColor(255, 255, 255, 100) if self.mode == 'erase' else QColor(240, 65, 65, 85))
        self.preview.setPath(operation_path(self._operation()))
        self.preview.show()

    def eventFilter(self, watched, event):
        if self.mode is None or not isValid(self.canvas) or not self.canvas.isEnabled():
            return False
        kind = event.type()
        if kind == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Escape:
            event.accept()
            return True
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            if event.key() == Qt.Key.Key_Escape and kind == QEvent.Type.KeyPress:
                self.cancel()
                return True
            if event.key() == Qt.Key.Key_Space:
                self._panning = kind == QEvent.Type.KeyPress
                self.brush_cursor.hide()
                return True
        if watched is not self.canvas.viewport():
            return False
        if kind == QEvent.Type.MouseButtonDblClick:
            return True
        if kind == QEvent.Type.Leave:
            self._cursor_position = None
            self.brush_cursor.hide()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and not self._panning:
            if not self.canvas.sceneRect().contains(self.canvas.mapToScene(event.position().toPoint())):
                return False
            self._points = [self._position(event)]
            self._show_cursor(self._points[0])
            self._preview()
            return True
        if kind == QEvent.Type.MouseMove and not self._panning:
            point = self._position(event)
            self._show_cursor(point)
            if not self._points:
                return True
            dx, dy = point[0]-self._points[-1][0], point[1]-self._points[-1][1]
            if (dx*dx+dy*dy)*self.canvas.transform().m11()**2 >= 4:
                self._points.append(point)
                if len(self._points) >= 2048:
                    self._points = self._points[::2]+[point]
                self._preview()
            return True
        if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton and self._points:
            self._points.append(self._position(event))
            op = self._operation()
            self._points = []
            self.preview.hide()
            self.add(op)
            return True
        # Wheel events always go to the existing canvas zoom handler.
        return False
