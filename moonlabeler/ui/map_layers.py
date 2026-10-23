# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Qt presentation of the same geographic overlays exported to SVG."""
import math
from dataclasses import dataclass
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsPathItem, QGraphicsEffect

from ..map_layers import (grid_color, grid_appearance, grid_dashes, legend_rect, legend_image,
                          legend_title, contour_appearance, terminator_appearance, terminator_dashes, line_strokes,
                          feathered_coverage)


def path_from_segments(segments):
    path = QPainterPath()
    for segment in segments:
        path.moveTo(*segment[0])
        for point in segment[1:]:
            path.lineTo(*point)
    return path


class PhotoCoverageEffect(QGraphicsEffect):
    """Composite only the visible device area, including at large canvas zooms."""
    def __init__(self, rect):
        super().__init__()
        self.rect = rect
        self.mask = QImage()

    def draw(self, painter):
        transform = painter.worldTransform()
        source = self.sourceBoundingRect(Qt.CoordinateSystem.LogicalCoordinates)
        bounds = transform.mapRect(source).toAlignedRect().intersected(painter.viewport())
        if bounds.isEmpty():
            return
        # QGraphicsOpacityEffect caches the entire transformed photo, which can
        # allocate hundreds of megapixels when zoomed. Keep this buffer bounded
        # by the viewport; exports use their original-size target instead.
        dpr = painter.device().devicePixelRatioF()
        image = QImage(round(bounds.width()*dpr), round(bounds.height()*dpr), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        buffer = QPainter(image)
        buffer.setRenderHints(painter.renderHints())
        buffer.translate(-bounds.x(), -bounds.y())
        buffer.setWorldTransform(transform, True)
        self.drawSource(buffer)
        buffer.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        buffer.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        buffer.drawImage(self.rect, self.mask)
        buffer.end()
        painter.save()
        painter.setWorldTransform(QTransform())
        painter.drawImage(bounds.topLeft(), image)
        painter.restore()


class MapCoverage(QGraphicsPathItem):
    """A soft photo-space mask; labels, legend and terminator stay independent."""
    def __init__(self, shape, coverage):
        super().__init__()
        self.rect = QRectF(0, 0, shape[1], shape[0])
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(1)
        bounds = QPainterPath()
        bounds.addRect(self.rect)
        self.setPath(bounds)
        self.effect = PhotoCoverageEffect(self.rect)
        self.setGraphicsEffect(self.effect)
        self.set_coverage(coverage)

    def set_coverage(self, coverage):
        path = QPainterPath()
        if coverage is None:
            path.addRect(self.rect)
        else:
            for polygon in coverage:
                path.moveTo(*polygon[0])
                for point in polygon[1:]:
                    path.lineTo(*point)
                path.closeSubpath()
        self.coverage_path = path
        self.effect.setEnabled(coverage is not None)
        if coverage is not None:
            mask = feathered_coverage((self.rect.height(), self.rect.width()), coverage)
            self.effect.mask = array_image(mask)
            self.effect.update()


def update_map_coverage(items, coverage):
    for item in items:
        if isinstance(item, MapCoverage):
            item.set_coverage(coverage)


class ElevationLegend(QGraphicsItem):
    def __init__(self, shape, project, contour_interval=None):
        super().__init__()
        self.rect = QRectF(*legend_rect(shape))
        self.project = project
        self.contour_interval = project.contour_interval if contour_interval is None else contour_interval
        self.ramp = array_image(legend_image(shape, project.elevation_palette))
        self.setZValue(6)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget=None):
        x, y, w, h = self.rect.getRect()
        u = h/6
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(55, 47, 27, 225) if self.project.art_style == "topographic" else QColor(16, 21, 29, 235))
        if self.project.art_style == "topographic":
            painter.setPen(QPen(QColor("#968454"), max(.5, u*.045)))
        painter.drawRoundedRect(self.rect, u*.4, u*.4)
        if self.project.elevation_enabled:
            painter.drawImage(QRectF(x+u, y+u*2.2, w-2*u, u), self.ramp)
        font = QFont("sans-serif" if self.project.art_style == "topographic" else "serif")
        font.setPixelSize(max(1, round(u)))
        painter.setFont(font)
        painter.setPen(QColor("#f0ece1"))
        painter.drawText(QPointF(x+u, y+u*1.5), legend_title(self.project, self.contour_interval))
        if not self.project.elevation_enabled:
            painter.setPen(QPen(QColor("#c5bb82"), max(1., u*.12)))
            painter.drawLine(QPointF(x+u, y+u*2.7), QPointF(x+w-u, y+u*2.7))
            painter.setPen(QColor("#f0ece1"))
            index = f"Index: {self.contour_interval*5:g} km · " if self.contour_interval != "auto" else ""
            painter.drawText(QPointF(x+u, y+u*4.8), f"{index}R = 1737.4 km")
            return
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


@dataclass
class MapPreview:
    source_size: tuple
    size: tuple
    paths: list
    image: QImage


def rasterize_map_paths(paths, source_size, size):
    """QImage painting is thread-safe; no scene items or QPixmaps in this work."""
    image = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size[0]/source_size[0], size[1]/source_size[1])
    for path, style in paths:
        dashes = style[3] if len(style) > 3 else ()
        for ink, width, alpha in line_strokes(*style[:3]):
            color = QColor(ink)
            color.setAlphaF(alpha)
            pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            if dashes:
                pen.setDashPattern([distance/width for distance in dashes])
            painter.strokePath(path, pen)
    painter.end()
    return image


def prepare_contour_preview(project, shape, contours):
    h, w = shape[:2]
    # Separate disconnected isolines: stroking thousands of islands in one
    # compound path makes the rasterizer spend seconds resolving overlaps.
    paths = [(path_from_segments([segment]), contour_appearance(shape, line.major, project.art_style))
             for line in contours for segment in line.segments]
    scale = min(1., (ContourLayer.MAX_PREVIEW_PIXELS/(w*h))**.5)
    size = (max(1, round(w*scale)), max(1, round(h*scale)))
    return MapPreview((w, h), size, paths, rasterize_map_paths(paths, (w, h), size))


class ContourLayer(QGraphicsItem):
    """Retain vector geometry but composite a bounded preview during interaction.

    Complex round joins are expensive to rasterize for every mouse movement.
    Opacity and view transforms reuse this image; PNG export temporarily draws
    the same geometry at the photograph's original resolution. SVG continues to
    use MapLayers.contours directly.
    """
    MAX_PREVIEW_PIXELS = 16_000_000

    def __init__(self, project, shape, contours, *, prepared=None):
        super().__init__()
        h, w = shape[:2]
        self.rect = QRectF(0, 0, w, h)
        prepared = prepared if prepared is not None else prepare_contour_preview(project, shape, contours)
        self.source_size, self.preview_size = prepared.source_size, prepared.size
        self.paths, self.preview = prepared.paths, prepared.image
        self.prepared = prepared
        self.mipmaps = {0: self.preview}
        self.export_image = None
        self.map_layer = "contour"
        self.setOpacity(project.contour_opacity)
        self.setZValue(3)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return self.rect

    def rasterize(self, size):
        return rasterize_map_paths(self.paths, self.source_size, size)

    def set_export_mode(self, enabled):
        if enabled and self.preview_size != self.source_size:
            self.export_image = self.rasterize(self.source_size)
        elif not enabled:
            self.export_image = None

    def paint(self, painter, option, widget=None):
        image = self.export_image
        if image is None:
            transform = painter.deviceTransform()
            scale = max(math.hypot(transform.m11(), transform.m12()),
                        math.hypot(transform.m21(), transform.m22()), 1e-8)
            ratio = min(self.preview_size[0]/self.source_size[0], self.preview_size[1]/self.source_size[1])
            level = max(0, int(math.floor(math.log2(max(ratio/scale, 1.)))))
            if level not in self.mipmaps:
                width, height = (max(1, dimension//(2**level)) for dimension in self.preview_size)
                # Area filtering retains subpixel contours when the whole photo
                # is fitted to the window; direct bilinear minification can miss them.
                self.mipmaps[level] = self.preview.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation)
            image = self.mipmaps[level]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect, image)
        painter.restore()


class GridLayer(ContourLayer):
    """Share the bounded raster preview and full-resolution export of contours."""
    def __init__(self, project, shape, lines, *, prepared=None):
        if prepared is None:
            h, w = shape[:2]
            paths = []
            for line in lines:
                style = grid_appearance(project, shape, line.major)
                paths.append((path_from_segments(line.segments), (*style, grid_dashes(style[2], line.major))))
            scale = min(1., (self.MAX_PREVIEW_PIXELS/(w*h))**.5)
            size = (max(1, round(w*scale)), max(1, round(h*scale)))
            prepared = MapPreview((w, h), size, paths, rasterize_map_paths(paths, (w, h), size))
        super().__init__(project, shape, (), prepared=prepared)
        self.map_layer = "grid"
        self.setOpacity(project.grid_opacity)
        self.setZValue(4)


def array_image(array):
    h, w = array.shape[:2]
    fmt = QImage.Format.Format_RGBA8888 if array.shape[2] == 4 else QImage.Format.Format_RGB888
    return QImage(array.data, w, h, array.strides[0], fmt).copy()


def update_map_opacity(items, layers, project, field):
    """Update existing scene items without reprojecting or moving labels."""
    for item in items:
        if field == "grid_opacity" and getattr(item, "map_layer", None) == "grid":
            item.setOpacity(project.grid_opacity)
        elif field == "contour_opacity" and getattr(item, "map_layer", None) == "contour":
            item.setOpacity(project.contour_opacity)
        elif field == "terminator_opacity" and getattr(item, "map_layer", None) == "terminator":
            item.setOpacity(project.terminator_opacity)
        elif field == "elevation_opacity" and getattr(item, "map_layer", None) == "elevation":
            item.setPixmap(QPixmap.fromImage(array_image(layers.elevation)))


def _line_items(scene, segments, appearance, opacity, layer, z, dashes=()):
    path, items = path_from_segments(segments), []
    for ink, thickness, alpha in line_strokes(*appearance):
        shade = QColor(ink)
        shade.setAlphaF(alpha)
        pen = QPen(shade, thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dashes:
            pen.setDashPattern([distance/thickness for distance in dashes])
        item = scene.addPath(path, pen)
        item.map_layer = layer
        item.setOpacity(opacity)
        item.setZValue(z)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        items.append(item)
    return items


def add_map_layers(scene, project, shape, layers, *, contour_preview=None, grid_preview=None):
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
    if layers.contours:
        contours = ContourLayer(project, shape, layers.contours, prepared=contour_preview)
        scene.addItem(contours)
        items.append(contours)
    size = max(6, round(min(h, w)*.009))
    color = QColor(grid_color(project))
    font = QFont("serif")
    font.setPixelSize(size)
    if layers.grid:
        grid = GridLayer(project, shape, layers.grid, prepared=grid_preview)
        scene.addItem(grid)
        items.append(grid)
    for line in layers.grid:
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
    if items:
        clip = MapCoverage(shape, layers.coverage)
        scene.addItem(clip)
        for item in items:
            item.setParentItem(clip)
        # Remove children from the scene before their parent during a refresh.
        items.append(clip)
    if layers.terminator:
        style = terminator_appearance(project, shape)
        items.extend(_line_items(scene, layers.terminator, style, project.terminator_opacity,
                                 "terminator", 5.5, terminator_dashes(project, style[2])))
    if layers.elevation is not None or layers.contours is not None:
        legend = ElevationLegend(shape, project, layers.contour_interval)
        scene.addItem(legend)
        items.append(legend)
    return items
