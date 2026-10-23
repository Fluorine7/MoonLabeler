# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Qt presentation of the same geographic overlays exported to SVG."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsPathItem

from ..map_layers import grid_color, legend_rect, legend_image


def path_from_segments(segments):
    path = QPainterPath()
    for segment in segments:
        path.moveTo(*segment[0])
        for point in segment[1:]:
            path.lineTo(*point)
    return path


class ElevationLegend(QGraphicsItem):
    def __init__(self, shape, palette):
        super().__init__()
        self.rect = QRectF(*legend_rect(shape))
        self.ramp = array_image(legend_image(shape, palette))
        self.setZValue(6)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget=None):
        x, y, w, h = self.rect.getRect()
        u = h/6
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(16, 21, 29, 235))
        painter.drawRoundedRect(self.rect, u*.4, u*.4)
        painter.drawImage(QRectF(x+u, y+u*2.2, w-2*u, u), self.ramp)
        font = QFont("serif")
        font.setPixelSize(max(1, round(u)))
        painter.setFont(font)
        painter.setPen(QColor("#f0ece1"))
        painter.drawText(QPointF(x+u, y+u*1.5), "LOLA · km (R = 1737.4 km)")
        metrics = QFontMetricsF(font)
        for start, text in ((x+u, "≤ −9"), (x+w/2-metrics.horizontalAdvance("0")/2, "0"),
                            (x+w-u-metrics.horizontalAdvance("≥ +9"), "≥ +9")):
            painter.drawText(QPointF(start, y+u*4.8), text)


class GridCaption(QGraphicsPathItem):
    def paint(self, painter, option, widget=None):
        # QGraphicsPathItem normally paints its stroke after its fill. At map
        # caption sizes that covers the fine strokes; the halo must go first.
        painter.strokePath(self.path(), self.pen())
        painter.fillPath(self.path(), self.brush())


def array_image(array):
    h, w = array.shape[:2]
    fmt = QImage.Format.Format_RGBA8888 if array.shape[2] == 4 else QImage.Format.Format_RGB888
    return QImage(array.data, w, h, array.strides[0], fmt).copy()


def update_map_opacity(items, layers, project, field):
    """Update existing scene items without reprojecting or moving labels."""
    for item in items:
        if field == "grid_opacity" and getattr(item, "map_layer", None) == "grid":
            item.setOpacity(project.grid_opacity)
        elif field == "elevation_opacity" and getattr(item, "map_layer", None) == "elevation":
            item.setPixmap(QPixmap.fromImage(array_image(layers.elevation)))


def add_map_layers(scene, project, shape, layers):
    items = []
    h, w = shape[:2]
    if layers.elevation is not None:
        item = QGraphicsPixmapItem(QPixmap.fromImage(array_image(layers.elevation)))
        item.map_layer = "elevation"
        item.setTransform(QTransform.fromScale(w/layers.elevation.shape[1], h/layers.elevation.shape[0]))
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setZValue(2)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        scene.addItem(item)
        items.append(item)
    width, size = max(.7, min(h, w)*.00065), max(6, round(min(h, w)*.009))
    color = QColor(grid_color(project))
    font = QFont("serif")
    font.setPixelSize(size)
    for line in layers.grid:
        pen = QPen(color, width)
        if not line.major:
            pen.setDashPattern([4., 5.])
        item = scene.addPath(path_from_segments(line.segments), pen)
        item.map_layer = "grid"
        item.setOpacity(project.grid_opacity)
        item.setZValue(4)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        items.append(item)
        if not line.label:
            continue
        path = QPainterPath()
        path.addText(*line.label_position, font, line.label)
        caption = GridCaption(path)
        caption.map_layer = "grid"
        caption.grid_line = line
        caption.setPen(QPen(QColor("#10151d"), max(1., size*.12)))
        caption.setBrush(color)
        scene.addItem(caption)
        caption.setOpacity(project.grid_opacity)
        caption.setZValue(5)
        caption.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        items.append(caption)
    if layers.elevation is not None:
        legend = ElevationLegend(shape, project.elevation_palette)
        scene.addItem(legend)
        items.append(legend)
    return items
