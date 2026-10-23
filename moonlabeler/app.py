# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Native Qt desktop application. All processing happens on this computer."""
from datetime import datetime, timezone
from dataclasses import replace
from itertools import islice
from pathlib import Path
from threading import Event
import os
import csv
import json
import math
import shutil
import unicodedata
import sys
import traceback

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QDateTime, QObject, Signal, QRunnable, QThreadPool, QTimer, QSettings, QProcess
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QPixmapCache, QPainter, QPen, QPainterPath, QPainterPathStroker, QTransform
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsLineItem, QGraphicsEllipseItem, QGraphicsPathItem,
    QPushButton, QLabel,
    QFileDialog, QMessageBox, QColorDialog, QTableWidgetItem,
    QListWidgetItem, QInputDialog,
    QDialog,
)

from . import __version__
from . import i18n
from .i18n import tr, trf
from .capture_time import winjupos_capture_time
from .ui.theme import STYLE
from .ui.window import WindowUiMixin, label_drag_hint
from .ui.wheel import protect_settings_from_wheel
from .ui.map_layers import (add_map_layers, path_from_segments, GridCaption, ContourLayer, GridLayer,
                            MapCoverage, update_map_coverage, update_map_opacity, prepare_contour_preview)
from .annotation_style import (appearance, caption_typography, placed_caption_typography,
                               caption_text, caption_glyphs, photo_for_style)
from .color_management import display_srgb, srgb_color_space, srgb_profile_bytes
from .map_layers import (MapLayers, grid_lines, sample_elevation, colorize_elevation,
                         elevation_alpha, contour_lines, resolved_contour_interval, build_terminator, legend_rect,
                         photo_lightness)
from .ui.compute import ComputeDialog
from . import compute
from .craters import DetectionOptions, detect_craters, detect_crater_rims
from .identification import identify_from_candidates
from .atlas import identify_from_atlas
from .limb import identify_from_limb
from .terrain_identification import identify_from_terrain
from .guided_identification import identify_from_reference_points, reference_point_errors, reference_point_tolerance
from .terrain_refinement import refine_crater_identification
from .annotation_relief import prepare_annotation_relief
from .geometry import compute_geometry, MOON_RADIUS_KM
from .layout import LabelBox, arrange_labels, leader_segment
from .landing_sites import is_landing_site, landing_marker_radius
from .project import Project, export_svg, DEFAULT_FONT_PERCENT, font_tier_percentages, label_font_families
from .registration import calibration_report, transform_points, auto_register
from .sources import load_catalog, read_image, nasa_reference, refresh_catalog, feature_search_text, COMMON_FEATURES
from .terrain import ElevationMap, download_basic_dem, render_region

ROOT = Path(__file__).resolve().parent.parent


def default_cache():
    """Per-user cache for frozen builds; a source checkout keeps ``.cache`` next to the package."""
    if not getattr(sys, "frozen", False):
        return ROOT / ".cache"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "MoonLabeler" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library/Caches/MoonLabeler"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "MoonLabeler"


CACHE = Path(os.environ.get("MOONLABELER_CACHE", str(default_cache())))


def prepare_cache():
    """Seed shipped JPL kernels without writing inside the application bundle."""
    bundled = ROOT / "bundled_ephemeris"
    if bundled.exists():
        destination = CACHE / "ephemeris"
        destination.mkdir(parents=True, exist_ok=True)
        for source in bundled.iterdir():
            if source.is_file() and not (destination / source.name).exists():
                shutil.copyfile(source, destination / source.name)


def qimage(array):
    array = np.ascontiguousarray(array, dtype=np.uint8)
    h, w = array.shape[:2]
    result = QImage(array.data, w, h, array.strides[0], QImage.Format.Format_RGB888).copy()
    result.setColorSpace(srgb_color_space())
    return result


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(object)  # the exception itself, so OSError paths can be shown verbatim
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.result.emit(self.function())
        except Exception as exc:
            traceback.print_exc()
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()


class Canvas(QGraphicsView):
    point_clicked = Signal(float, float)
    image_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#10151d"))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setAcceptDrops(True)
        self.picking = False
        QPixmapCache.setCacheLimit(max(QPixmapCache.cacheLimit(), 64*1024))
        self._text_worker = None
        self._text_cancel = None
        self._text_timer = QTimer(self)
        self._text_timer.setSingleShot(True)
        self._text_timer.setInterval(180)
        self._text_timer.timeout.connect(self.refine_text_caches)

    def postpone_text_refinement(self):
        if self._text_cancel is not None:
            self._text_cancel.set()
        self._text_timer.start()

    def update_text_caches(self):
        self.postpone_text_refinement()
        transform = self.transform()
        scale = max(math.hypot(transform.m11(), transform.m12()),
                    math.hypot(transform.m21(), transform.m22()))*self.viewport().devicePixelRatioF()
        for item in self.scene().items():
            if isinstance(item, Annotation):
                item.cache_for_view(scale)

    def refine_text_caches(self):
        if self._text_worker is not None:
            return
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        requests = []
        for item in self.scene().items(visible):
            if (isinstance(item, Annotation) and item._cache_size is not None
                    and (item._preview_size != item._cache_size or not QPixmapCache.find(item._preview_key, QPixmap()))):
                requests.append((item, item._cache_size, item._text_revision, item.text_raster_request(item._cache_size)))
        if not requests:
            return
        # Only QImages and immutable path/style snapshots cross threads. Keep
        # the previous pixels at the same scene bounds throughout navigation.
        cancel = self._text_cancel = Event()
        def render_batch():
            results = []
            for item, size, revision, request in requests:
                if cancel.is_set():
                    break
                image = rasterize_caption(*request, cancel)
                if image is not None:
                    results.append((item, size, revision, image))
                # PySide's native glyph painting can hold the GIL. Yield
                # between captions so navigation can cancel an obsolete batch.
                if cancel.wait(.001):
                    break
            return results
        self._text_worker = Worker(render_batch)
        self._text_worker.signals.result.connect(self.text_caches_ready)
        self._text_worker.signals.finished.connect(self.text_caches_finished)
        QThreadPool.globalInstance().start(self._text_worker)

    def text_caches_ready(self, results):
        current = set(self.scene().items())
        for item, size, revision, image in results:
            if item in current and item._cache_size == size and item._text_revision == revision:
                item.install_text_preview(image, size)
                item.update()
            elif item in current:
                self._text_timer.start()

    def text_caches_finished(self):
        interrupted = self._text_cancel.is_set()
        self._text_worker = None
        self._text_cancel = None
        if interrupted:
            self._text_timer.start()
        # A completed batch waits for the next navigation request. Otherwise a
        # viewport exceeding Qt's shared cache budget can refine/evict forever.

    def scrollContentsBy(self, dx, dy):
        # Hand-panning also needs to interrupt refinement, even though it does
        # not change the caption scale. Qt can call this during construction.
        if hasattr(self, '_text_timer'):
            self.postpone_text_refinement()
        super().scrollContentsBy(dx, dy)

    def scale(self, sx, sy):
        super().scale(sx, sy)
        self.update_text_caches()

    def fitInView(self, *args):
        super().fitInView(*args)
        self.update_text_caches()

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        current = self.transform().m11()
        if 0.01 < current * factor < 30:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if self.picking and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            self.point_clicked.emit(point.x(), point.y())
            event.accept()
        else:
            super().mousePressEvent(event)

    def cancel_label_drag(self):
        scene = self.scene()
        item = scene.mouseGrabberItem() if scene is not None else None
        if isinstance(item, Annotation):
            item.end_drag()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Control:
            self.cancel_label_drag()
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.cancel_label_drag()
        super().focusOutEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            event.acceptProposedAction()

    def mouseDoubleClickEvent(self, event):
        # Plain presses on labels pass through to hand-panning. Keep explicit
        # double-click editing even though those presses don't grab the item.
        item = self.itemAt(event.position().toPoint())
        if not self.picking and event.button() == Qt.MouseButton.LeftButton and isinstance(item, Annotation):
            item.edit(item.feature)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        self.image_dropped.emit(event.mimeData().urls()[0].toLocalFile())
        event.acceptProposedAction()


def default_name_language():
    """Name language for a new photo: Traditional names under the Traditional interface."""
    return "双语（繁体）" if i18n.is_traditional() else "双语"


def label_font(pixel_size, project=None, feature=None):
    """CJK-capable label font; bold unless the project asks for normal weight."""
    font = QFont()
    font.setFamilies(label_font_families(project.language if project else "双语",
                                       art_style=project.art_style if project else "standard"))
    font.setPixelSize(pixel_size)
    font.setWeight(QFont.Weight.Normal if project is not None and appearance(project).weight == "normal" else QFont.Weight.Bold)
    if project is not None and feature is not None:
        typography = caption_typography(project, feature)
        font.setItalic(typography.italic)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, typography.tracking*pixel_size)
    return font


def paint_caption(painter, path, halo, halo_width, color, face_width, *, stroke_paths=None, cancel=None):
    for ink, width in ((halo, halo_width), (color, face_width)):
        if width:
            pen = QPen(QColor(ink), width, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            for part in stroke_paths if stroke_paths is not None else (path,):
                if cancel is not None and cancel.wait(.001):
                    return False
                painter.strokePath(part, pen)
    painter.fillPath(path, QColor(color))
    return True


def caption_stroke_paths(path):
    """Batch closed glyph contours without a long, uninterruptible paint call.

    Preserve Bezier curves and paint all halos before the foreground. The fill
    still uses the complete path so counters and overlapping glyphs keep their
    original winding rule. Vector exports continue to use the original path.
    """
    parts, part, index = [], QPainterPath(), 0
    while index < path.elementCount():
        point = path.elementAt(index)
        if point.isMoveTo():
            if not part.isEmpty():
                parts.append(part)
            part = QPainterPath()
            part.moveTo(point.x, point.y)
        elif point.isLineTo():
            part.lineTo(point.x, point.y)
        else:
            control, end = path.elementAt(index+1), path.elementAt(index+2)
            part.cubicTo(point.x, point.y, control.x, control.y, end.x, end.y)
            index += 2
        index += 1
    if not part.isEmpty():
        parts.append(part)
    batches, batch = [], QPainterPath()
    for part in parts:
        if batch.elementCount()+part.elementCount() > 128 and not batch.isEmpty():
            batches.append(batch)
            batch = QPainterPath()
        batch.addPath(part)
    if not batch.isEmpty():
        batches.append(batch)
    return batches


def rasterize_caption(size, bounds, path, halo, halo_width, color, face_width, cancel=None):
    if cancel is not None and cancel.is_set():
        return None
    image = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size[0]/bounds.width(), size[1]/bounds.height())
    painter.translate(-bounds.x(), -bounds.y())
    complete = paint_caption(painter, path, halo, halo_width, color, face_width,
                             stroke_paths=caption_stroke_paths(path), cancel=cancel)
    painter.end()
    return image if complete else None


def caption_path(text, size, font, typography):
    path = QPainterPath()
    glyphs = caption_glyphs(text, size, typography)
    if glyphs:
        for character, x, y, angle in glyphs:
            glyph = QPainterPath()
            glyph.addText(0, 0, font, character)
            path.addPath(QTransform().translate(x, y).rotate(angle).map(glyph))
    else:
        path.addText(0, size, font, text)
    return path


class Annotation(QGraphicsItem):
    MAX_FALLBACK_PIXELS = 65536

    def __init__(self, feature, anchor, text, project, moved, edit, *, font_size=None):
        super().__init__()
        self.feature, self.anchor, self.text = feature, QPointF(*anchor), text
        self.project, self.moved, self.edit = project, moved, edit
        self.font_size = project.font_size if font_size is None else font_size
        self.color = project.label_color(feature)
        self.appearance = appearance(project, landing=is_landing_site(feature))
        self.outline_segments = []
        self.font = label_font(self.font_size, project, feature)
        self.typography = caption_typography(project, feature)
        self.path = caption_path(text, self.font_size, self.font, self.typography)
        if project.art_style in ("topographic", "manuscript"):
            self.path.setFillRule(Qt.FillRule.WindingFill)
        self._curved_path = self._flat_path = self.path
        if self.typography.arc:
            self._flat_path = caption_path(text, self.font_size, self.font,
                                           replace(self.typography, arc=0., positioned=True))
            self._flat_path.setFillRule(self.path.fillRule())
        # Reserve both shapes before collision layout. Flattening at the limb
        # must not expand into a neighboring caption or move a user pin.
        self._layout_bounds = self.padded_bounds(self.path.boundingRect().united(self._flat_path.boundingRect()))
        self._text_revision = 0
        self._view_scale = None
        self._cache_size = self._cache_density = None
        self._preview_size = None
        self._preview_key = QPixmapCache.Key()
        self._fallback_preview = QPixmap()
        self._export_mode = False
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(trf("{hint} · 双击编辑文字", hint=label_drag_hint()))
        self.setZValue(20)
        self.line = QGraphicsLineItem()
        self.line.setPen(QPen(QColor(self.appearance.line), max(1.2, self.font_size*.035)))
        self.line.setZValue(10)
        self.marker = None
        if is_landing_site(feature):
            radius = landing_marker_radius(self.font_size)
            x, y = self.anchor.x(), self.anchor.y()
            for segment in ((x-radius, y, x+radius, y), (x, y-radius, x, y+radius)):
                marker = QGraphicsLineItem(*segment, self.line)
                marker.setPen(QPen(QColor(self.appearance.line), max(1.2, self.font_size*.045)))
        else:
            marker_radius = max(2.5, self.font_size*.06)
            marker = QGraphicsEllipseItem(self.anchor.x()-marker_radius, self.anchor.y()-marker_radius,
                                          marker_radius*2, marker_radius*2, self.line)
            marker.setBrush(QColor(self.color))
            marker.setPen(QPen(Qt.PenStyle.NoPen))
            self.marker = marker
        self.update_map_leader()
        self.update_caption_placement()

    def update_map_leader(self):
        # A saved position is an edit, not a change of cartographic style.
        # Art captions only expose their ordinary locator during a drag.
        permanent = not self.appearance.map_style or is_landing_site(self.feature)
        dragging = self._drag_offset is not None and not self._export_mode
        self.line.setVisible(permanent or dragging)

    def padded_bounds(self, bounds):
        padding = max(5., self.font_size*.04, self.appearance.halo_width(self.font_size)/2+1)
        return bounds.adjusted(-padding, -padding, padding, padding)

    def boundingRect(self):
        return self.padded_bounds(self.path.boundingRect())

    def layout_bounds(self):
        return self._layout_bounds

    def update_caption_placement(self):
        typography = placed_caption_typography(self.project, self.feature, self.text, self.font_size,
                                                (self.pos().x(), self.pos().y()))
        if typography == self.typography:
            return
        self.prepareGeometryChange()
        self.typography = typography
        self.path = self._curved_path if typography.arc else self._flat_path
        self._text_revision += 1
        QPixmapCache.remove(self._preview_key)
        self._preview_size = None
        self._fallback_preview = QPixmap()
        if self._view_scale is not None:
            self.cache_for_view(self._view_scale)
        self.update()
        if self.scene() is not None:
            for view in self.scene().views():
                if isinstance(view, Canvas):
                    view.postpone_text_refinement()

    def cache_for_view(self, scale):
        self._view_scale = scale
        # Reuse oversampled text while zooming within a scale bucket. Repainting
        # every outlined glyph at every wheel step dominates the frame time.
        density = self._cache_density
        # Hysteresis prevents opposite wheel steps near a bucket boundary from
        # discarding the same cache repeatedly. Keep at least 1.5x screen detail.
        if density is None or not 1.5*scale <= density <= 6*scale:
            density = 2**math.ceil(math.log2(max(scale, 1e-6)*2))
        bounds = self.boundingRect()
        size = (max(1, math.ceil(bounds.width()*density)),
                max(1, math.ceil(bounds.height()*density)))
        if size[0]*size[1] > 1_000_000:
            # Keep reusing bounded pixels at extreme zoom. Falling back to
            # complex vector strokes here causes a fresh stall on every frame.
            limit = math.sqrt(1_000_000/(bounds.width()*bounds.height()))
            size = (max(1, int(bounds.width()*limit)), max(1, int(bounds.height()*limit)))
        if self._cache_size != size:
            self._cache_size = size
            self.update()
        self._cache_density = density

    def set_export_mode(self, enabled):
        self._export_mode = enabled
        self.update_map_leader()
        self.update()

    def text_raster_request(self, size):
        return (size, self.boundingRect(), QPainterPath(self.path), self.appearance.halo,
                self.appearance.halo_width(self.font_size), self.color, self.appearance.face_width(self.font_size))

    def install_text_preview(self, image, size):
        preview = QPixmap.fromImage(image)
        QPixmapCache.remove(self._preview_key)
        self._preview_key = QPixmapCache.insert(preview)
        self._preview_size = size
        # Qt may evict a full-resolution preview at any time. Keep a small
        # scene-owned copy so a later wheel/pan frame never has to repaint it.
        scale = min(1., math.sqrt(self.MAX_FALLBACK_PIXELS/(size[0]*size[1])))
        width, height = max(1, int(size[0]*scale)), max(1, int(size[1]*scale))
        if width*height > self._fallback_preview.width()*self._fallback_preview.height():
            self._fallback_preview = preview.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation)

    def paint(self, painter, option, widget=None):
        if self._export_mode or self._cache_size is None:
            self.paint_text(painter)
        else:
            preview = QPixmap()
            if not QPixmapCache.find(self._preview_key, preview):
                if self._fallback_preview.isNull():
                    width, height = self._cache_size
                    scale = min(1., math.sqrt(self.MAX_FALLBACK_PIXELS/(width*height)))
                    size = max(1, int(width*scale)), max(1, int(height*scale))
                    image = rasterize_caption(*self.text_raster_request(size))
                    self.install_text_preview(image, size)
                preview = self._fallback_preview
            # Explicit source/target rectangles keep cache density independent
            # of scene geometry. Qt's custom ItemCoordinateCache size can scale
            # outlined glyphs a second time on some raster paint engines.
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.boundingRect(), preview, QRectF(preview.rect()))
            painter.restore()
        if self.isSelected():
            painter.setPen(QPen(QColor("#88baf3"), 1.))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.boundingRect(), 3., 3.)

    def paint_text(self, painter):
        paint_caption(painter, self.path, self.appearance.halo, self.appearance.halo_width(self.font_size),
                      self.color, self.appearance.face_width(self.font_size))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.update_caption_placement()
            rect = self.boundingRect().translated(self.pos())
            segment = leader_segment((self.anchor.x(), self.anchor.y()), (rect.x(), rect.y(), rect.width(), rect.height()),
                                     outline=self.outline_segments)
            self.line.setLine(*segment)
            self.moved(self.feature["id"], [self.pos().x(), self.pos().y()])
            self.update_map_leader()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.edit(self.feature)
        event.accept()

    def mousePressEvent(self, event):
        self._drag_offset = None
        # Qt ControlModifier is Command on macOS, Ctrl on Windows/Linux:
        # https://doc.qt.io/qt-6/macos-issues.html#special-keys
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._drag_offset = event.scenePos()-self.pos()
            self.scene().clearSelection()
            self.setSelected(True)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update_map_leader()
            event.accept()
        else:
            self.end_drag()
            event.ignore()  # Let ScrollHandDrag pan, even over a label.

    def mouseMoveEvent(self, event):
        if (self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.setPos(event.scenePos()-self._drag_offset)
        else:
            # Releasing the modifier ends this drag; don't jump if re-pressed.
            self.end_drag()
        event.accept()

    def end_drag(self):
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update_map_leader()

    def mouseReleaseEvent(self, event):
        self.end_drag()
        event.accept()


class CraterOverlay(QGraphicsItem):
    """Review aid only; excluded from annotation exports."""
    def __init__(self, candidate, index, selected):
        super().__init__()
        self.candidate, self.index, self.selected_callback = candidate, index, selected
        self.active, self.outline = False, False
        self.setPos(candidate.x, candidate.y)
        self.setZValue(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setToolTip(trf("候选 {number} · 中心 ({x:.1f}, {y:.1f})\n点击选中；请核对坑缘和地名。",
                            number=index+1, x=candidate.x, y=candidate.y))

    def rim_path(self):
        from PySide6.QtGui import QTransform
        c = self.candidate
        path = QPainterPath()
        path.addEllipse(QRectF(-c.major, -c.minor, 2*c.major, 2*c.minor))
        return QTransform().rotate(c.angle).map(path)

    def boundingRect(self):
        return self.rim_path().boundingRect().united(QRectF(-12, -12, 45, 30)).adjusted(-6, -6, 6, 6)

    def shape(self):
        path = QPainterPath()
        path.addEllipse(QRectF(-9, -9, 18, 18))
        if (self.active or self.outline) and self.candidate.method != "manual":
            stroker = QPainterPathStroker()
            stroker.setWidth(10)
            path = path.united(stroker.createStroke(self.rim_path()))
        return path

    def paint(self, painter, option, widget=None):
        pen = QPen(QColor("#ffd287" if self.active else "#79c8cf"), 2. if self.active else 1.)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if (self.active or self.outline) and self.candidate.method != "manual":
            painter.drawPath(self.rim_path())
        painter.drawLine(QPointF(-5, 0), QPointF(5, 0))
        painter.drawLine(QPointF(0, -5), QPointF(0, 5))
        if self.active:
            font = label_font(12)
            path = QPainterPath()
            path.addText(8, -5, font, str(self.index+1))
            shadow = QPen(QColor("#111821"), 2.)
            painter.strokePath(path, shadow)
            painter.fillPath(path, pen.color())

    def mousePressEvent(self, event):
        self.selected_callback(self.index)
        event.accept()




class RecognitionFailure(ValueError):
    """Every automatic registration strategy failed.

    Keeps the underlying exceptions instead of flattening them into one string,
    so :func:`describe_error` can translate the labels while leaving any file
    path inside an OSError untouched. ``str()`` stays the Simplified summary
    used by logs and tracebacks.
    """

    def __init__(self, candidate_count, causes):
        self.candidate_count = candidate_count
        self.causes = list(causes)  # (Simplified label, exception)
        super().__init__(self.render(lambda text: text))

    def __reduce__(self):
        # Exceptions with extra constructor arguments need this to survive pickling.
        return (type(self), (self.candidate_count, self.causes))

    def summary(self):
        """The summary template; :meth:`render` translates it before inserting the count."""
        return "检测到 {count} 个疑似坑缘；未通过自动配准验证。"

    def render(self, translate, describe=str):
        lines = [translate(self.summary()).format(count=self.candidate_count)]
        lines += [translate(label) + describe(cause) for label, cause in self.causes]
        return "\n".join(lines)


def feature_caption(feature):
    """A feature's name for messages in the interface language.

    The English interface shows the official USGS / IAU name; the Chinese
    interfaces show the Chinese caption (converted for Traditional), falling
    back to the official name when no caption is recorded.
    """
    if i18n.is_english():
        return feature["name"]
    return tr(feature.get("name_zh") or feature["name"])


def feature_choice(feature, separator=" · "):
    """A selector entry: the caption, with the official name appended when it differs."""
    caption = feature_caption(feature)
    return caption if caption == feature["name"] else f"{caption}{separator}{feature['name']}"


def describe_error(problem):
    """Translate an error for display.

    Messages raised by MoonLabeler itself are Simplified sentences without
    paths and are translated whole. An OSError carries the offending path
    separately, so only its description is translated and the path(s) are
    appended verbatim; the interface language must never rewrite a file name.
    A :class:`RecognitionFailure` renders each underlying error the same way.
    """
    if isinstance(problem, RecognitionFailure):
        return problem.render(tr, describe_error)
    if isinstance(problem, OSError):
        # Third-party errors (e.g. Pillow) can embed a path in the message
        # without setting filename. Preserve that opaque text verbatim.
        if problem.filename is None:
            return str(problem)
        detail = problem.strerror or type(problem).__name__
        names = [str(problem.filename)]
        if problem.filename2 is not None:
            names.append(str(problem.filename2))
        return tr(detail) + "\n" + "\n".join(names)
    return tr(str(problem))


class MainWindow(WindowUiMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        protect_settings_from_wheel()
        self.setWindowTitle(f"MoonLabeler {__version__} · {tr('月面照片标注')} · ©️Fluorine Zhu（正七价的氟离子）")
        self.resize(1440, 930)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(STYLE)
        self.project = Project(language=default_name_language())
        self.image = None
        self.display_image = None
        self.photo_item = None
        self._photo_display_key = None
        self.catalog = load_catalog(CACHE)
        self.compute_preferences = QSettings(str(CACHE/'preferences.ini'), QSettings.Format.IniFormat)
        compute_mode = self.compute_preferences.value('compute/mode', 'auto')
        compute_mode = compute.normalize_mode(compute_mode)
        compute.set_mode(compute_mode if compute_mode in compute.MODES else 'auto')
        self.catalog_by_id = {f["id"]: f for f in self.catalog}
        self.annotation_items = []
        self.map_items = []
        self.map_layers = MapLayers()
        self._map_display_key = None
        self._terminator_key = self._terminator_result = None
        self._elevation_key = None
        self._elevation_raster = None
        self._elevation_failed_key = None
        self._contour_key = self._contour_render = None
        self._grid_preview_key = self._grid_preview = None
        self._photo_light_key = self._photo_lightness = None
        self._map_layers_pending = False
        self._dem_revision = 0
        self.reference_items = []
        self.crater_items = []
        self.crater_candidates = []
        self.crater_result = None
        self.picking_crater_index = None
        self.picking_id = None
        self.calibration = None
        self.terrain_reference = None
        self.terrain_geometry = None
        self.terrain_dialog = None
        basic = CACHE/"terrain/LDEM_16.LBL"
        self.dem_path = str(basic) if basic.exists() and basic.with_suffix(".IMG").exists() else ""
        self.dirty = False
        self.busy = False
        self.restart_requested = False
        self.project_path = None
        self.rebuilding = False
        self.workers = set()
        self.style_pending = False
        self.pending_color = self.project.color
        self.pending_landing_color = self.project.landing_color
        self.canvas = Canvas()
        self.canvas.point_clicked.connect(self.canvas_point_clicked)
        self.canvas.image_dropped.connect(self.open_image)
        self.build_toolbar()
        self.build_sidebar()
        self.displayed_font_percent = self.font_size.value()
        self.displayed_font_step_percent = self.ui_font_step.value()
        self.update_manual_guide()
        self.statusBar().showMessage(trf("滚轮缩放 · 拖动平移 · {hint}", hint=label_drag_hint()))
        self.empty_hint = self.canvas.scene().addText(tr("打开或拖入照片"), label_font(26))
        self.empty_hint.setDefaultTextColor(QColor("#718399"))
        self.empty_hint.setPos(70, 100)




    def crater_settings_changed(self, *args):
        self.crater_settings_toggle.setText(trf("检测设置 · 半径 {minimum}–{maximum} px",
                                                minimum=self.crater_min.value(), maximum=self.crater_max.value()))
        if self.rebuilding:
            return
        self.project.crater_settings = {"min_radius": self.crater_min.value(), "max_radius": self.crater_max.value(),
                                        "sensitivity": self.crater_sensitivity.value(), "max_candidates": self.crater_limit.value(),
                                        "viewport": self.crater_viewport.isChecked()}
        if self.crater_candidates:
            self.crater_status.setText(tr("参数已改，需重新检测"))
        if self.image is not None:
            self.dirty = True

    def detect_photo_craters(self):
        if self.image is None:
            self.error(tr("请先打开局部月面照片。"))
            return
        options = DetectionOptions(self.crater_min.value(), self.crater_max.value(),
                                    self.crater_sensitivity.value(), self.crater_limit.value())
        if options.max_radius <= options.min_radius:
            self.error(tr("最大半径必须大于最小半径。"))
            return
        self.cancel_pick()
        region = None
        if self.crater_viewport.isChecked():
            rect = self.canvas.mapToScene(self.canvas.viewport().rect()).boundingRect().intersected(self.canvas.sceneRect())
            region = (rect.x(), rect.y(), rect.width(), rect.height())
        image = self.image
        self.run_background(tr("正在本地检测疑似坑中心…"), lambda: detect_craters(image, options, region), self.accept_crater_candidates)

    def identify_photo(self):
        if self.image is None:
            self.error(tr("请先打开月面照片，并选择拍摄日期。默认按当日 UTC 15:00 计算。"))
            return
        if self.busy:
            return
        if not self.ui_capture_inputs_valid():
            self.error(self.ui_capture_error.text())
            return
        self.cancel_pick()
        utc = self.utc()
        lat = self.latitude.value() if self.topocentric.isChecked() else None
        lon = self.longitude.value() if self.topocentric.isChecked() else None
        image, catalog = self.image, list(self.catalog)
        allow_eyepiece = self.project.capture_mode != "direct"
        known = self.manual_reference_points()
        review_candidates = list(self.crater_candidates)
        cached_geometry = self.project.geometry
        # Never feed a previous image-derived correction back into ephemeris
        # matching: repeated recognition must not accumulate view offsets.
        if known or self.project.identification.get("refinement"):
            cached_geometry = None
        def work():
            geometry = cached_geometry or compute_geometry(utc, CACHE / "ephemeris", lat, lon)
            detection = None
            if known:
                detection = detect_crater_rims(image)
                recognition = identify_from_reference_points(image, geometry, CACHE, known, catalog,
                                                             review_candidates + detection.candidates)
            else:
                try:
                    recognition = identify_from_atlas(image, geometry, allow_eyepiece=allow_eyepiece)
                except ValueError as atlas_error:
                    try:
                        recognition = identify_from_limb(image, geometry)
                    except ValueError as limb_error:
                        detection = detect_crater_rims(image)
                        try:
                            recognition = identify_from_candidates(detection.candidates, catalog, geometry, image.shape, image=image)
                            recognition = refine_crater_identification(recognition, image, geometry, CACHE, catalog)
                        except ValueError as exc:
                            try:
                                recognition = identify_from_terrain(image, geometry, CACHE, catalog=catalog)
                            except (ValueError, OSError) as terrain_error:
                                raise RecognitionFailure(len(detection.candidates), [
                                    ("纹理参考：", atlas_error), ("轮廓参考：", limb_error),
                                    ("坑群参考：", exc), ("高程参考：", terrain_error)]) from terrain_error
            if recognition.projection_surface == 'terrain':
                # The accepted automatic relief fit used the basic LOLA map,
                # not an unrelated map currently selected in the preview UI.
                recognition.annotation_relief = prepare_annotation_relief(
                    catalog, recognition.projection_geometry or geometry, recognition.matrix, image.shape, CACHE,
                    lens_distortion=recognition.lens_distortion)
            return detection, recognition, geometry, lat, lon
        def failure(message):
            self.identification_status.setText(tr("参考点配准失败，请核对取点") if known else tr("识别失败，可改用手动校准"))
            self.identification_status.setToolTip(self.error_text(message))
            self.show_crater_review()
            self.error(message)
        self.identification_status.setText(tr("正在按参考点配准…") if known else tr("正在识别…"))
        self.run_background(tr("正在按参考点配准…") if known else tr("正在识别，首次运行需下载参考数据…"),
                            work, self.accept_identification, failure)

    def accept_identification(self, result):
        detection, recognition, geometry, lat, lon = result
        geometry = recognition.projection_geometry or geometry
        # Previous detections are not independent user evidence and must not
        # prevent a newly validated refinement from replacing a coarse pose.
        known = self.manual_reference_points()
        if known:
            try:
                errors = reference_point_errors(recognition.matrix, geometry, known, self.catalog)
                consistent = (errors <= reference_point_tolerance(self.image.shape, recognition.rms_px)).all()
            except ValueError:
                consistent = False
            if not consistent:
                self.identification_status.setText(tr("自动结果与现有参考点不一致，未采用。"))
                self.error(tr("自动识别与现有参考点不一致，已保留原配准。请核对日期和参考点。"))
                return
        self.project.geometry = geometry
        self.project.matrix = recognition.matrix
        self.project.terrain_rims = recognition.crater_rims or {}
        self.project.annotation_relief = recognition.annotation_relief or {}
        self.project.projection_surface = recognition.projection_surface
        self.project.utc = geometry.utc
        self.project.latitude, self.project.longitude = lat, lon
        previous_auto = {a['id']: a for a in self.project.anchors if a.get('source') == 'automatic'}
        self.project.anchors = [a for a in self.project.anchors if a.get('source') != 'automatic']
        existing = {a["id"] for a in self.project.anchors}
        for match in recognition.matches:
            candidate = detection.candidates[match.candidate_index]
            fid = match.feature["id"]
            if fid not in existing:
                enabled = previous_auto.get(fid, {}).get('enabled', True)
                self.project.anchors.append({"id": fid, "pixel": [float(candidate.x), float(candidate.y)], "enabled": enabled, "source": "automatic"})
            # Recognition anchors prove the pose. Lettered satellites should
            # not take layout precedence over the main named formations.
            if match.feature["kind"] == "Crater, craters":
                self.project.labels.setdefault(fid, {})["force"] = True
        if recognition.image_inliers or recognition.limb_inliers:
            self.project.min_diameter = max(5., min(self.project.min_diameter, 15*MOON_RADIUS_KM/np.linalg.norm(recognition.matrix[:, 0])))
        else:
            self.project.min_diameter = min(self.project.min_diameter, 5.)
        self.project.identification = {"method": recognition.method,
                                       "candidate_count": len(detection.candidates) if detection is not None else None,
                                       "matched_names": [m.feature["name"] for m in recognition.matches],
                                       "image_inliers": recognition.image_inliers,
                                       "coverage": recognition.coverage,
                                       "limb_inliers": recognition.limb_inliers,
                                       "texture_correlation": recognition.texture_correlation,
                                       "rms_px": recognition.rms_px}
        if recognition.refinement:
            self.project.identification["refinement"] = recognition.refinement
        if recognition.lens_distortion:
            self.project.identification["lens_distortion"] = recognition.lens_distortion
        if recognition.reference_points:
            self.project.identification["reference_points"] = recognition.reference_points
        # Atlas/limb matches need no crater proposals. Preserve the user's
        # reviewed centres instead of replacing them with unused detections.
        if detection is not None:
            self.accept_crater_candidates(detection)
        self.sync_controls()
        self.show_geometry()
        self.refresh_anchor_table()
        self.refresh_annotations()
        names = [m.feature["name"] for m in recognition.matches if m.feature["kind"] == "Crater, craters"]
        if recognition.reference_points:
            message = trf("参考点辅助配准 · {confirmed} 个已确认点 · {inliers} 个图像对应点 · 覆盖 {coverage:.1%}。圈为目录参考轮廓",
                          confirmed=len(recognition.reference_points['reference_ids']),
                          inliers=recognition.image_inliers, coverage=recognition.coverage)
        elif recognition.lens_distortion:
            message = trf("目镜畸变校正 · {inliers} 个图像对应点 · 月缘偏差（95%）{limb:.1f} px",
                          inliers=recognition.image_inliers, limb=recognition.refinement['limb_p95_px'])
        elif recognition.limb_inliers:
            message = trf("月盘外缘与月海纹理配准成功 · 纹理相关 {correlation:.2f} · 外缘拟合偏差 {rms:.2f} px",
                          correlation=recognition.texture_correlation, rms=recognition.rms_px)
        elif recognition.refinement and recognition.matches:
            message = trf("坑群识别后精修 · {inliers} 个图像对应点 · 覆盖 {coverage:.1%} · 拟合偏差 {rms:.2f} px。大坑优先使用高程坑缘，轮廓精度受数据分辨率限制",
                          inliers=recognition.image_inliers, coverage=recognition.coverage, rms=recognition.rms_px)
        elif recognition.method.startswith("LOLA"):
            message = trf("已定位月面区域 · {inliers} 个图像对应点 · 覆盖 {coverage:.1%} · 拟合偏差 {rms:.2f} px",
                          inliers=recognition.image_inliers, coverage=recognition.coverage, rms=recognition.rms_px)
            message += tr("。大坑使用高程参考轮廓") if recognition.crater_rims else tr("。圈为目录参考轮廓，尚未贴合实际坑缘")
            if recognition.refinement:
                message += tr("。观测方向微调已通过分区验证")
        elif recognition.image_inliers:
            message = trf("纹理配准成功 · {inliers} 个图像对应点 · 拟合偏差 {rms:.2f} px",
                          inliers=recognition.image_inliers, rms=recognition.rms_px)
        else:
            message = trf("识别到 {names} 等 {count} 处地形 · 拟合偏差 {rms:.2f} px",
                          names=tr("、").join(tr(name) for name in names[:4]), count=len(recognition.matches),
                          rms=recognition.rms_px)
        self.identification_status.setText(trf("{result} · 拟合偏差 {rms:.2f} px",
                                               result=tr("参考点辅助配准完成") if recognition.reference_points else tr("配准完成"),
                                               rms=recognition.rms_px))
        details = message + tr("。拟合偏差只反映一致性，不代表绝对定位精度。")
        self.identification_status.setToolTip(details)
        self.registration_status.setText("")
        self.workspace_tabs.setCurrentIndex(1)
        self.statusBar().showMessage(tr("配准完成"))
        self.dirty = True

    def clear_crater_candidates(self):
        for item in self.crater_items:
            self.canvas.scene().removeItem(item)
        self.crater_items = []
        self.crater_candidates = []
        self.crater_result = None
        self.crater_list.clear()
        self.crater_feature.setCurrentRow(-1)
        self.crater_status.setText(tr("未检测"))
        self.update_crater_buttons()

    def accept_crater_candidates(self, result):
        self.clear_crater_candidates()
        self.crater_result = result
        self.crater_candidates = list(result.candidates)
        self.refresh_crater_candidates()
        count = len(self.crater_candidates)
        message = trf("{count} 个候选", count=count) if count else tr("未找到候选，可调整检测参数")
        if result.scale < .99:
            message += tr(" · 已缩小检测")
        self.crater_status.setText(message)
        self.statusBar().showMessage(tr("检测完成") if count else tr("未找到候选"))
        if count:
            self.ui_scroll_to_crater_controls()

    def refresh_crater_candidates(self, selected_index=0):
        for item in self.crater_items:
            self.canvas.scene().removeItem(item)
        self.crater_items = []
        self.crater_list.blockSignals(True)
        self.crater_list.clear()
        for index, candidate in enumerate(self.crater_candidates):
            row = QListWidgetItem(trf("{number:02d}   ({x:.0f}, {y:.0f})   ·   半径 {radius:.0f} px",
                                      number=index+1, x=candidate.x, y=candidate.y, radius=(candidate.major+candidate.minor)/2))
            row.setToolTip((tr("EDCircles 坑缘拟合；还需核对是否为真实环形山。") if candidate.method == "edge-drawing" else tr("中心已手动调整。")) if candidate.support is None else
                           trf("长/短半轴 {major:.1f} / {minor:.1f} px；方向 {angle:.1f}°\n边缘支持度 {support:.2f}，用于排序，不是正确率。",
                               major=candidate.major, minor=candidate.minor, angle=candidate.angle, support=candidate.support))
            self.crater_list.addItem(row)
            overlay = CraterOverlay(candidate, index, self.crater_list.setCurrentRow)
            self.canvas.scene().addItem(overlay)
            self.crater_items.append(overlay)
        if self.crater_candidates:
            self.crater_list.setCurrentRow(selected_index)
        self.crater_list.blockSignals(False)
        self.show_crater_overlays()
        self.update_crater_buttons()

    def select_crater_candidate(self, index):
        if self.picking_crater_index is not None and index != self.picking_crater_index:
            self.cancel_pick()
        # A name is a deliberate choice for this candidate, not a sticky
        # search result that may silently be assigned to the next crater.
        self.crater_feature.clearSelection()
        self.crater_feature.setCurrentRow(-1)
        self.show_crater_overlays()
        self.update_crater_buttons()

    def review_page_changed(self, *args):
        self.cancel_pick()
        self.show_crater_overlays()

    def registration_page_changed(self, *args):
        self.ui_set_manual_section_expanded(True)
        self.review_page_changed()

    def show_crater_overlays(self, *args):
        visible = (self.workspace_tabs.currentIndex() == 0
                   and self.registration_tabs.currentWidget() == self.crater_tab
                   and self.ui_manual_section_expanded()
                   and not self.ui_manual_pick_toggle.isChecked())
        if hasattr(self, "crater_action_panel"):
            self.crater_action_panel.setVisible(visible)
        for index, item in enumerate(self.crater_items):
            item.active = index == self.crater_list.currentRow()
            item.outline = self.crater_overlay_toggle.isChecked()
            item.setVisible(visible)
            item.update()
        for item in self.reference_items:
            item.setVisible(self.workspace_tabs.currentIndex() == 0 and (not visible or self.ui_reference_toggle.isChecked()))

    def update_crater_buttons(self, *args):
        selected = 0 <= self.crater_list.currentRow() < len(self.crater_candidates)
        self.crater_remove.setEnabled(selected)
        self.crater_repick.setEnabled(selected)
        self.crater_export.setEnabled(bool(self.crater_candidates))
        name_item = self.crater_feature.currentItem()
        fid = name_item.data(Qt.ItemDataRole.UserRole) if name_item is not None else None
        self.crater_anchor_button.setEnabled(selected and fid is not None)
        operation = tr("更新参考点") if fid is not None and any(a["id"] == fid for a in self.project.anchors) else tr("加入参考点")
        self.crater_anchor_button.setText(trf("确认候选 {number:02d}，{operation}", number=self.crater_list.currentRow()+1, operation=operation)
                                          if selected else tr("确认地名，加入参考点"))
        self.ui_refresh_crater_review()

    def search_crater_features(self, text):
        normalized = lambda value: "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))
        query = normalized(text.strip())
        blocked = self.crater_feature.blockSignals(True)
        self.crater_feature.clear()
        # Require a deliberate name search, rather than defaulting to the
        # largest unrelated formation and encouraging an accidental assignment.
        if query:
            matches = [f for f in self.catalog if f["kind"] in ("Crater, craters", "Satellite Feature") and query in normalized(feature_search_text(f))]
            matches.sort(key=lambda f: (normalized(f["name"]) != query, -f["diameter"]))
            for feature in matches[:100]:
                item = QListWidgetItem(feature_choice(feature))
                item.setData(Qt.ItemDataRole.UserRole, feature["id"])
                item.setToolTip(item.text())
                self.crater_feature.addItem(item)
        self.crater_feature.setCurrentRow(-1)
        self.crater_feature.blockSignals(blocked)
        self.update_crater_buttons()

    def use_crater_candidate(self):
        index = self.crater_list.currentRow()
        name_item = self.crater_feature.currentItem()
        fid = name_item.data(Qt.ItemDataRole.UserRole) if name_item is not None else None
        if not 0 <= index < len(self.crater_candidates) or fid is None:
            return
        feature = self.catalog_by_id[fid]
        if self.project.geometry is not None:
            _, visible, _ = self.project.geometry.project([feature["lat"]], [feature["lon"]])
            if not visible[0]:
                self.error(tr("此地形位于月球背面。请核对拍摄时间或地形名称。"))
                return
        self.picking_id = fid
        candidate = self.crater_candidates[index]
        self.add_anchor(candidate.x, candidate.y)
        self.update_crater_buttons()
        self.crater_status.setText(trf("已确认候选 {number:02d}：{name}", number=index+1, name=feature_caption(feature)))
        self.statusBar().showMessage(self.crater_status.text())

    def remove_crater_candidate(self):
        self.cancel_pick()
        index = self.crater_list.currentRow()
        if 0 <= index < len(self.crater_candidates):
            self.crater_candidates.pop(index)
            self.crater_feature.clearSelection()
            self.crater_feature.setCurrentRow(-1)
            self.refresh_crater_candidates()
            self.crater_status.setText(trf("保留 {count} 个候选", count=len(self.crater_candidates)))

    def repick_crater_candidate(self):
        index = self.crater_list.currentRow()
        if 0 <= index < len(self.crater_candidates):
            self.cancel_pick()
            self.picking_crater_index = index
            self.canvas.picking = True
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.statusBar().showMessage(trf("点击候选 {number} 的坑中心 · Esc 取消", number=index+1))

    def canvas_point_clicked(self, x, y):
        if self.picking_crater_index is None:
            self.add_anchor(x, y)
            return
        index = self.picking_crater_index
        if self.image is None or not (0 <= x < self.image.shape[1] and 0 <= y < self.image.shape[0]):
            return
        if not 0 <= index < len(self.crater_candidates):
            self.cancel_pick()
            return
        self.crater_candidates[index] = replace(self.crater_candidates[index], x=x, y=y, support=None, method="manual")
        self.cancel_pick()
        self.refresh_crater_candidates(selected_index=index)
        self.crater_status.setText(trf("候选 {number} 中心已更新", number=index+1))

    def export_crater_candidates(self):
        if not self.crater_candidates:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("导出疑似坑候选"), self.suggest_export_path("crater-candidates", "csv"), tr("CSV (*.csv)"))
        if path:
            try:
                with open(path if path.lower().endswith(".csv") else path+".csv", "w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["image", "candidate", "center_x_px", "center_y_px", "semimajor_px", "semiminor_px", "angle_deg", "edge_support", "method"])
                    for index, c in enumerate(self.crater_candidates):
                        writer.writerow([Path(self.project.image_path).name, index+1, f"{c.x:.3f}", f"{c.y:.3f}", f"{c.major:.3f}", f"{c.minor:.3f}", f"{c.angle:.3f}", "" if c.support is None else f"{c.support:.3f}", c.method])
                self.statusBar().showMessage(tr("CSV 已保存"))
            except OSError as exc:
                self.error(exc)

    def run_background(self, title, function, success, failure=None, *, allow_canvas=False):
        if self.busy:
            return
        self.busy = True
        self.sidebar.setEnabled(False)
        self.toolbar.setEnabled(False)
        self.canvas.setEnabled(allow_canvas)
        self.statusBar().showMessage(title)
        worker = Worker(function)
        self.workers.add(worker)
        worker.signals.result.connect(success)
        worker.signals.error.connect(failure or self.error)
        def finished():
            self.busy = False
            self.sidebar.setEnabled(True)
            self.toolbar.setEnabled(True)
            self.canvas.setEnabled(True)
            self.workers.discard(worker)
            if self._map_layers_pending:
                self._map_layers_pending = False
                QTimer.singleShot(0, self.refresh_annotations)
        worker.signals.finished.connect(finished)
        QThreadPool.globalInstance().start(worker)

    def choose_ui_language(self):
        if self.busy:
            return
        from .ui.language import LanguageDialog
        # Preselect the saved preference: a change that is waiting for a restart must not be
        # silently reverted by reopening the dialog and pressing OK.
        saved = i18n.normalize(self.compute_preferences.value(i18n.PREFERENCE_KEY)) or i18n.current_language()
        dialog = LanguageDialog(saved, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        code = dialog.selected()
        self.compute_preferences.setValue(i18n.PREFERENCE_KEY, code)
        self.compute_preferences.sync()
        if code == i18n.current_language():
            return
        answer = QMessageBox.question(self, "MoonLabeler", tr("界面语言将在重新启动后生效。现在重新启动 MoonLabeler？"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.restart_requested = True
            self.close()

    def error(self, problem):
        """Report a failure; ``problem`` is an exception or a Simplified message string."""
        self.statusBar().showMessage(tr("操作未完成。"))
        QMessageBox.warning(self, "MoonLabeler", self.error_text(problem))

    error_text = staticmethod(describe_error)

    def sync_capture_time(self, *args):
        # date remains the single timestamp source for geometry and projects.
        # The disclosure only changes visibility, never the selected time.
        time = self.date.time()
        blocked = self.capture_time.blockSignals(True)
        self.capture_time.setTime(time)
        self.capture_time.blockSignals(blocked)
        self.ui_update_time_summary()

    def utc(self):
        # Treat displayed components as UTC, independent of host timezone.
        dt = self.date.dateTime()
        day, time = dt.date(), dt.time()
        return datetime(day.year(), day.month(), day.day(), time.hour(), time.minute(), time.second(), tzinfo=timezone.utc)

    def geometry_changed(self, *args):
        if self.rebuilding:
            return
        self.cancel_pick()
        self.project.utc = self.utc().isoformat()
        self.project.latitude = self.latitude.value() if self.topocentric.isChecked() else None
        self.project.longitude = self.longitude.value() if self.topocentric.isChecked() else None
        self.project.geometry = None
        self.project.matrix = None
        self.project.identification.clear()
        self.project.terrain_rims.clear()
        self.project.annotation_relief.clear()
        self.project.projection_surface = 'sphere'
        self.project.labels.clear()
        self.clear_terrain_preview()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.geometry_status.setText(tr("待重新计算"))
        self.identification_status.setText(tr("拍摄条件已改，需重新校准"))
        self.identification_status.setToolTip("")
        self.registration_status.setText(tr("待重新校准"))
        if self.image is not None:
            self.dirty = True

    def capture_mode_changed(self, *args):
        if self.rebuilding:
            return
        self.project.capture_mode = self.capture_mode.currentData()
        # This is a search policy, not a change to the current photo geometry.
        # Keep the validated result and all edits until a new result is accepted.
        if self.image is not None:
            self.dirty = True
            self.identification_status.setText(tr("拍摄方式已改，下次识别生效"))
            self.identification_status.setToolTip("")

    def calculate_geometry(self, checked=False, *, after=None):
        if not self.ui_capture_inputs_valid():
            self.error(self.ui_capture_error.text())
            return
        utc = self.utc()
        lat = self.latitude.value() if self.topocentric.isChecked() else None
        lon = self.longitude.value() if self.topocentric.isChecked() else None
        def success(geometry):
            self.project.geometry = geometry
            self.project.utc = utc.isoformat()
            self.project.latitude, self.project.longitude = lat, lon
            self.project.matrix = None
            self.project.identification.clear()
            self.project.terrain_rims.clear()
            self.project.annotation_relief.clear()
            self.project.projection_surface = 'sphere'
            self.clear_terrain_preview()
            self.show_geometry()
            self.refresh_anchor_table()
            self.refresh_annotations()
            self.dirty = True
            self.statusBar().showMessage(tr("月面几何已计算"))
            if after is not None:
                after()
        self.run_background(tr("计算月面几何…"),
                            lambda: compute_geometry(utc, CACHE / "ephemeris", lat, lon), success)

    def show_geometry(self):
        if self.project.geometry:
            lat, lon = self.project.geometry.libration
            label = tr("投影视角（图像微调）") if self.project.identification.get("refinement") else tr("天平动")
            self.geometry_status.setText(trf("{label}：纬度 {lat:+.3f}°，经度 {lon:+.3f}°", label=label, lat=lat, lon=lon))

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, tr("保存工程"), tr("当前工程有未保存的修改。"), QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def open_image(self, path=None):
        if self.busy or not self.confirm_discard():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, tr("打开月面照片"), "", tr("图像 (*.png *.jpg *.jpeg *.tif *.tiff *.fits *.fit *.fts)"))
        if not path:
            return
        try:
            image = read_image(path)
            display_image = display_srgb(image, path)
            filename_utc = winjupos_capture_time(path)
            self.project = Project(image_path=str(Path(path).resolve()), utc=(filename_utc or self.utc()).isoformat(),
                                   language=default_name_language())
            self.project_path = None
            self.set_image(image, display_image=display_image)
            self.sync_controls()
            self.ui_reset_for_new_photo()
            self.dirty = False
            self.geometry_status.setText(tr("未计算"))
            self.registration_status.setText(tr("未配准"))
            self.identification_status.setText(tr("未识别"))
            self.identification_status.setToolTip("")
            # Translate the template first, then insert the file name so it is never rewritten.
            timestamp = trf(" · 文件名时间：{utc:%Y-%m-%d %H:%M:%S} UTC", utc=filename_utc) if filename_utc else ""
            self.statusBar().showMessage(trf("{name} · {w} × {h} 像素{timestamp}", name=Path(path).name,
                                             w=image.shape[1], h=image.shape[0], timestamp=timestamp))
        except Exception as exc:
            self.error(exc)

    def set_image(self, image, *, display_image=None):
        if display_image is None:
            display_image = display_srgb(image, self.project.image_path)
        self.clear_terrain_preview()
        self.clear_crater_candidates()
        self.image = image
        self.display_image = display_image
        self.project.update_font_size(image.shape)
        self.update_font_hint()
        self.annotation_items = []
        self.map_items = []
        self.map_layers = MapLayers()
        self._map_display_key = self._elevation_key = self._elevation_failed_key = None
        self._terminator_key = self._terminator_result = None
        self._elevation_raster = None
        self._contour_key = self._contour_render = None
        self._grid_preview_key = self._grid_preview = None
        self._photo_light_key = self._photo_lightness = None
        self.reference_items = []
        self.canvas.scene().clear()
        self.photo_item = self.canvas.scene().addPixmap(QPixmap.fromImage(qimage(photo_for_style(display_image, self.project.art_style))))
        self.photo_item.setZValue(0)
        self._photo_display_key = (id(image), self.project.art_style != "standard")
        h, w = image.shape[:2]
        self.canvas_title.setText(Path(self.project.image_path).name or tr("月面照片"))
        self.canvas_details.setText(trf("{w:,} × {h:,} px   ·   滚轮缩放 · {hint} · 双击编辑文字", w=w, h=h, hint=label_drag_hint()))
        self.canvas.scene().setSceneRect(QRectF(0, 0, w, h))
        self.cancel_pick()
        self.refresh_anchor_table()
        self.refresh_annotations()
        # Startup projects load before the window has its final viewport size.
        QTimer.singleShot(0, self.fit_canvas)

    def fit_canvas(self):
        if self.image is not None:
            self.canvas.fitInView(self.canvas.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def open_project(self, path=None):
        if self.busy or not self.confirm_discard():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, tr("打开工程"), "", tr("MoonLabeler (*.moonlabel)"))
        if not path:
            return
        try:
            project = Project.load(path)
            if not Path(project.image_path).exists():
                replacement, _ = QFileDialog.getOpenFileName(self, tr("原始照片已移动，请重新选择"))
                if not replacement:
                    return
                project.image_path = str(Path(replacement).resolve())
            image = read_image(project.image_path)
            display_image = display_srgb(image, project.image_path)
            self.project = project
            self.project.update_font_size(image.shape)
            self.project_path = Path(path)
            self.sync_controls()
            self.set_image(image, display_image=display_image)
            self.show_geometry()
            self.identification_status.setToolTip("")
            self.registration_status.setText(tr("已配准") if project.matrix is not None else tr("未配准"))
            if project.identification and project.matrix is not None:
                names = project.identification.get("matched_names", [])
                if project.identification.get("image_inliers"):
                    self.identification_status.setText(tr("已配准"))
                    self.identification_status.setToolTip(trf("{inliers} 个图像对应点；标注由目录坐标投影得到。",
                                                              inliers=project.identification['image_inliers']))
                else:
                    self.identification_status.setText(tr("已识别"))
                    self.identification_status.setToolTip("、".join(names[:4]))
            else:
                self.identification_status.setText(tr("未识别"))
            self.dirty = False
            self.statusBar().showMessage(trf("已打开 {name}", name=Path(path).name))
        except Exception as exc:
            self.error(exc)

    def save_project(self):
        if self.image is None:
            self.error(tr("请先打开照片。"))
            return False
        path, _ = QFileDialog.getSaveFileName(self, tr("保存工程"), str(self.project_path or Path(self.project.image_path).with_suffix(".moonlabel")), tr("MoonLabeler (*.moonlabel)"))
        if not path:
            return False
        if not path.endswith(".moonlabel"):
            path += ".moonlabel"
        try:
            self.project.save(path)
            self.project_path = Path(path)
            self.dirty = False
            self.statusBar().showMessage(trf("已保存 {name}", name=Path(path).name))
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def sync_controls(self):
        self.rebuilding = True
        self.capture_mode.setCurrentIndex(self.capture_mode.findData(self.project.capture_mode))
        self.topocentric.setChecked(self.project.latitude is not None)
        self.latitude.setValue(self.project.latitude or 0.)
        self.longitude.setValue(self.project.longitude or 0.)
        if self.project.utc:
            dt = datetime.fromisoformat(self.project.utc).astimezone(timezone.utc)
            self.date.setDateTime(QDateTime.fromString(dt.isoformat(), Qt.DateFormat.ISODate))
        self.kind.setCurrentIndex(max(0, self.kind.findData(self.project.kind)))
        self.diameter.setValue(self.project.min_diameter)
        self.maximum.setValue(self.project.max_labels)
        self.language.setCurrentIndex(max(0, self.language.findData(self.project.language)))
        percent = self.project.font_percent or DEFAULT_FONT_PERCENT
        # Legacy pixel-size projects can lie outside today's editing range.
        # Loading them must not silently clamp the stored font proportion.
        self.font_size.setRange(min(.05, percent), max(8., percent))
        self.font_size.setValue(percent)
        self.displayed_font_percent = self.font_size.value()
        self.ui_font_step.setRange(0., max(8., self.project.font_step_percent))
        self.ui_font_step.setValue(self.project.font_step_percent)
        self.displayed_font_step_percent = self.ui_font_step.value()
        self.lit.setChecked(self.project.illuminated_only)
        self.landing_sites_toggle.setChecked(self.project.show_landing_sites)
        self.pending_landing_color = self.project.landing_color
        self.landing_color_button.setToolTip(trf("着陆点颜色：{color}；使用小档字号", color=self.pending_landing_color))
        self.optimize_layout.setChecked(self.project.optimize_layout)
        self.crater_outlines.setChecked(self.project.crater_outlines)
        self.crater_outline_shape.setCurrentIndex(self.crater_outline_shape.findData(self.project.crater_outline_shape))
        self.font_weight.setCurrentIndex(max(0, self.font_weight.findData(self.project.font_weight)))
        self.art_style.setCurrentIndex(max(0, self.art_style.findData(self.project.art_style)))
        self.grid_spacing.setCurrentIndex(self.grid_spacing.findData(self.project.grid_spacing))
        self.grid_opacity.setValue(round(self.project.grid_opacity*100))
        self.elevation_toggle.setChecked(self.project.elevation_enabled)
        self.elevation_opacity.setValue(round(self.project.elevation_opacity*100))
        self.elevation_palette.setCurrentIndex(self.elevation_palette.findData(self.project.elevation_palette))
        self.contour_toggle.setChecked(self.project.contour_enabled)
        self.contour_interval.setCurrentIndex(self.contour_interval.findData(self.project.contour_interval))
        self.contour_opacity.setValue(round(self.project.contour_opacity*100))
        self.terminator_toggle.setChecked(self.project.terminator_enabled)
        self.terminator_opacity.setValue(round(self.project.terminator_opacity*100))
        self.terminator_source.setCurrentIndex(self.terminator_source.findData(self.project.terminator_source))
        self.map_light_toggle.setChecked(self.project.map_light_mask)
        self.pending_map_light_threshold = self.project.map_light_threshold
        self.update_map_light_hint()
        self.map_styles_toggle.setChecked(self.project.art_style != "standard" or bool(self.project.grid_spacing)
                                         or self.project.elevation_enabled or self.project.contour_enabled
                                         or self.project.terminator_enabled)
        self.update_map_controls()
        self.pending_color = self.project.color
        self.color_button.setText(trf("文字与引线颜色：{color}", color=self.pending_color))
        self.style_pending = False
        self.settings_status.setText("")
        self.update_font_hint()
        if self.project.terrain_path:
            self.dem_path = self.project.terrain_path
        self.dem_status.setText(Path(self.dem_path).name if self.dem_path else tr("尚未选择高程数据"))
        settings = self.project.terrain_settings
        center_id = settings.get("center_id")
        if center_id in self.catalog_by_id:
            self.terrain_search.setText(self.catalog_by_id[center_id]["name"])
            self.terrain_center.setCurrentIndex(self.terrain_center.findData(center_id))
        self.terrain_width.setValue(settings.get("width_km", 300))
        self.terrain_size.setCurrentText(str(settings.get("size", 768)))
        self.terrain_model.setCurrentText(settings.get("model", "Lommel-Seeliger"))
        self.terrain_gamma.setValue(settings.get("gamma", 1.6))
        self.terrain_shadows.setChecked(settings.get("shadows", True))
        settings = self.project.crater_settings
        self.crater_min.setValue(settings.get("min_radius", 8))
        self.crater_max.setValue(settings.get("max_radius", 180))
        self.crater_sensitivity.setValue(settings.get("sensitivity", 50))
        self.crater_limit.setValue(settings.get("max_candidates", 80))
        self.crater_viewport.setChecked(settings.get("viewport", False))
        self.search_crater_features(self.crater_search.text())
        self.rebuilding = False

    def search_features(self, text):
        def normalized(value):
            return "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                           if not unicodedata.combining(char))
        text = normalized(text.strip())
        self.feature_list.clear()
        matches = [f for f in self.catalog if text in normalized(feature_search_text(f))]
        matches.sort(key=lambda f: f["diameter"], reverse=True)
        for f in matches[:100]:
            item = QListWidgetItem(f"{feature_choice(f, '  ·  ')}  ({f['diameter']:.0f} km)")
            item.setData(Qt.ItemDataRole.UserRole, f["id"])
            self.feature_list.addItem(item)
        self.update_manual_guide()

    def manual_selection_changed(self, *args):
        # A changed search result must never leave an old name armed on canvas.
        self.cancel_pick()

    def manual_reference_points(self):
        return [dict(a, pixel=list(a['pixel'])) for a in self.project.anchors
                if a.get('enabled', True) and a.get('source') != 'automatic' and a['id'] in self.catalog_by_id]

    def update_manual_guide(self, *args):
        count = sum(a.get("enabled", True) for a in self.project.anchors)
        known_count = len(self.manual_reference_points())
        required = 3 if self.mirror.currentIndex() == 0 else 2
        self.anchor_count.setText(trf("{count} 个有效参考点", count=count) + (tr(" · 可尝试自动配准") if known_count else ""))
        self.solve_button.setToolTip(trf("至少 {required} 个分散、不共线的参考点。", required=required))
        self.solve_button.setEnabled(self.image is not None and count >= required and not self.canvas.picking)
        self.guided_identify_button.setEnabled(self.image is not None and known_count > 0 and not self.canvas.picking)
        item = self.feature_list.currentItem()
        picking = self.canvas.picking and self.picking_id is not None
        self.cancel_pick_button.setVisible(picking)
        self.pick_button.setEnabled(self.image is not None and item is not None and not self.canvas.picking)
        if self.image is None:
            message = tr("请打开照片")
        elif picking:
            feature = self.catalog_by_id[self.picking_id]
            message = trf("{name}：点击照片中的坑中心", name=feature_caption(feature))
        elif count >= required:
            message = tr("可校准，也可继续取点")
        elif known_count:
            message = trf("可尝试自动配准；手动校准还需 {missing} 个点", missing=required-count)
        else:
            message = trf("还需 {missing} 个参考点", missing=required-count)
        self.manual_guide.setText(message)
        if picking:
            self.pick_button.setText(tr("点击照片中的坑中心…"))
        elif item is not None:
            feature = self.catalog_by_id[item.data(Qt.ItemDataRole.UserRole)]
            self.pick_button.setText(trf("在照片中标记：{name}", name=feature_caption(feature)))
        else:
            self.pick_button.setText(tr("选择地名后取点"))

    def show_manual_points(self):
        self.ui_crater_scroll_timer.stop()
        self.workspace_tabs.setCurrentIndex(0)
        self.registration_tabs.setCurrentWidget(self.crater_tab)
        self.ui_set_manual_section_expanded(True)
        self.ui_reference_toggle.setChecked(True)
        target = self.guided_identify_button if self.guided_identify_button.isEnabled() else self.anchor_table
        self.ui_scroll_to_reference_points(target)

    def show_crater_review(self):
        self.workspace_tabs.setCurrentIndex(0)
        self.registration_tabs.setCurrentWidget(self.crater_tab)
        self.ui_set_manual_section_expanded(True)
        self.ui_scroll_to_crater_controls()

    def start_pick(self):
        if self.image is None:
            self.error(tr("请先打开照片。"))
            return
        item = self.feature_list.currentItem()
        if item is None:
            self.error(tr("请先搜索并选择一个已知地形。"))
            return
        self.workspace_tabs.setCurrentIndex(0)
        self.ui_set_manual_section_expanded(True)
        self.ui_manual_pick_toggle.setChecked(True)
        self.cancel_pick()
        self.picking_id = item.data(Qt.ItemDataRole.UserRole)
        self.canvas.picking = True
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        self.canvas.setFocus()
        self.update_manual_guide()
        self.statusBar().showMessage(self.manual_guide.text())
        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.cancel_pick_button)
                          if self.canvas.picking else None)

    def cancel_pick(self):
        was_picking = self.canvas.picking
        self.picking_crater_index = None
        self.picking_id = None
        self.canvas.picking = False
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        self.update_manual_guide()
        if was_picking:
            self.statusBar().showMessage(tr("已取消取点"))

    def add_anchor(self, x, y):
        if self.picking_id not in self.catalog_by_id or self.image is None or not (0 <= x < self.image.shape[1] and 0 <= y < self.image.shape[0]):
            return
        # Re-clicking a named anchor updates it instead of adding duplicates.
        self.project.anchors = [a for a in self.project.anchors if a["id"] != self.picking_id]
        self.project.anchors.append({"id": self.picking_id, "pixel": [x, y], "enabled": True})
        self.project.matrix = None
        self.project.identification.clear()
        self.project.labels.clear()
        self.cancel_pick()
        self.feature_list.setCurrentRow(-1)
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.registration_status.setText("")
        self.statusBar().showMessage(self.manual_guide.text())
        self.dirty = True
        if self.workspace_tabs.currentIndex() == 0 and self.ui_manual_pick_toggle.isChecked():
            self.ui_manual_pick_toggle.setChecked(False)
            self.show_manual_points()

    def refresh_anchor_table(self):
        enabled = [a for a in self.project.anchors if a.get("enabled", True)]
        self.calibration = None
        diagnostics = {}
        if self.project.geometry and self.project.matrix is not None and enabled:
            try:
                features = [self.catalog_by_id[a["id"]] for a in enabled]
                predicted = self.project.annotation_points(features)[0]
                target = np.array([a["pixel"] for a in enabled])
                actual_errors = np.linalg.norm(predicted-target, axis=1)
                diagnostics = {a["id"]: (error, float("nan"), False) for a, error in zip(enabled, actual_errors)}
                if len(enabled) >= 2 and not self.project.identification.get("lens_distortion"):
                    inverse = np.linalg.inv(np.vstack((self.project.matrix, [0., 0., 1.])))[:2]
                    source = transform_points(inverse, predicted)
                    self.calibration = calibration_report(source, target, ["auto", "no", "yes"][self.mirror.currentIndex()])
                    diagnostics = {a["id"]: (error, self.calibration.check_errors_px[i], i == self.calibration.suspect_index)
                                   for i, (a, error) in enumerate(zip(enabled, actual_errors))}
            except (ValueError, KeyError):
                pass
        self.anchor_table.blockSignals(True)
        self.anchor_table.setRowCount(len(self.project.anchors))
        for index, anchor in enumerate(self.project.anchors):
            feature = self.catalog_by_id.get(anchor["id"])
            name = feature_caption(feature) if feature else anchor["id"]
            checked = QTableWidgetItem()
            checked.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            checked.setCheckState(Qt.CheckState.Checked if anchor.get("enabled", True) else Qt.CheckState.Unchecked)
            error, check, suspect = diagnostics.get(anchor["id"], (None, float("nan"), False))
            values = [checked, QTableWidgetItem(f"{index+1}. {name}"), QTableWidgetItem(f"{error:.2f}" if error is not None else "—")]
            tooltip = trf("中心：X {x:.1f}，Y {y:.1f}", x=anchor['pixel'][0], y=anchor['pixel'][1])
            if np.isfinite(check):
                tooltip += trf("\n留出该点后，其他点预测它的偏差：{check:.2f} px", check=check)
            if suspect:
                tooltip += tr("\n建议核对此点；停用后可重新配准。程序没有自动删除它。")
            for col, item in enumerate(values):
                item.setToolTip(tooltip)
                if suspect:
                    item.setForeground(QColor("#ffb36b"))
                self.anchor_table.setItem(index, col, item)
        self.anchor_table.blockSignals(False)
        self.refresh_reference_markers()
        self.update_manual_guide()

    def anchor_enabled_changed(self, item):
        if item.column() != 0 or self.rebuilding:
            return
        self.project.anchors[item.row()]["enabled"] = item.checkState() == Qt.CheckState.Checked
        self.invalidate_registration()

    def repick_anchor(self, row, column=0):
        if self.image is None or row >= len(self.project.anchors):
            return
        anchor = self.project.anchors[row]
        feature = self.catalog_by_id.get(anchor["id"])
        if not feature:
            return
        self.feature_search.setText(feature["name"])
        for index in range(self.feature_list.count()):
            if self.feature_list.item(index).data(Qt.ItemDataRole.UserRole) == feature["id"]:
                self.feature_list.setCurrentRow(index)
                break
        self.canvas.centerOn(*anchor["pixel"])
        self.start_pick()

    def refresh_reference_markers(self):
        scene = self.canvas.scene()
        for item in self.reference_items:
            scene.removeItem(item)
        self.reference_items = []
        if self.image is None:
            return
        for number, anchor in enumerate(self.project.anchors, 1):
            x, y = anchor["pixel"]
            color = "#75d6d6" if anchor.get("enabled", True) else "#718399"
            pen = QPen(QColor(color), 1.5)
            for coords in ((-8,0,8,0), (0,-8,0,8)):
                item = scene.addLine(*coords, pen)
                item.setPos(x, y)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                item.setZValue(30)
                self.reference_items.append(item)
            text = scene.addText(str(number))
            text.setDefaultTextColor(QColor(color))
            text.setPos(x, y)
            text.setHtml(f'<span style="background-color:#111821;color:{color}">&nbsp;{number}&nbsp;</span>')
            text.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            text.setZValue(30)
            self.reference_items.append(text)
            if self.project.matrix is not None and self.project.geometry and anchor.get("enabled", True):
                feature = self.catalog_by_id.get(anchor["id"])
                if feature:
                    predicted = self.project.annotation_points([feature])[0][0]
                    if np.linalg.norm(predicted-[x, y]) > 1:
                        line = scene.addLine(x, y, *predicted, QPen(QColor("#ffb36b"), 1.5, Qt.PenStyle.DashLine))
                        line.setZValue(30)
                        self.reference_items.append(line)
        self.show_crater_overlays()

    def remove_anchor(self):
        row = self.anchor_table.currentRow()
        if row < 0:
            return
        self.project.anchors.pop(row)
        self.invalidate_registration()

    def clear_anchors(self):
        self.project.anchors.clear()
        self.invalidate_registration()

    def invalidate_registration(self):
        self.cancel_pick()
        self.project.matrix = None
        self.project.identification.clear()
        self.project.terrain_rims.clear()
        self.project.annotation_relief.clear()
        self.project.projection_surface = 'sphere'
        self.project.labels.clear()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.registration_status.setText("")
        self.dirty = True

    def solve_manual(self):
        if not self.ui_capture_inputs_valid():
            self.error(self.ui_capture_error.text())
            return
        anchors = [a for a in self.project.anchors if a.get("enabled", True)]
        required = 3 if self.mirror.currentIndex() == 0 else 2
        if self.image is None or len(anchors) < required:
            self.error(trf("请先添加至少 {required} 个已知环形山的参考点，尽量分散且不共线。", required=required))
            return
        if self.project.geometry is None:
            self.calculate_geometry(after=self.solve_manual)
            return
        self.cancel_pick()
        try:
            anchors = [a for a in self.project.anchors if a.get("enabled", True)]
            if len(anchors) < 2:
                raise ValueError(tr("请先在照片上添加至少两个已知环形山中心；建议三处以上，以判断镜像和检查配准误差。"))
            features = [self.catalog_by_id[a["id"]] for a in anchors]
            points, visible, _ = self.project.geometry.project([f["lat"] for f in features], [f["lon"] for f in features])
            if not np.all(visible):
                raise ValueError(tr("参考点包含背面地形，请核对地形和拍摄时间。"))
            report = calibration_report(points, [a["pixel"] for a in anchors], ["auto", "no", "yes"][self.mirror.currentIndex()])
            # Start with a coarse sphere fit to bound the DEM snapshot. Then
            # fit the SAME elevated/visual anchors the display will use; simply
            # adding heights after a manual fit would count relief twice.
            relief = prepare_annotation_relief(self.catalog, self.project.geometry, report.matrix, self.image.shape,
                                               CACHE, dem_path=self.dem_path)
            if relief:
                provisional = Project(geometry=self.project.geometry, matrix=report.matrix,
                                      annotation_relief=relief, projection_surface='terrain',
                                      crater_outline_shape=self.project.crater_outline_shape)
                predicted = provisional.annotation_points(features)[0]
                inverse = np.linalg.inv(np.vstack((report.matrix, [0., 0., 1.])))[:2]
                points = transform_points(inverse, predicted)
                report = calibration_report(points, [a['pixel'] for a in anchors],
                                             ["auto", "no", "yes"][self.mirror.currentIndex()])
            matrix, rms = report.matrix, report.rms_px
            self.project.matrix = matrix
            self.project.identification.clear()
            self.project.terrain_rims.clear()
            self.project.annotation_relief = relief
            self.project.projection_surface = 'terrain' if relief else 'sphere'
            self.project.labels.clear()
            mirrored = np.linalg.det(matrix[:, :2]) < 0
            warning = tr("；两点无法自动判断镜像，也无法独立评估误差") if len(features) == 2 else ""
            if report.suspect_index is not None:
                warning += trf("；请核对 {name}（表中橙色）", name=tr(features[report.suspect_index]['name']))
            self.registration_status.setText(trf("{count} 个参考点 · 残差 {rms:.2f} px · {mirror}{warning}", count=len(features), rms=rms,
                                                 mirror=tr('镜像') if mirrored else tr('不镜像'), warning=warning))
            self.refresh_anchor_table()
            self.refresh_annotations()
            self.workspace_tabs.setCurrentIndex(1)
            self.statusBar().showMessage(tr("校准完成"))
            self.dirty = True
        except Exception as exc:
            self.error(exc)

    def accept_auto(self, result, *, reference_project=None):
        match, geometry, matrix, reference_utc, latitude, longitude = result
        self.project.geometry = geometry
        self.project.matrix = matrix
        self.project.utc = reference_utc
        self.project.latitude, self.project.longitude = latitude, longitude
        self.project.anchors.clear()
        self.project.identification.clear()
        self.project.terrain_rims.clear()
        self.project.annotation_relief.clear()
        self.project.projection_surface = 'sphere'
        if reference_project is not None:
            # Composing the photo transform does not change the reference
            # project's geographic surface or its sampled heights.
            self.project.projection_surface = reference_project.projection_surface
            self.project.terrain_rims = dict(reference_project.terrain_rims)
            self.project.annotation_relief = dict(reference_project.annotation_relief)
        self.project.labels.clear()
        self.sync_controls()
        self.show_geometry()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.registration_status.setText(trf("自动匹配：{inliers}/{matches} 个内点 · 残差 {rms:.2f} px · {mirror}", inliers=match.inliers,
                                             matches=match.matches, rms=match.rms_px, mirror=tr('镜像') if match.mirrored else tr('不镜像')))
        self.statusBar().showMessage(tr("配准完成"))
        self.dirty = True

    def auto_nasa(self):
        if self.image is None:
            self.error(tr("请先打开照片。"))
            return
        if self.topocentric.isChecked():
            self.error(tr("NASA 参考使用地心视角。请取消“使用拍摄地点”，或用地形参考点做站心配准。"))
            return
        utc, photo = self.utc(), self.image.copy()
        def work():
            reference, geometry, matrix, _ = nasa_reference(utc, CACHE)
            match = auto_register(reference, photo)
            composed = (np.vstack((match.matrix, [0.,0.,1.])) @ np.vstack((matrix,[0.,0.,1.])))[:2]
            return match, geometry, composed, utc.isoformat(), None, None
        self.run_background(tr("下载 NASA 同时刻影像并匹配…"), work, self.accept_auto, self.nasa_failed)

    def nasa_failed(self, text):
        self.show_crater_review()
        self.registration_status.setText(tr("NASA 配准失败，可用手动校准"))
        self.error(text)

    def auto_local(self):
        if self.image is None:
            self.error(tr("请先打开照片。"))
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("选择同一拍摄时刻的已校准参考工程"), str(ROOT / "examples"), tr("MoonLabeler (*.moonlabel)"))
        if not path:
            return
        try:
            reference_project = Project.load(path)
            if reference_project.identification.get("lens_distortion"):
                raise ValueError(tr("此参考工程含目镜畸变校正，请对当前照片使用自动识别。"))
            if reference_project.matrix is None or reference_project.geometry is None:
                raise ValueError(tr("参考工程未配准"))
            delta = abs((datetime.fromisoformat(reference_project.utc) - self.utc()).total_seconds())
            if delta > 3600:
                raise ValueError(tr("参考工程与当前拍摄时间相差超过一小时，请先设置为相同拍摄时刻。不同日期的天平动不能用同一平面变换处理。"))
            photo, requested_utc = self.image.copy(), self.utc().isoformat()
            def work():
                reference = read_image(reference_project.image_path)
                match = auto_register(reference, photo)
                composed = (np.vstack((match.matrix, [0.,0.,1.])) @ np.vstack((reference_project.matrix,[0.,0.,1.])))[:2]
                return match, reference_project.geometry, composed, requested_utc, reference_project.latitude, reference_project.longitude
            self.run_background(tr("正在匹配本地参考照片…"), work,
                                lambda result: self.accept_auto(result, reference_project=reference_project))
        except Exception as exc:
            self.error(exc)

    def terrain_parameters(self):
        return {"center_id": self.terrain_center.currentData(), "width_km": self.terrain_width.value(),
                "size": int(self.terrain_size.currentText()), "model": self.terrain_model.currentText(),
                "gamma": self.terrain_gamma.value(), "shadows": self.terrain_shadows.isChecked()}

    def terrain_settings_changed(self, *args):
        if self.rebuilding:
            return
        self.project.terrain_path = self.dem_path
        self.project.terrain_settings = self.terrain_parameters()
        self.clear_terrain_preview()
        if self.image is not None:
            self.dirty = True

    def search_terrain_features(self, text):
        def normalized(value):
            return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))
        query = normalized(text.strip())
        features = sorted((f for f in self.catalog if query in normalized(feature_search_text(f))),
                          key=lambda f: f["diameter"], reverse=True)
        self.terrain_center.blockSignals(True)
        self.terrain_center.clear()
        for feature in features[:100]:
            self.terrain_center.addItem(feature_choice(feature), feature["id"])
        self.terrain_center.blockSignals(False)
        if hasattr(self, "terrain_shadows"):
            self.terrain_settings_changed()

    @staticmethod
    def dem_metadata(path):
        dem = ElevationMap.load(path)
        try:
            return str(Path(path).resolve()), dem.name, dem.resolution_km
        finally:
            dem.close()

    def accept_dem(self, result):
        self.dem_path, name, resolution = result
        self.dem_status.setText(trf("{name} · 赤道采样约 {resolution:.3f} km", name=name, resolution=resolution))
        self.dem_status.setToolTip(self.dem_path)
        if self.project.matrix is None:
            self.project.annotation_relief.clear()
            self._annotation_relief_attempt = None
        self.terrain_settings_changed()
        self._dem_revision += 1
        self._elevation_failed_key = None
        self.refresh_annotations()
        self.statusBar().showMessage(tr("高程数据已加载"))

    def import_dem(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("选择 LOLA 柱面 DEM 标签"), str(Path(self.dem_path).parent if self.dem_path else CACHE),
                                                tr("月面高程 (*.lbl *.LBL *.img *.IMG *.npz)"))
        if path:
            self.run_background(tr("读取 DEM 元数据…"), lambda: self.dem_metadata(path), self.accept_dem)

    def download_dem(self):
        def work():
            return self.dem_metadata(download_basic_dem(CACHE))
        self.run_background(tr("下载 LOLA 高程数据 · 约 33 MB…"), work, self.accept_dem)

    def clear_terrain_preview(self):
        self.terrain_reference = None
        self.terrain_geometry = None
        if self.terrain_dialog:
            self.terrain_dialog.close()
            self.terrain_dialog.deleteLater()
            self.terrain_dialog = None

    def generate_terrain(self):
        if not self.dem_path or not Path(self.dem_path).exists():
            self.error(tr("请先导入本地 DEM，或下载基础 LOLA 高程数据。"))
            return
        parameters = self.terrain_parameters()
        feature = self.catalog_by_id.get(parameters.pop("center_id"))
        if not feature:
            self.error(tr("请搜索并选择照片中的已知区域。"))
            return
        utc = self.utc()
        lat = self.latitude.value() if self.topocentric.isChecked() else None
        lon = self.longitude.value() if self.topocentric.isChecked() else None
        geometry, path = self.project.geometry, self.dem_path
        self.project.terrain_path = path
        self.project.terrain_settings = self.terrain_parameters()
        def work():
            current = geometry or compute_geometry(utc, CACHE/"ephemeris", lat, lon)
            dem = ElevationMap.load(path)
            try:
                reference = render_region(dem, current, feature["lat"], feature["lon"], **parameters)
                return reference, current, utc.isoformat(), lat, lon
            finally:
                dem.close()
        self.run_background(tr("生成模拟图…"), work, self.accept_terrain_reference)

    def accept_terrain_reference(self, result):
        reference, geometry, utc, lat, lon = result
        self.clear_terrain_preview()
        self.terrain_reference, self.terrain_geometry = reference, geometry
        self.project.geometry = geometry
        self.project.utc, self.project.latitude, self.project.longitude = utc, lat, lon
        self.show_geometry()
        if self.image is not None:
            self.dirty = True
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("DEM 模拟"))
        dialog.resize(900, 880)
        layout = QVBoxLayout(dialog)
        note = QLabel(trf("{utc} · 视野 {width:.0f} km · 采样 {resolution:.3f} km", utc=utc,
                          width=reference.width_km, resolution=reference.resolution_km))
        note.setToolTip(tr("球面光照模拟，未加入反照率纹理；细节和阴影可能与实拍不同。"))
        note.setWordWrap(True)
        layout.addWidget(note)
        preview = Canvas()
        preview.scene().addPixmap(QPixmap.fromImage(qimage(reference.image)))
        preview.scene().setSceneRect(QRectF(0, 0, reference.image.shape[1], reference.image.shape[0]))
        layout.addWidget(preview)
        row = QHBoxLayout()
        save = QPushButton(tr("保存模拟图与参考工程"))
        save.clicked.connect(self.save_terrain_reference)
        match = QPushButton(tr("匹配当前照片"))
        match.setEnabled(self.image is not None)
        match.clicked.connect(self.match_terrain_reference)
        close = QPushButton(tr("关闭预览"))
        close.clicked.connect(dialog.close)
        row.addWidget(save)
        row.addWidget(match)
        row.addWidget(close)
        layout.addLayout(row)
        self.terrain_dialog = dialog
        dialog.show()
        QTimer.singleShot(0, lambda: preview.fitInView(preview.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio))
        self.statusBar().showMessage(tr("模拟完成"))

    def save_terrain_reference(self):
        if self.terrain_reference is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("保存 DEM 模拟与参考工程"), self.suggest_export_path("dem-reference", "png"), tr("PNG (*.png)"))
        if not path:
            return
        try:
            from PIL import Image
            path = Path(path if path.lower().endswith(".png") else path+".png")
            Image.fromarray(self.terrain_reference.image).save(path, icc_profile=srgb_profile_bytes())
            project = Project(image_path=str(path.resolve()), utc=self.terrain_geometry.utc,
                              geometry=self.terrain_geometry, matrix=self.terrain_reference.matrix,
                              latitude=self.project.latitude, longitude=self.project.longitude,
                              terrain_path=self.dem_path, terrain_settings=self.terrain_parameters(), min_diameter=5,
                              language=default_name_language())
            project.save(path.with_suffix(".moonlabel"))
            self.statusBar().showMessage(trf("已保存 {name} 和对应参考工程。", name=path.name))
        except Exception as exc:
            self.error(exc)

    def match_terrain_reference(self):
        if self.image is None or self.terrain_reference is None:
            return
        reference, geometry = self.terrain_reference, self.terrain_geometry
        # Upsampling a coarse DEM cannot create the detail needed for SIFT.
        if reference.width_km/reference.resolution_km < 64:
            self.error(tr("这个视野内不足 64 个地形采样点，细节不足以自动匹配。请导入更高分辨率 DEM，或用地形点校准。"))
            return
        photo = self.image.copy()
        def work():
            match = auto_register(reference.image, photo)
            matrix = (np.vstack((match.matrix, [0., 0., 1.])) @ np.vstack((reference.matrix, [0., 0., 1.])))[:2]
            return match, geometry, matrix
        self.run_background(tr("匹配 DEM 参考图…"), work, self.accept_terrain_match)

    def accept_terrain_match(self, result):
        match, geometry, matrix = result
        # Known user clicks are a separate check on a synthetic-image match.
        anchors = [a for a in self.project.anchors if a.get("enabled", True)]
        if len(anchors) >= 3:
            features = [self.catalog_by_id[a["id"]] for a in anchors]
            points, _, _ = geometry.project([f["lat"] for f in features], [f["lon"] for f in features])
            errors = np.linalg.norm(transform_points(matrix, points)-[a["pixel"] for a in anchors], axis=1)
            previous = np.linalg.norm(self.project.photo_points(points)-[a["pixel"] for a in anchors], axis=1) if self.project.matrix is not None else np.array([0.])
            if np.median(errors) > max(6., 2*np.median(previous)):
                self.error(tr("DEM 匹配与已有地形点不一致，未采用该结果。请核对区域、时间或数据分辨率。"))
                return
        self.project.geometry, self.project.matrix = geometry, matrix
        self.project.identification.clear()
        self.project.terrain_rims.clear()
        self.project.annotation_relief.clear()
        self.project.projection_surface = 'sphere'
        self.project.labels.clear()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.registration_status.setText(trf("DEM 配准 · {inliers}/{matches} 个内点 · 残差 {rms:.2f} px",
                                             inliers=match.inliers, matches=match.matches, rms=match.rms_px))
        self.registration_status.setToolTip(tr("辅助匹配，需用已知地形复核。"))
        self.statusBar().showMessage(tr("DEM 配准完成"))
        self.dirty = True

    def about_dialog(self):
        text = trf("MoonLabeler {version}\n\n"
                          "作者：Fluorine Zhu\n开源许可：GNU GPL v3.0 或更新版本\n\n"
                          "致敬 Jim Mosher 与 Henrik Bondo 创建的 Lunar Terminator Visualization Tool。"
                          "本程序参考其地形点校准与 DEM 光照思路，使用 Python / Qt 独立实现。\n\n"
                          "感谢樊仕达（10deg）提供 moonlib 代码参考及 LPND 中文地名资料。\n\n"
                          "感谢蔡明翰（{evan_tsai}）贡献繁体中文支持及 Windows 部分问题修复。\n\n"
                          "地名：USGS / IAU；中文译名优先采用 LPND，补录来源单独保留。\n"
                          "月面高程：LRO / LOLA；星历：JPL DE421；着陆点：NASA NSSDCA / LROC。\n"
                          "疑似坑检测改编自 Ram Maruboina 的 Lunar Crater Detector（MIT）。\n"
                          "来源和模型限制见项目目录的 ACKNOWLEDGEMENTS.md 与 README.md。", version=__version__,
                          evan_tsai='<a href="https://www.facebook.com/mjrt.mj">Evan Tsai</a>')
        QMessageBox.about(self, tr("关于 MoonLabeler"), text.replace("\n", "<br>"))

    def style_changed(self, *args):
        if self.rebuilding:
            return
        self.style_pending = True
        self.update_font_hint()
        self.settings_status.setText(tr("设置已改，需重新生成"))

    def map_opacity_changed(self, field, value):
        if self.rebuilding:
            return
        applied = {"grid_opacity": bool(self.project.grid_spacing),
                   "elevation_opacity": self.project.elevation_enabled,
                   "contour_opacity": self.project.contour_enabled,
                   "terminator_opacity": self.project.terminator_enabled}[field]
        if not applied:
            self.style_changed()
            return
        setattr(self.project, field, value/100)
        if (field == "elevation_opacity" and self.map_layers.elevation is not None and
                self._elevation_key == self.map_sampling_key()):
            self.map_layers.elevation[:, :, 3] = elevation_alpha(self._elevation_raster, self.project)
        update_map_opacity(self.map_items, self.map_layers, self.project, field)
        self._map_display_key = None
        if self.image is not None:
            self.dirty = True
        if not self.style_pending:
            self.settings_status.setText(tr("已更新"))

    def current_photo_lightness(self):
        if self.image is None:
            return None
        key = self.map_sampling_key() or (id(self.image),)
        if key != self._photo_light_key:
            self._photo_lightness = photo_lightness(self.project, self.image)
            self._photo_light_key = key
        return self._photo_lightness

    def update_map_light_hint(self):
        automatic = self.pending_map_light_threshold == "auto"
        field = self.current_photo_lightness() if automatic else None
        value = field.automatic_threshold if field is not None else 1 if automatic else self.pending_map_light_threshold
        rebuilding, self.rebuilding = self.rebuilding, True
        try:
            self.map_light_threshold.setValue(value)
            self.map_light_readout.setValue(value)
            self.map_light_auto.setChecked(automatic)
        finally:
            self.rebuilding = rebuilding

    def map_light_threshold_changed(self, value):
        if not self.rebuilding:
            self.pending_map_light_threshold = value
            self.apply_map_light_controls()

    def reset_map_light_threshold(self):
        if not self.rebuilding:
            self.pending_map_light_threshold = "auto"
            self.apply_map_light_controls()

    def apply_map_light_controls(self, *args):
        if self.rebuilding:
            return
        self.update_map_light_hint()
        p = self.project
        if not (p.grid_spacing or p.elevation_enabled or p.contour_enabled):
            self.style_changed()
            return
        p.map_light_mask = self.map_light_toggle.isChecked()
        p.map_light_threshold = self.pending_map_light_threshold
        self.refresh_map_coverage()
        update_map_coverage(self.map_items, self.map_layers.coverage)
        self.update_grid_captions()
        self._map_display_key = None
        if self.image is not None:
            self.dirty = True
        if not self.style_pending:
            self.settings_status.setText(tr("已更新"))

    def refresh_map_coverage(self):
        self.map_layers.coverage = self.map_layers.light_threshold = None
        if self.project.map_light_mask:
            field = self.current_photo_lightness()
            if field is not None:
                self.map_layers.coverage, self.map_layers.light_threshold = field.coverage(self.project.map_light_threshold)
        self.update_map_light_hint()

    def update_font_hint(self):
        percentages = font_tier_percentages(self.font_size.value(), self.ui_font_step.value())
        if self.ui_font_step.value() == 0:
            hint = tr("统一字号")
            if self.image is not None:
                hint += trf(" · 原图 {pixels} px", pixels=max(6, round(min(self.image.shape[:2])*percentages[0]/100)))
        else:
            hint = tr("大 / 中 / 小：")+" / ".join(f"{percent:.2f}%" for percent in percentages)
            if self.image is not None:
                pixels = [max(6, round(min(self.image.shape[:2])*percent/100)) for percent in percentages]
                hint += tr("\n原图 ")+" / ".join(map(str, pixels))+" px"
        self.font_pixels_hint.setText(hint)

    def apply_label_settings(self):
        if self.busy:
            return
        if self.font_size.value() != self.displayed_font_percent:
            self.project.font_percent = self.font_size.value()
        if self.ui_font_step.value() != self.displayed_font_step_percent:
            self.project.font_step_percent = self.ui_font_step.value()
        for key, value in (("min_diameter", self.diameter.value()), ("kind", self.kind.currentData()),
                           ("max_labels", self.maximum.value()), ("language", self.language.currentData()),
                           ("font_weight", self.font_weight.currentData()),
                           ("art_style", self.art_style.currentData()),
                           ("grid_spacing", self.grid_spacing.currentData()),
                           ("grid_opacity", self.grid_opacity.value()/100),
                           ("elevation_enabled", self.elevation_toggle.isChecked()),
                           ("elevation_opacity", self.elevation_opacity.value()/100),
                           ("elevation_palette", self.elevation_palette.currentData()),
                           ("contour_enabled", self.contour_toggle.isChecked()),
                           ("contour_interval", self.contour_interval.currentData()),
                           ("contour_opacity", self.contour_opacity.value()/100),
                           ("terminator_enabled", self.terminator_toggle.isChecked()),
                           ("terminator_opacity", self.terminator_opacity.value()/100),
                           ("terminator_source", self.terminator_source.currentData()),
                           ("map_light_mask", self.map_light_toggle.isChecked()),
                           ("map_light_threshold", self.pending_map_light_threshold),
                           ("illuminated_only", self.lit.isChecked()),
                           ("show_landing_sites", self.landing_sites_toggle.isChecked()),
                           ("landing_color", self.pending_landing_color),
                           ("optimize_layout", self.optimize_layout.isChecked()),
                           ("crater_outlines", self.crater_outlines.isChecked()),
                           ("crater_outline_shape", self.crater_outline_shape.currentData()), ("color", self.pending_color)):
            setattr(self.project, key, value)
        if (self.project.elevation_enabled or self.project.contour_enabled) and self.dem_path:
            self.project.terrain_path = self.dem_path
        if self._elevation_failed_key is not None:
            self._map_display_key = None
        self._elevation_failed_key = None
        if self.image is not None:
            self.project.update_font_size(self.image.shape)
        self.refresh_annotations()
        self.displayed_font_percent = self.font_size.value()
        self.displayed_font_step_percent = self.ui_font_step.value()
        self.style_pending = False
        self.settings_status.setText(tr("已更新"))
        if self.image is not None:
            self.dirty = True

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.pending_color), self)
        if color.isValid():
            self.pending_color = color.name()
            self.color_button.setText(trf("文字与引线颜色：{color}", color=self.pending_color))
            self.style_changed()

    def choose_landing_color(self):
        color = QColorDialog.getColor(QColor(self.pending_landing_color), self)
        if color.isValid():
            self.pending_landing_color = color.name()
            self.landing_color_button.setToolTip(trf("着陆点颜色：{color}；使用小档字号", color=self.pending_landing_color))
            self.style_changed()

    def move_label(self, fid, position):
        if not self.rebuilding:
            self.project.labels.setdefault(fid, {})["position"] = position
            self.dirty = True
            self.update_grid_captions()

    def update_grid_captions(self):
        # Feature names have priority over coordinate captions. Keep the same
        # visibility in the SVG, including after the user drags a name.
        bounds = [item.sceneBoundingRect() for item in self.annotation_items]
        if self.map_layers.elevation is not None or self.map_layers.contours is not None:
            bounds.append(QRectF(*legend_rect(self.image.shape)))
        coverage = next((item.coverage_path for item in self.map_items if isinstance(item, MapCoverage)), None)
        for item in self.map_items:
            if isinstance(item, GridCaption):
                visible = not any(item.sceneBoundingRect().intersects(rect) for rect in bounds)
                if self.map_layers.coverage is not None and coverage is not None:
                    visible = visible and coverage.contains(item.sceneBoundingRect())
                item.setVisible(visible)
                item.grid_line.show_label = visible

    def map_sampling_key(self):
        """Snapshot of all projection inputs; cosmetic changes reuse sampled heights."""
        p = self.project
        if self.image is None or p.geometry is None or p.matrix is None:
            return None
        return (id(p), id(self.image), self.image.shape[:2], p.matrix.tobytes(),
                json.dumps(p.geometry.to_dict(), sort_keys=True), p.projection_surface,
                json.dumps(p.identification.get("lens_distortion"), sort_keys=True),
                p.terrain_path or self.dem_path, self._dem_revision)

    def refresh_map_layers(self):
        p = self.project
        key = self.map_sampling_key() if p.grid_spacing or p.elevation_enabled or p.contour_enabled or p.terminator_enabled else None
        display_key = (key, p.art_style, p.grid_spacing, p.grid_opacity, p.elevation_enabled,
                       p.elevation_palette, p.elevation_opacity,
                       p.contour_enabled, p.contour_interval, p.contour_opacity,
                       p.terminator_enabled, p.terminator_opacity, p.terminator_source,
                       p.map_light_mask, p.map_light_threshold)
        if display_key == self._map_display_key:
            return
        for item in self.map_items:
            self.canvas.scene().removeItem(item)
        self.map_items = []
        self.map_layers = MapLayers()
        self.refresh_map_coverage()
        self._map_display_key = display_key
        self.set_map_layer_status()
        self.set_map_layer_status(terminator=True)
        auto_index = self.contour_interval.findData("auto")
        self.contour_interval.setItemText(auto_index, tr("自动"))
        if key is None:
            if p.grid_spacing or p.elevation_enabled or p.contour_enabled or p.terminator_enabled:
                self.set_map_layer_status(tr("配准后可叠加经纬网、高程图与晨昏线。"))
            return
        self.map_layers.grid = grid_lines(p, self.image.shape)
        if p.terminator_enabled:
            terminator_key = (key, p.terminator_source)
            if self._terminator_key != terminator_key:
                self._terminator_result = build_terminator(p, self.image.shape, image=self.image)
                self._terminator_key = terminator_key
            self.map_layers.terminator, self.map_layers.terminator_unreliable = self._terminator_result
            if self.map_layers.terminator_unreliable:
                self.set_map_layer_status(tr("照片内未找到可靠的晨昏交界，未绘制。可选择工程时间的理论线，或关闭晨昏线。"), terminator=True)
        preview = None
        if p.elevation_enabled or p.contour_enabled:
            raster = self._elevation_raster if key == self._elevation_key else None
            contour_key = (key, p.art_style, p.contour_interval)
            if raster is not None:
                if p.elevation_enabled:
                    self.map_layers.elevation = colorize_elevation(raster, p, image=self.image)
                if p.contour_enabled:
                    interval = resolved_contour_interval(raster, p)
                    self.map_layers.contour_interval = interval
                    if p.contour_interval == "auto":
                        self.contour_interval.setItemText(auto_index, trf("自动（{interval:g} km）", interval=interval))
                    if contour_key == self._contour_key:
                        self.map_layers.contours, preview = self._contour_render
            needs_work = raster is None or (p.contour_enabled and self.map_layers.contours is None)
            if needs_work and key != self._elevation_failed_key:
                source = p.terrain_path or self.dem_path
                if not source:
                    self.set_map_layer_status(tr("高程图需要 DEM：请导入或下载基础 LOLA 高程数据。"))
                elif self.busy:
                    self._map_layers_pending = True
                    self._map_display_key = None
                else:
                    snapshot, shape = replace(p, matrix=p.matrix.copy()), self.image.shape
                    def work():
                        sampled = raster
                        if sampled is None:
                            dem = ElevationMap.load(source)
                            try:
                                sampled = sample_elevation(snapshot, shape, dem)
                            finally:
                                dem.close()
                        lines = contour_lines(sampled, snapshot, shape) if snapshot.contour_enabled else None
                        prepared = prepare_contour_preview(snapshot, shape, lines) if lines else None
                        return sampled, lines, prepared
                    def ready(result):
                        if self.map_sampling_key() != key:
                            return
                        raster, lines, prepared = result
                        self._elevation_key, self._elevation_raster = key, raster
                        if snapshot.contour_enabled:
                            self._contour_key, self._contour_render = contour_key, (lines, prepared)
                        self._map_display_key = None
                        self.refresh_map_layers()
                        self.update_grid_captions()
                        self.statusBar().showMessage(tr("高程图已更新"))
                    def failed(exc):
                        self._elevation_failed_key = key
                        self.set_map_layer_status(tr("高程图未生成，请检查 DEM 后重新生成；已有标注保留。"))
                        self.error(exc)
                    self.set_map_layer_status(tr("正在生成高程图…"))
                    self.run_background(tr("正在生成高程图…"), work, ready, failed, allow_canvas=True)
            elif needs_work:
                self.set_map_layer_status(tr("高程图未生成，请检查 DEM 后重新生成；已有标注保留。"))
        grid_key = (key, p.art_style, p.grid_spacing)
        grid_preview = self._grid_preview if grid_key == self._grid_preview_key else None
        self.map_items = add_map_layers(self.canvas.scene(), p, self.image.shape, self.map_layers,
                                        contour_preview=preview, grid_preview=grid_preview)
        self._grid_preview = next((item.prepared for item in self.map_items if isinstance(item, GridLayer)), None)
        self._grid_preview_key = grid_key

    def check_map_export(self):
        if self.project.terminator_enabled and self.map_layers.terminator_unreliable:
            raise ValueError(tr("照片内未找到可靠的晨昏交界；请选择工程时间的理论线，或关闭晨昏线再导出。"))
        if self.project.contour_enabled and (self.map_layers.contours is None or
                self._contour_key != (self.map_sampling_key(), self.project.art_style, self.project.contour_interval)):
            raise ValueError(tr("等高线尚未生成；请先生成或关闭等高线再导出。"))
        if self.project.elevation_enabled and (self.map_layers.elevation is None or
                                               self._elevation_key != self.map_sampling_key()):
            raise ValueError(tr("高程图尚未生成；请先生成或关闭高程着色再导出。"))

    def refresh_annotations(self):
        self.rebuilding = True
        scene = self.canvas.scene()
        if self.image is not None and self.photo_item is not None:
            photo_key = (id(self.image), self.project.art_style != "standard")
            if photo_key != self._photo_display_key:
                self.photo_item.setPixmap(QPixmap.fromImage(qimage(photo_for_style(self.display_image, self.project.art_style))))
                self._photo_display_key = photo_key
        self.refresh_map_layers()
        for item in self.annotation_items:
            scene.removeItem(item.line)
            scene.removeItem(item)
        self.annotation_items = []
        self.auto_omitted = set()
        self.names.clear()
        if self.image is None:
            self.layout_status.setText("")
            self.rebuilding = False
            return
        if (self.project.projection_surface == 'terrain' and self.project.geometry is not None and
                self.project.matrix is not None and not self.project.annotation_relief):
            # Recognition prepares this in its worker. Legacy/manual projects
            # sample a local map once, without downloads or retained handles.
            key = (id(self.project), id(self.project.geometry), self.project.matrix.tobytes(), self.dem_path)
            if key != getattr(self, '_annotation_relief_attempt', None):
                self.project.annotation_relief = prepare_annotation_relief(
                    self.catalog, self.project.geometry, self.project.matrix, self.image.shape, CACHE,
                    dem_path=self.dem_path if not self.project.identification else '',
                    lens_distortion=self.project.identification.get('lens_distortion'))
                self._annotation_relief_attempt = None if self.project.annotation_relief else key
        candidates = self.project.visible_features(self.catalog, self.image.shape, image=self.image, all_candidates=True)
        font_sizes = self.project.label_font_sizes([feature for feature, _ in candidates], self.image.shape)
        reference_font = self.project.font_sizes(self.image.shape)[1]
        objects = {}
        scale = np.sqrt(abs(np.linalg.det(self.project.matrix[:, :2]))) if self.project.matrix is not None else 1.
        def requests():
            # Build text paths and rim graphics only for candidates actually
            # considered by layout; the catalogue can contain thousands more.
            for feature, xy in candidates:
                fid = feature["id"]
                data = self.project.labels.get(fid, {})
                if data.get("hidden", False):
                    continue
                item = Annotation(feature, xy, caption_text(self.project, feature), self.project, self.move_label, self.edit_label,
                                  font_size=font_sizes[fid])
                outline = self.project.crater_outline(feature, self.image.shape)
                if outline:
                    item.outline_segments = outline
                    contour = QPainterPath()
                    for segment in outline:
                        contour.moveTo(*segment[0])
                        for point in segment[1:]:
                            contour.lineTo(*point)
                    ring = self.canvas.scene().addPath(contour, QPen(QColor(item.appearance.line), max(1.2, item.font_size*.045)))
                    # Own the absolute contour with the leader; moving the
                    # caption must leave the projected crater rim in place.
                    self.canvas.scene().removeItem(ring)
                    ring.setParentItem(item.line)
                    ring.setZValue(-1)
                    if item.marker is not None:
                        item.marker.hide()
                bounds = item.layout_bounds()
                fixed = (data["position"][0]+bounds.x(), data["position"][1]+bounds.y()) if "position" in data else None
                if feature["kind"] in ("Crater, craters", "Satellite Feature"):
                    radius = min(min(self.image.shape[:2])*.12, max(4., feature["diameter"]*scale/(2*MOON_RADIUS_KM)))
                else:
                    radius = min(item.font_size*1.3, max(4., feature["diameter"]*scale/(4*MOON_RADIUS_KM)))
                if self.project.art_style == "topographic":
                    radius = max(4., item.font_size*.25)
                elif self.project.art_style == "manuscript":
                    radius = min(radius, max(item.font_size*.6, min(self.image.shape[:2])*.025))
                objects[fid] = item
                yield LabelBox(fid, tuple(xy), bounds.width(), bounds.height(), radius, fixed,
                               data.get("force", False), item.outline_segments,
                               important=feature['name'] in COMMON_FEATURES or is_landing_site(feature),
                               region=self.project.art_style == "topographic" or caption_typography(self.project, feature).region)
        h, w = self.image.shape[:2]
        if self.project.optimize_layout:
            placements, self.auto_omitted = arrange_labels(requests(), w, h, gap=max(5., reference_font*(.8 if self.project.art_style == "topographic" else .4)),
                                                          max_labels=self.project.max_labels,
                                                          obstacles=[legend_rect(self.image.shape)] if (self.project.elevation_enabled or self.project.contour_enabled) and (self.project.terrain_path or self.dem_path) else [])
        else:
            placements = {request.key: (*(request.fixed or (request.anchor[0]+request.radius+8, request.anchor[1]-request.height/2)),
                                        request.width, request.height) for request in islice(requests(), self.project.max_labels)}
        for feature, xy in candidates:
            fid = feature["id"]
            data = self.project.labels.get(fid, {})
            hidden = data.get("hidden", False)
            if fid not in objects and not hidden:
                continue  # Unused reserves are not collision-hidden labels.
            listing = QListWidgetItem(self.project.label_text(feature))
            listing.setData(Qt.ItemDataRole.UserRole, fid)
            listing.setFlags(listing.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            listing.setCheckState(Qt.CheckState.Unchecked if hidden else Qt.CheckState.Checked)
            if fid in self.auto_omitted:
                listing.setText(listing.text()+tr("  · 避让收起"))
                listing.setForeground(QColor("#8e9fb5"))
                listing.setToolTip(tr("当前布局没有足够空间，暂时收起；取消再勾选可优先显示，或减少其他标签。"))
            self.names.addItem(listing)
            if hidden or fid not in placements:
                continue
            item = objects[fid]
            bounds = item.layout_bounds()
            x, y, _, _ = placements[fid]
            position = QPointF(x-bounds.x(), y-bounds.y())
            scene.addItem(item.line)
            scene.addItem(item)
            item.setPos(position)
            self.annotation_items.append(item)
        self.canvas.update_text_caches()
        self.update_grid_captions()
        self.layout_status.setText(trf("{count} 个标签", count=len(self.annotation_items)) +
                                  (trf(" · 避让隐藏 {count} 个", count=len(self.auto_omitted)) if self.auto_omitted else ""))
        self.rebuilding = False

    def label_visibility_changed(self, item):
        if self.rebuilding:
            return
        fid = item.data(Qt.ItemDataRole.UserRole)
        self.project.labels.setdefault(fid, {})["hidden"] = item.checkState() != Qt.CheckState.Checked
        if item.checkState() == Qt.CheckState.Checked:
            self.project.labels[fid]["force"] = True
        self.refresh_annotations()
        self.dirty = True

    def edit_label(self, feature):
        text, okay = QInputDialog.getText(self, tr("编辑标注名称"), feature["name"], text=self.project.label_text(feature))
        if okay and text.strip():
            self.project.labels.setdefault(feature["id"], {})["text"] = text.strip()
            self.refresh_annotations()
            self.dirty = True

    def hide_selected(self):
        for item in self.annotation_items:
            if item.isSelected():
                self.project.labels.setdefault(item.feature["id"], {})["hidden"] = True
                self.dirty = True
        self.refresh_annotations()

    def reset_labels(self):
        self.project.labels.clear()
        self.refresh_annotations()
        self.dirty = True

    def reflow_labels(self):
        for data in self.project.labels.values():
            data.pop("position", None)
        self.apply_label_settings()

    def annotation_entries(self):
        return [(item.feature, [item.anchor.x(), item.anchor.y()], [item.pos().x(), item.pos().y()])
                for item in self.annotation_items]

    def annotation_leaders(self):
        return {item.feature["id"]: (item.line.line().x1(), item.line.line().y1(), item.line.line().x2(), item.line.line().y2())
                for item in self.annotation_items}

    def render_png(self, path):
        if self.image is None or self.project.matrix is None:
            raise ValueError(tr("请先打开照片并配准。"))
        self.check_map_export()
        # Keep the exported canvas exactly the original dimensions. Reference
        # markers and selection rectangles belong to the editor only.
        hidden = [(item, item.isVisible()) for item in (*self.reference_items, *self.crater_items)]
        selected = [item for item in self.annotation_items if item.isSelected()]
        contour_layers = [item for item in self.map_items if isinstance(item, ContourLayer)]
        for item, _ in hidden:
            item.setVisible(False)
        for item in selected:
            item.setSelected(False)
        try:
            for item in self.annotation_items:
                item.set_export_mode(True)
            for item in contour_layers:
                item.set_export_mode(True)
            h, w = self.image.shape[:2]
            result = QImage(w, h, QImage.Format.Format_RGB32)
            result.setColorSpace(srgb_color_space())
            result.fill(QColor("#000"))
            painter = QPainter(result)
            painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                                   QPainter.RenderHint.SmoothPixmapTransform)
            self.canvas.scene().render(painter, QRectF(0,0,w,h), QRectF(0,0,w,h))
            painter.end()
            if not result.save(str(path), "PNG"):
                raise ValueError(tr("PNG 保存失败，请检查目标路径。"))
        finally:
            for item in self.annotation_items:
                item.set_export_mode(False)
            for item in contour_layers:
                item.set_export_mode(False)
            for item, visible in hidden:
                item.setVisible(visible)
            for item in selected:
                item.setSelected(True)
            self.canvas.update_text_caches()

    def suggest_export_path(self, suffix, extension):
        source = Path(self.project.image_path) if self.project.image_path else Path("moon")
        return str(source.with_name(f"{source.stem}-{suffix}.{extension}"))

    def export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("导出标注照片"), self.suggest_export_path("annotated", "png"), tr("PNG (*.png)"))
        if path:
            try:
                self.render_png(path if path.lower().endswith(".png") else path+".png")
                self.statusBar().showMessage(tr("PNG 已导出"))
            except Exception as exc:
                self.error(exc)

    def export_vector(self):
        if self.image is None or self.project.matrix is None:
            self.error(tr("请先打开照片并配准。"))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("导出可编辑标注"), self.suggest_export_path("annotated", "svg"), tr("SVG (*.svg)"))
        if path:
            try:
                self.check_map_export()
                export_svg(path if path.lower().endswith(".svg") else path+".svg", self.image, self.annotation_entries(), self.project, self.annotation_leaders(), layers=self.map_layers, display_image=self.display_image)
                self.statusBar().showMessage(tr("SVG 已导出"))
            except Exception as exc:
                self.error(exc)

    def update_catalog(self):
        def success(features):
            self.catalog = features
            self.catalog_by_id = {f["id"]: f for f in features}
            self.project.annotation_relief.clear()
            self._annotation_relief_attempt = None
            self.catalog_button.setText(trf("更新 USGS 地名（现有 {count:,} 项）", count=len(features)))
            self.search_features(self.feature_search.text())
            self.search_crater_features(self.crater_search.text())
            self.refresh_annotations()
            self.statusBar().showMessage(tr("地名目录已更新"))
        self.run_background(tr("下载 USGS / IAU 官方地名目录…"), lambda: refresh_catalog(CACHE), success)

    def open_example(self):
        self.open_project(str(ROOT / "examples" / "demo.moonlabel"))

    def compute_settings_dialog(self):
        if not self.busy:
            ComputeDialog(self.compute_preferences, self).exec()

    def help_dialog(self):
        QMessageBox.information(self, tr("使用 MoonLabeler"),
            trf("自动：打开照片，设置拍摄日期，点击“自动识别并标注”。时间默认 UTC 15:00，展开可修改；北京时间请换算为 UTC。首次需下载参考数据。\n\n"
            "辅助找坑：自动识别失败后，先检测中心，选候选，搜索并点击环形山名称，再在底部确认加入参考点。按 Enter 可选首条地名。\n\n"
            "参考点辅助自动：确认一两个已知点后，点击“用参考点自动配准”或顶部“自动识别并标注”。程序搜索附近地形，验证通过后生成标注。\n\n"
            "手动补点：展开“手动补点”，搜索地名，点击取点按钮，再点照片中同一个坑的完整坑缘中心。不要点亮斑或阴影中心。取 3–6 个分散、不共线的点，再完成校准。\n"
            "Esc 取消取点；双击参考点行重选，取消勾选停用。橙色行需核对。\n\n"
            "月溪、山脉等在“手动补点”中选择。\n\n"
            "标注：改设置后点击“重新生成标注”。{hint}调整位置，双击编辑文字。不按修饰键时拖动只平移画面。字号按照片短边计算，按视直径分大、中、小三档；字号递减设为 0 则统一字号。可保存工程或导出 PNG / SVG。\n\n"
            "DEM：导入或下载高程数据，选择区域生成光照参考。基础采样约 1.9 km；不适用于近月缘区域。\n\n"
            "坑缘圈是目录投影参考，可能偏离实际坑缘。拟合残差只表示一致性；模型和数据来源详见 README。", hint=label_drag_hint()))

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage(tr("处理完成后可关闭"))
            self.restart_requested = False
            event.ignore()
        elif self.confirm_discard():
            if self.restart_requested:
                self.restart_requested = False
                if not self.restart_application():
                    # Keep the window: the preference is saved, the user can reopen manually.
                    event.ignore()
                    self.error(tr("无法自动重新启动 MoonLabeler，请手动重新打开。界面语言设置已保存。"))
                    return
            self.clear_terrain_preview()
            event.accept()
        else:
            self.restart_requested = False
            event.ignore()

    def restart_application(self):
        """Launch a fresh MoonLabeler process; return False when it could not be started.

        Source checkouts are relaunched as ``python -m moonlabeler`` from the repository
        root so the module is found even when the original process was started through
        ``run_app.py`` from another directory; relative file arguments are made absolute.
        """
        arguments = [str(Path(arg).resolve()) if Path(arg).exists() else arg for arg in sys.argv[1:]]
        if getattr(sys, "frozen", False):
            program, cwd = sys.executable, os.getcwd()
        else:
            program, arguments, cwd = sys.executable, ["-m", "moonlabeler", *arguments], str(ROOT)
        result = QProcess.startDetached(program, arguments, cwd)
        started = result[0] if isinstance(result, tuple) else result
        return bool(started)


def main():
    prepare_cache()
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("MoonLabeler")
    application.setOrganizationName("MoonLabeler")
    preferences = QSettings(str(CACHE/'preferences.ini'), QSettings.Format.IniFormat)
    i18n.initialize(preferences.value(i18n.PREFERENCE_KEY))
    window = MainWindow()
    window.showMaximized()
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.suffix == ".moonlabel":
            window.open_project(str(path))
        else:
            window.open_image(str(path))
    sys.exit(application.exec())
