# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Movable cached locator; only explicit exports paint its vector decoration."""
from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsItem

from .drag import DRAG_KEY, ModifierDragItem
from ..color_management import srgb_color_space
from ..i18n import trf
from ..photo_overview import overview_rect, overview_document


class PhotoOverview(ModifierDragItem):
    def __init__(self, shape, project, model, *, moved=None):
        super().__init__()
        self._ready = False
        self.photo_shape, self.project, self.model, self.moved = shape, project, model, moved
        x, y, w, h = overview_rect(shape, project.overview_position)
        self.rect = QRectF(0, 0, w, h)
        hit_shape = QPainterPath()
        hit_shape.addRoundedRect(QRectF(1, 1, 318, 364), 12, 12)
        self.hit_shape = QTransform.fromScale(w/320, h/366).map(hit_shape)
        self.art_style = None
        self.set_style(project.art_style)
        self._export_mode = False
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setToolTip(trf("按住 {key} 拖动照片区域示意图", key=DRAG_KEY))
        self.setPos(x, y)
        self._ready = True

    def set_style(self, art_style):
        if self.art_style == art_style:
            return
        self.art_style = art_style
        self.renderer = QSvgRenderer(QByteArray(overview_document(self.model, art_style).encode('utf-8')))
        self.preview = QImage(640, 732, QImage.Format.Format_ARGB32_Premultiplied)
        self.preview.setColorSpace(srgb_color_space())
        self.preview.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.preview)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                               QPainter.RenderHint.SmoothPixmapTransform)
        self.renderer.render(painter)
        painter.end()
        self.update()

    def boundingRect(self):
        return self.rect

    def shape(self):
        return self.hit_shape

    def set_export_mode(self, enabled):
        self._export_mode = enabled
        self.update()

    def paint(self, painter, option, widget=None):
        if self._export_mode:
            self.renderer.render(painter, self.rect)
        else:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.rect, self.preview)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            x, y, _, _ = overview_rect(self.photo_shape, (value.x(), value.y()))
            return QPointF(x, y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self._ready:
            position = [self.pos().x(), self.pos().y()]
            self.project.overview_position = position
            if self.moved is not None:
                self.moved(position)
        return super().itemChange(change, value)
