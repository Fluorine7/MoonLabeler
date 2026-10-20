# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Native Qt desktop application. All processing happens on this computer."""
from datetime import datetime, timezone
from dataclasses import replace
from itertools import islice
from pathlib import Path
import os
import csv
import shutil
import unicodedata
import sys
import traceback

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QDateTime, QObject, Signal, QRunnable, QThreadPool, QTimer, QSettings, QProcess
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QPainter, QPen, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsLineItem, QGraphicsEllipseItem,
    QPushButton, QLabel,
    QFileDialog, QMessageBox, QColorDialog, QTableWidgetItem,
    QListWidgetItem, QInputDialog,
    QDialog,
)

from . import __version__
from . import i18n
from .i18n import tr
from .capture_time import winjupos_capture_time
from .ui.theme import STYLE
from .ui.window import WindowUiMixin, LABEL_DRAG_HINT
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
from .project import Project, export_svg, DEFAULT_FONT_PERCENT, font_tier_percentages
from .registration import calibration_report, transform_points, auto_register
from .sources import load_catalog, read_image, nasa_reference, refresh_catalog, feature_search_text, COMMON_FEATURES
from .terrain import ElevationMap, download_basic_dem, render_region

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("MOONLABELER_CACHE", str(Path.home() / "Library/Caches/MoonLabeler" if getattr(sys, "frozen", False) else ROOT / ".cache")))


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
    return QImage(array.data, w, h, array.strides[0], QImage.Format.Format_RGB888).copy()


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
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
            self.signals.error.emit(str(exc))
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


class Annotation(QGraphicsItem):
    def __init__(self, feature, anchor, text, project, moved, edit, *, font_size=None):
        super().__init__()
        self.feature, self.anchor, self.text = feature, QPointF(*anchor), text
        self.project, self.moved, self.edit = project, moved, edit
        self.font_size = project.font_size if font_size is None else font_size
        self.color = project.label_color(feature)
        self.outline_segments = []
        self.font = QFont("PingFang SC")
        self.font.setPixelSize(self.font_size)
        self.path = QPainterPath()
        self.path.addText(0, self.font_size, self.font, text)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tr(f"{LABEL_DRAG_HINT} · 双击编辑文字"))
        self.setZValue(20)
        self.line = QGraphicsLineItem()
        self.line.setPen(QPen(QColor(self.color), max(1.2, self.font_size*.035)))
        self.line.setZValue(10)
        if is_landing_site(feature):
            radius = landing_marker_radius(self.font_size)
            x, y = self.anchor.x(), self.anchor.y()
            for segment in ((x-radius, y, x+radius, y), (x, y-radius, x, y+radius)):
                marker = QGraphicsLineItem(*segment, self.line)
                marker.setPen(QPen(QColor(self.color), max(1.2, self.font_size*.045)))
        else:
            marker_radius = max(2.5, self.font_size*.06)
            marker = QGraphicsEllipseItem(self.anchor.x()-marker_radius, self.anchor.y()-marker_radius,
                                          marker_radius*2, marker_radius*2, self.line)
            marker.setBrush(QColor(self.color))
            marker.setPen(QPen(Qt.PenStyle.NoPen))

    def boundingRect(self):
        padding = max(5., self.font_size*.04)
        return self.path.boundingRect().adjusted(-padding, -padding, padding, padding)

    def paint(self, painter, option, widget=None):
        painter.strokePath(self.path, QPen(QColor("#141923"), max(2., self.font_size*.06),
                                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.fillPath(self.path, QColor(self.color))
        if self.isSelected():
            painter.setPen(QPen(QColor("#88baf3"), 1.))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.boundingRect(), 3., 3.)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            rect = self.boundingRect().translated(self.pos())
            segment = leader_segment((self.anchor.x(), self.anchor.y()), (rect.x(), rect.y(), rect.width(), rect.height()),
                                     outline=self.outline_segments)
            self.line.setLine(*segment)
            self.moved(self.feature["id"], [self.pos().x(), self.pos().y()])
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
            event.accept()
        else:
            event.ignore()  # Let ScrollHandDrag pan, even over a label.

    def mouseMoveEvent(self, event):
        if (self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.setPos(event.scenePos()-self._drag_offset)
        else:
            # Releasing the modifier ends this drag; don't jump if re-pressed.
            self._drag_offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
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
        self.setToolTip(tr(f"候选 {index+1} · 中心 ({candidate.x:.1f}, {candidate.y:.1f})\n点击选中；请核对坑缘和地名。"))

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
            font = QFont("PingFang SC")
            font.setPixelSize(12)
            path = QPainterPath()
            path.addText(8, -5, font, str(self.index+1))
            shadow = QPen(QColor("#111821"), 2.)
            painter.strokePath(path, shadow)
            painter.fillPath(path, pen.color())

    def mousePressEvent(self, event):
        self.selected_callback(self.index)
        event.accept()




class MainWindow(WindowUiMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MoonLabeler {__version__} · {tr('月面照片标注')} · ©️Fluorine Zhu（正七价的氟离子）")
        self.resize(1440, 930)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(STYLE)
        self.project = Project()
        self.image = None
        self.catalog = load_catalog(CACHE)
        self.compute_preferences = QSettings(str(CACHE/'preferences.ini'), QSettings.Format.IniFormat)
        compute_mode = self.compute_preferences.value('compute/mode', 'auto')
        compute_mode = compute.normalize_mode(compute_mode)
        compute.set_mode(compute_mode if compute_mode in compute.MODES else 'auto')
        self.catalog_by_id = {f["id"]: f for f in self.catalog}
        self.annotation_items = []
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
        self.statusBar().showMessage(tr(f"滚轮缩放 · 拖动平移 · {LABEL_DRAG_HINT}"))
        self.empty_hint = self.canvas.scene().addText(tr("打开或拖入照片"), QFont("PingFang SC", 20))
        self.empty_hint.setDefaultTextColor(QColor("#718399"))
        self.empty_hint.setPos(70, 100)




    def crater_settings_changed(self, *args):
        self.crater_settings_toggle.setText(tr(f"检测设置 · 半径 {self.crater_min.value()}–{self.crater_max.value()} px"))
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
                                raise ValueError(tr(f"检测到 {len(detection.candidates)} 个疑似坑缘；未通过自动配准验证。\n纹理参考：{atlas_error}\n轮廓参考：{limb_error}\n坑群参考：{exc}\n高程参考：{terrain_error}")) from terrain_error
            if recognition.projection_surface == 'terrain':
                # The accepted automatic relief fit used the basic LOLA map,
                # not an unrelated map currently selected in the preview UI.
                recognition.annotation_relief = prepare_annotation_relief(
                    catalog, recognition.projection_geometry or geometry, recognition.matrix, image.shape, CACHE,
                    lens_distortion=recognition.lens_distortion)
            return detection, recognition, geometry, lat, lon
        def failure(message):
            self.identification_status.setText(tr("参考点配准失败，请核对取点") if known else tr("识别失败，可改用手动校准"))
            self.identification_status.setToolTip(tr(message))
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
            message = tr(f"参考点辅助配准 · {len(recognition.reference_points['reference_ids'])} 个已确认点 · {recognition.image_inliers} 个图像对应点 · 覆盖 {recognition.coverage:.1%}。圈为目录参考轮廓")
        elif recognition.lens_distortion:
            message = tr(f"目镜畸变校正 · {recognition.image_inliers} 个图像对应点 · 月缘偏差（95%）{recognition.refinement['limb_p95_px']:.1f} px")
        elif recognition.limb_inliers:
            message = tr(f"月盘外缘与月海纹理配准成功 · 纹理相关 {recognition.texture_correlation:.2f} · 外缘拟合偏差 {recognition.rms_px:.2f} px")
        elif recognition.refinement and recognition.matches:
            message = tr(f"坑群识别后精修 · {recognition.image_inliers} 个图像对应点 · 覆盖 {recognition.coverage:.1%} · 拟合偏差 {recognition.rms_px:.2f} px。大坑优先使用高程坑缘，轮廓精度受数据分辨率限制")
        elif recognition.method.startswith("LOLA"):
            message = tr(f"已定位月面区域 · {recognition.image_inliers} 个图像对应点 · 覆盖 {recognition.coverage:.1%} · 拟合偏差 {recognition.rms_px:.2f} px")
            message += tr("。大坑使用高程参考轮廓") if recognition.crater_rims else tr("。圈为目录参考轮廓，尚未贴合实际坑缘")
            if recognition.refinement:
                message += tr("。观测方向微调已通过分区验证")
        elif recognition.image_inliers:
            message = tr(f"纹理配准成功 · {recognition.image_inliers} 个图像对应点 · 拟合偏差 {recognition.rms_px:.2f} px")
        else:
            message = tr(f"识别到 {'、'.join(names[:4])} 等 {len(recognition.matches)} 处地形 · 拟合偏差 {recognition.rms_px:.2f} px")
        self.identification_status.setText(tr(f"{'参考点辅助配准完成' if recognition.reference_points else '配准完成'} · 拟合偏差 {recognition.rms_px:.2f} px"))
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
        message = tr(f"{count} 个候选") if count else tr("未找到候选，可调整检测参数")
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
            row = QListWidgetItem(tr(f"{index+1:02d}   ({candidate.x:.0f}, {candidate.y:.0f})   ·   半径 {(candidate.major+candidate.minor)/2:.0f} px"))
            row.setToolTip((tr("EDCircles 坑缘拟合；还需核对是否为真实环形山。") if candidate.method == "edge-drawing" else tr("中心已手动调整。")) if candidate.support is None else
                           tr(f"长/短半轴 {candidate.major:.1f} / {candidate.minor:.1f} px；方向 {candidate.angle:.1f}°\n边缘支持度 {candidate.support:.2f}，用于排序，不是正确率。"))
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
        self.crater_anchor_button.setText(tr(f"确认候选 {self.crater_list.currentRow()+1:02d}，{operation}") if selected else tr("确认地名，加入参考点"))
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
                item = QListWidgetItem(self.project.label_text(feature))
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
        self.crater_status.setText(tr(f"已确认候选 {index+1:02d}：{feature.get('name_zh') or feature['name']}"))
        self.statusBar().showMessage(self.crater_status.text())

    def remove_crater_candidate(self):
        self.cancel_pick()
        index = self.crater_list.currentRow()
        if 0 <= index < len(self.crater_candidates):
            self.crater_candidates.pop(index)
            self.crater_feature.clearSelection()
            self.crater_feature.setCurrentRow(-1)
            self.refresh_crater_candidates()
            self.crater_status.setText(tr(f"保留 {len(self.crater_candidates)} 个候选"))

    def repick_crater_candidate(self):
        index = self.crater_list.currentRow()
        if 0 <= index < len(self.crater_candidates):
            self.cancel_pick()
            self.picking_crater_index = index
            self.canvas.picking = True
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.statusBar().showMessage(tr(f"点击候选 {index+1} 的坑中心 · Esc 取消"))

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
        self.crater_status.setText(tr(f"候选 {index+1} 中心已更新"))

    def export_crater_candidates(self):
        if not self.crater_candidates:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("导出疑似坑候选"), "crater-candidates.csv", tr("CSV (*.csv)"))
        if path:
            try:
                with open(path if path.lower().endswith(".csv") else path+".csv", "w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["image", "candidate", "center_x_px", "center_y_px", "semimajor_px", "semiminor_px", "angle_deg", "edge_support", "method"])
                    for index, c in enumerate(self.crater_candidates):
                        writer.writerow([Path(self.project.image_path).name, index+1, f"{c.x:.3f}", f"{c.y:.3f}", f"{c.major:.3f}", f"{c.minor:.3f}", f"{c.angle:.3f}", "" if c.support is None else f"{c.support:.3f}", c.method])
                self.statusBar().showMessage(tr("CSV 已保存"))
            except OSError as exc:
                self.error(str(exc))

    def run_background(self, title, function, success, failure=None):
        if self.busy:
            return
        self.busy = True
        self.sidebar.setEnabled(False)
        self.toolbar.setEnabled(False)
        self.canvas.setEnabled(False)
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

    def error(self, text):
        self.statusBar().showMessage(tr("操作未完成。"))
        QMessageBox.warning(self, "MoonLabeler", tr(text))

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
            self.geometry_status.setText(tr(f"{label}：纬度 {lat:+.3f}°，经度 {lon:+.3f}°"))

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
            filename_utc = winjupos_capture_time(path)
            self.project = Project(image_path=str(Path(path).resolve()), utc=(filename_utc or self.utc()).isoformat())
            self.project_path = None
            self.set_image(image)
            self.sync_controls()
            self.ui_reset_for_new_photo()
            self.dirty = False
            self.geometry_status.setText(tr("未计算"))
            self.registration_status.setText(tr("未配准"))
            self.identification_status.setText(tr("未识别"))
            self.identification_status.setToolTip("")
            timestamp = tr(f" · 文件名时间：{filename_utc:%Y-%m-%d %H:%M:%S} UTC") if filename_utc else ""
            self.statusBar().showMessage(tr(f"{Path(path).name} · {image.shape[1]} × {image.shape[0]} 像素{timestamp}"))
        except Exception as exc:
            self.error(str(exc))

    def set_image(self, image):
        self.clear_terrain_preview()
        self.clear_crater_candidates()
        self.image = image
        self.project.update_font_size(image.shape)
        self.update_font_hint()
        self.annotation_items = []
        self.reference_items = []
        self.canvas.scene().clear()
        self.canvas.scene().addPixmap(QPixmap.fromImage(qimage(image))).setZValue(0)
        h, w = image.shape[:2]
        self.canvas_title.setText(Path(self.project.image_path).name or tr("月面照片"))
        self.canvas_details.setText(tr(f"{w:,} × {h:,} px   ·   滚轮缩放 · {LABEL_DRAG_HINT} · 双击编辑文字"))
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
            self.project = project
            self.project.update_font_size(image.shape)
            self.project_path = Path(path)
            self.sync_controls()
            self.set_image(image)
            self.show_geometry()
            self.identification_status.setToolTip("")
            self.registration_status.setText(tr("已配准") if project.matrix is not None else tr("未配准"))
            if project.identification and project.matrix is not None:
                names = project.identification.get("matched_names", [])
                if project.identification.get("image_inliers"):
                    self.identification_status.setText(tr("已配准"))
                    self.identification_status.setToolTip(tr(f"{project.identification['image_inliers']} 个图像对应点；标注由目录坐标投影得到。"))
                else:
                    self.identification_status.setText(tr("已识别"))
                    self.identification_status.setToolTip("、".join(names[:4]))
            else:
                self.identification_status.setText(tr("未识别"))
            self.dirty = False
            self.statusBar().showMessage(tr(f"已打开 {Path(path).name}"))
        except Exception as exc:
            self.error(str(exc))

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
            self.statusBar().showMessage(tr(f"已保存 {Path(path).name}"))
            return True
        except Exception as exc:
            self.error(str(exc))
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
        self.landing_color_button.setToolTip(tr(f"着陆点颜色：{self.pending_landing_color}；使用小档字号"))
        self.optimize_layout.setChecked(self.project.optimize_layout)
        self.crater_outlines.setChecked(self.project.crater_outlines)
        self.crater_outline_shape.setCurrentIndex(self.crater_outline_shape.findData(self.project.crater_outline_shape))
        self.pending_color = self.project.color
        self.color_button.setText(tr(f"文字与引线颜色：{self.pending_color}"))
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
            item = QListWidgetItem(f"{f.get('name_zh') or f['name']}  ·  {f['name']}  ({f['diameter']:.0f} km)")
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
        self.anchor_count.setText(tr(f"{count} 个有效参考点") + (tr(" · 可尝试自动配准") if known_count else ""))
        self.solve_button.setToolTip(tr(f"至少 {required} 个分散、不共线的参考点。"))
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
            message = tr(f"{feature.get('name_zh') or feature['name']}：点击照片中的坑中心")
        elif count >= required:
            message = tr("可校准，也可继续取点")
        elif known_count:
            message = tr(f"可尝试自动配准；手动校准还需 {required-count} 个点")
        else:
            message = tr(f"还需 {required-count} 个参考点")
        self.manual_guide.setText(message)
        if picking:
            self.pick_button.setText(tr("点击照片中的坑中心…"))
        elif item is not None:
            feature = self.catalog_by_id[item.data(Qt.ItemDataRole.UserRole)]
            name = feature.get('name_zh') or feature['name']
            self.pick_button.setText(tr(f"在照片中标记：{name}"))
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
            name = (feature.get("name_zh") or feature["name"]) if feature else anchor["id"]
            checked = QTableWidgetItem()
            checked.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            checked.setCheckState(Qt.CheckState.Checked if anchor.get("enabled", True) else Qt.CheckState.Unchecked)
            error, check, suspect = diagnostics.get(anchor["id"], (None, float("nan"), False))
            values = [checked, QTableWidgetItem(f"{index+1}. {name}"), QTableWidgetItem(f"{error:.2f}" if error is not None else "—")]
            tooltip = tr(f"中心：X {anchor['pixel'][0]:.1f}，Y {anchor['pixel'][1]:.1f}")
            if np.isfinite(check):
                tooltip += tr(f"\n留出该点后，其他点预测它的偏差：{check:.2f} px")
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
            self.error(tr(f"请先添加至少 {required} 个已知环形山的参考点，尽量分散且不共线。"))
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
                warning += tr(f"；请核对 {features[report.suspect_index]['name']}（表中橙色）")
            self.registration_status.setText(tr(f"{len(features)} 个参考点 · 残差 {rms:.2f} px · {'镜像' if mirrored else '不镜像'}{warning}"))
            self.refresh_anchor_table()
            self.refresh_annotations()
            self.workspace_tabs.setCurrentIndex(1)
            self.statusBar().showMessage(tr("校准完成"))
            self.dirty = True
        except Exception as exc:
            self.error(str(exc))

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
        self.registration_status.setText(tr(f"自动匹配：{match.inliers}/{match.matches} 个内点 · 残差 {match.rms_px:.2f} px · {'镜像' if match.mirrored else '不镜像'}"))
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
            self.error(str(exc))

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
            self.terrain_center.addItem(f"{feature.get('name_zh') or feature['name']} · {feature['name']}", feature["id"])
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
        self.dem_status.setText(tr(f"{name} · 赤道采样约 {resolution:.3f} km"))
        self.dem_status.setToolTip(self.dem_path)
        if self.project.matrix is None:
            self.project.annotation_relief.clear()
            self._annotation_relief_attempt = None
        self.terrain_settings_changed()
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
        note = QLabel(tr(f"{utc} · 视野 {reference.width_km:.0f} km · 采样 {reference.resolution_km:.3f} km"))
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
        path, _ = QFileDialog.getSaveFileName(self, tr("保存 DEM 模拟与参考工程"), "moon-dem-reference.png", tr("PNG (*.png)"))
        if not path:
            return
        try:
            from PIL import Image
            path = Path(path if path.lower().endswith(".png") else path+".png")
            Image.fromarray(self.terrain_reference.image).save(path)
            project = Project(image_path=str(path.resolve()), utc=self.terrain_geometry.utc,
                              geometry=self.terrain_geometry, matrix=self.terrain_reference.matrix,
                              latitude=self.project.latitude, longitude=self.project.longitude,
                              terrain_path=self.dem_path, terrain_settings=self.terrain_parameters(), min_diameter=5)
            project.save(path.with_suffix(".moonlabel"))
            self.statusBar().showMessage(tr(f"已保存 {path.name} 和对应参考工程。"))
        except Exception as exc:
            self.error(str(exc))

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
        self.registration_status.setText(tr(f"DEM 配准 · {match.inliers}/{match.matches} 个内点 · 残差 {match.rms_px:.2f} px"))
        self.registration_status.setToolTip(tr("辅助匹配，需用已知地形复核。"))
        self.statusBar().showMessage(tr("DEM 配准完成"))
        self.dirty = True

    def about_dialog(self):
        QMessageBox.about(self, tr("关于 MoonLabeler"), tr(f"MoonLabeler {__version__}\n\n"
                          "作者：Fluorine Zhu\n开源许可：GNU GPL v3.0 或更新版本\n\n"
                          "致敬 Jim Mosher 与 Henrik Bondo 创建的 Lunar Terminator Visualization Tool。"
                          "本程序参考其地形点校准与 DEM 光照思路，使用 Python / Qt 独立实现。\n\n"
                          "感谢樊仕达（10deg）提供 moonlib 代码参考及 LPND 中文地名资料。\n\n"
                          "地名：USGS / IAU；中文译名优先采用 LPND，补录来源单独保留。\n"
                          "月面高程：LRO / LOLA；星历：JPL DE421；着陆点：NASA NSSDCA / LROC。\n"
                          "疑似坑检测改编自 Ram Maruboina 的 Lunar Crater Detector（MIT）。\n"
                          "来源和模型限制见项目目录的 ACKNOWLEDGEMENTS.md 与 README.md。"))

    def style_changed(self, *args):
        if self.rebuilding:
            return
        self.style_pending = True
        self.update_font_hint()
        self.settings_status.setText(tr("设置已改，需重新生成"))

    def update_font_hint(self):
        percentages = font_tier_percentages(self.font_size.value(), self.ui_font_step.value())
        if self.ui_font_step.value() == 0:
            hint = tr("统一字号")
            if self.image is not None:
                hint += tr(f" · 原图 {max(6, round(min(self.image.shape[:2])*percentages[0]/100))} px")
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
                           ("illuminated_only", self.lit.isChecked()),
                           ("show_landing_sites", self.landing_sites_toggle.isChecked()),
                           ("landing_color", self.pending_landing_color),
                           ("optimize_layout", self.optimize_layout.isChecked()),
                           ("crater_outlines", self.crater_outlines.isChecked()),
                           ("crater_outline_shape", self.crater_outline_shape.currentData()), ("color", self.pending_color)):
            setattr(self.project, key, value)
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
            self.color_button.setText(tr(f"文字与引线颜色：{self.pending_color}"))
            self.style_changed()

    def choose_landing_color(self):
        color = QColorDialog.getColor(QColor(self.pending_landing_color), self)
        if color.isValid():
            self.pending_landing_color = color.name()
            self.landing_color_button.setToolTip(tr(f"着陆点颜色：{self.pending_landing_color}；使用小档字号"))
            self.style_changed()

    def move_label(self, fid, position):
        if not self.rebuilding:
            self.project.labels.setdefault(fid, {})["position"] = position
            self.dirty = True

    def refresh_annotations(self):
        self.rebuilding = True
        scene = self.canvas.scene()
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
                item = Annotation(feature, xy, self.project.label_text(feature), self.project, self.move_label, self.edit_label,
                                  font_size=font_sizes[fid])
                outline = self.project.crater_outline(feature, self.image.shape)
                if outline:
                    item.outline_segments = outline
                    contour = QPainterPath()
                    for segment in outline:
                        contour.moveTo(*segment[0])
                        for point in segment[1:]:
                            contour.lineTo(*point)
                    ring = self.canvas.scene().addPath(contour, QPen(QColor(self.project.color), max(1.2, item.font_size*.045)))
                    # Own the absolute contour with the leader; moving the
                    # caption must leave the projected crater rim in place.
                    self.canvas.scene().removeItem(ring)
                    ring.setParentItem(item.line)
                    ring.setZValue(-1)
                    for child in item.line.childItems():
                        if isinstance(child, QGraphicsEllipseItem):
                            child.hide()
                bounds = item.boundingRect()
                fixed = (data["position"][0]+bounds.x(), data["position"][1]+bounds.y()) if "position" in data else None
                if feature["kind"] in ("Crater, craters", "Satellite Feature"):
                    radius = min(min(self.image.shape[:2])*.12, max(4., feature["diameter"]*scale/(2*MOON_RADIUS_KM)))
                else:
                    radius = min(item.font_size*1.3, max(4., feature["diameter"]*scale/(4*MOON_RADIUS_KM)))
                objects[fid] = item
                yield LabelBox(fid, tuple(xy), bounds.width(), bounds.height(), radius, fixed,
                               data.get("force", False), item.outline_segments,
                               important=feature['name'] in COMMON_FEATURES or is_landing_site(feature))
        h, w = self.image.shape[:2]
        if self.project.optimize_layout:
            placements, self.auto_omitted = arrange_labels(requests(), w, h, gap=max(5., reference_font*.4),
                                                          max_labels=self.project.max_labels)
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
            bounds = item.boundingRect()
            x, y, _, _ = placements[fid]
            position = QPointF(x-bounds.x(), y-bounds.y())
            scene.addItem(item.line)
            scene.addItem(item)
            item.setPos(position)
            self.annotation_items.append(item)
        self.layout_status.setText(tr(f"{len(self.annotation_items)} 个标签") +
                                  (tr(f" · 避让隐藏 {len(self.auto_omitted)} 个") if self.auto_omitted else ""))
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
        # Keep the exported canvas exactly the original dimensions. Reference
        # markers and selection rectangles belong to the editor only.
        hidden = [(item, item.isVisible()) for item in (*self.reference_items, *self.crater_items)]
        selected = [item for item in self.annotation_items if item.isSelected()]
        for item, _ in hidden:
            item.setVisible(False)
        for item in selected:
            item.setSelected(False)
        try:
            h, w = self.image.shape[:2]
            result = QImage(w, h, QImage.Format.Format_RGB32)
            result.fill(QColor("#000"))
            painter = QPainter(result)
            painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            self.canvas.scene().render(painter, QRectF(0,0,w,h), QRectF(0,0,w,h))
            painter.end()
            if not result.save(str(path), "PNG"):
                raise ValueError(tr("PNG 保存失败，请检查目标路径。"))
        finally:
            for item, visible in hidden:
                item.setVisible(visible)
            for item in selected:
                item.setSelected(True)

    def export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("导出标注照片"), "moon-annotated.png", tr("PNG (*.png)"))
        if path:
            try:
                self.render_png(path if path.lower().endswith(".png") else path+".png")
                self.statusBar().showMessage(tr("PNG 已导出"))
            except Exception as exc:
                self.error(str(exc))

    def export_vector(self):
        if self.image is None or self.project.matrix is None:
            self.error(tr("请先打开照片并配准。"))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("导出可编辑标注"), "moon-annotated.svg", tr("SVG (*.svg)"))
        if path:
            try:
                export_svg(path if path.lower().endswith(".svg") else path+".svg", self.image, self.annotation_entries(), self.project, self.annotation_leaders())
                self.statusBar().showMessage(tr("SVG 已导出"))
            except Exception as exc:
                self.error(str(exc))

    def update_catalog(self):
        def success(features):
            self.catalog = features
            self.catalog_by_id = {f["id"]: f for f in features}
            self.project.annotation_relief.clear()
            self._annotation_relief_attempt = None
            self.catalog_button.setText(tr(f"更新 USGS 地名（现有 {len(features):,} 项）"))
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
            tr("自动：打开照片，设置拍摄日期，点击“自动识别并标注”。时间默认 UTC 15:00，展开可修改；北京时间请换算为 UTC。首次需下载参考数据。\n\n"
            "辅助找坑：自动识别失败后，先检测中心，选候选，搜索并点击环形山名称，再在底部确认加入参考点。按 Enter 可选首条地名。\n\n"
            "参考点辅助自动：确认一两个已知点后，点击“用参考点自动配准”或顶部“自动识别并标注”。程序搜索附近地形，验证通过后生成标注。\n\n"
            "手动补点：展开“手动补点”，搜索地名，点击取点按钮，再点照片中同一个坑的完整坑缘中心。不要点亮斑或阴影中心。取 3–6 个分散、不共线的点，再完成校准。\n"
            "Esc 取消取点；双击参考点行重选，取消勾选停用。橙色行需核对。\n\n"
            "月溪、山脉等在“手动补点”中选择。\n\n"
            f"标注：改设置后点击“重新生成标注”。{LABEL_DRAG_HINT}调整位置，双击编辑文字。不按修饰键时拖动只平移画面。字号按照片短边计算，按视直径分大、中、小三档；字号递减设为 0 则统一字号。可保存工程或导出 PNG / SVG。\n\n"
            "DEM：导入或下载高程数据，选择区域生成光照参考。基础采样约 1.9 km；不适用于近月缘区域。\n\n"
            "坑缘圈是目录投影参考，可能偏离实际坑缘。拟合残差只表示一致性；模型和数据来源详见 README。"))

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
