# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Native Qt desktop application. All processing happens on this computer."""
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
import os
import csv
import re
import shutil
import unicodedata
import sys
import traceback

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QDateTime, QTime, QTimeZone, QObject, Signal, QRunnable, QThreadPool, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QPainter, QPen, QAction, QKeySequence, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsLineItem, QGraphicsEllipseItem,
    QPushButton, QToolButton, QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QDateTimeEdit, QGroupBox, QScrollArea, QSplitter,
    QFileDialog, QMessageBox, QColorDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QListWidget, QListWidgetItem, QInputDialog, QAbstractItemView, QTabWidget,
    QDialog,
)

from . import __version__
from .ui.theme import STYLE
from .ui.window import WindowUiMixin
from .craters import DetectionOptions, detect_craters, detect_crater_rims
from .identification import identify_from_candidates
from .atlas import identify_from_atlas
from .limb import identify_from_limb
from .terrain_identification import identify_from_terrain
from .geometry import compute_geometry, MOON_RADIUS_KM
from .layout import LabelBox, arrange_labels, leader_segment
from .project import Project, export_svg, DEFAULT_FONT_PERCENT
from .registration import calibration_report, transform_points, auto_register
from .sources import load_catalog, read_image, nasa_reference, refresh_catalog, COMMON_FEATURES, feature_search_text
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

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        self.image_dropped.emit(event.mimeData().urls()[0].toLocalFile())
        event.acceptProposedAction()


class Annotation(QGraphicsItem):
    def __init__(self, feature, anchor, text, project, moved, edit):
        super().__init__()
        self.feature, self.anchor, self.text = feature, QPointF(*anchor), text
        self.project, self.moved, self.edit = project, moved, edit
        self.outline_segments = []
        self.font = QFont("PingFang SC")
        self.font.setPixelSize(project.font_size)
        self.path = QPainterPath()
        self.path.addText(0, project.font_size, self.font, text)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(20)
        self.line = QGraphicsLineItem()
        self.line.setPen(QPen(QColor(project.color), max(1.2, project.font_size*.035)))
        self.line.setZValue(10)
        marker_radius = max(2.5, project.font_size*.06)
        marker = QGraphicsEllipseItem(self.anchor.x()-marker_radius, self.anchor.y()-marker_radius,
                                      marker_radius*2, marker_radius*2, self.line)
        marker.setBrush(QColor(project.color))
        marker.setPen(QPen(Qt.PenStyle.NoPen))

    def boundingRect(self):
        padding = max(5., self.project.font_size*.04)
        return self.path.boundingRect().adjusted(-padding, -padding, padding, padding)

    def paint(self, painter, option, widget=None):
        painter.strokePath(self.path, QPen(QColor("#141923"), max(2., self.project.font_size*.06),
                                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.fillPath(self.path, QColor(self.project.color))
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
        self.setToolTip(f"候选 {index+1} · 中心 ({candidate.x:.1f}, {candidate.y:.1f})\n点击选中；请核对坑缘和地名。")

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
        self.setWindowTitle(f"MoonLabeler {__version__} · 月面照片标注")
        self.resize(1440, 930)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(STYLE)
        self.project = Project()
        self.image = None
        self.catalog = load_catalog(CACHE)
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
        self.project_path = None
        self.rebuilding = False
        self.workers = set()
        self.style_pending = False
        self.pending_color = self.project.color
        self.canvas = Canvas()
        self.canvas.point_clicked.connect(self.canvas_point_clicked)
        self.canvas.image_dropped.connect(self.open_image)
        self.build_toolbar()
        self.build_sidebar()
        self.update_manual_guide()
        self.statusBar().showMessage("拖入月面照片，或先打开示例工程。滚轮缩放，空白处拖动平移。")
        self.empty_hint = self.canvas.scene().addText("拖入你的月面照片\n\n配准地形 · 选择名称 · 编辑标注 · 导出作品", QFont("PingFang SC", 24))
        self.empty_hint.setDefaultTextColor(QColor("#718399"))
        self.empty_hint.setPos(70, 100)




    def crater_settings_changed(self, *args):
        self.crater_settings_toggle.setText(f"检测设置 · 半径 {self.crater_min.value()}–{self.crater_max.value()} px")
        if self.rebuilding:
            return
        self.project.crater_settings = {"min_radius": self.crater_min.value(), "max_radius": self.crater_max.value(),
                                        "sensitivity": self.crater_sensitivity.value(), "max_candidates": self.crater_limit.value(),
                                        "viewport": self.crater_viewport.isChecked()}
        if self.crater_candidates:
            self.crater_status.setText("参数已改变，列表仍是上次结果。点击检测更新。")
        if self.image is not None:
            self.dirty = True

    def detect_photo_craters(self):
        if self.image is None:
            self.error("请先打开局部月面照片。")
            return
        options = DetectionOptions(self.crater_min.value(), self.crater_max.value(),
                                    self.crater_sensitivity.value(), self.crater_limit.value())
        if options.max_radius <= options.min_radius:
            self.error("最大半径必须大于最小半径。")
            return
        self.cancel_pick()
        region = None
        if self.crater_viewport.isChecked():
            rect = self.canvas.mapToScene(self.canvas.viewport().rect()).boundingRect().intersected(self.canvas.sceneRect())
            region = (rect.x(), rect.y(), rect.width(), rect.height())
        image = self.image
        self.run_background("正在本地检测疑似坑中心…", lambda: detect_craters(image, options, region), self.accept_crater_candidates)

    def identify_photo(self):
        if self.image is None:
            self.error("请先打开月面照片，并选择拍摄日期。默认按当日 UTC 15:00 计算。")
            return
        if self.busy:
            return
        self.cancel_pick()
        utc = self.utc()
        lat = self.latitude.value() if self.topocentric.isChecked() else None
        lon = self.longitude.value() if self.topocentric.isChecked() else None
        image, catalog = self.image, list(self.catalog)
        cached_geometry = self.project.geometry
        # Never feed a previous image-derived correction back into ephemeris
        # matching: repeated recognition must not accumulate view offsets.
        if self.project.identification.get("refinement"):
            cached_geometry = None
        def work():
            geometry = cached_geometry or compute_geometry(utc, CACHE / "ephemeris", lat, lon)
            detection = detect_crater_rims(image)
            try:
                recognition = identify_from_atlas(image, geometry)
            except ValueError:
                try:
                    recognition = identify_from_limb(image, geometry)
                except ValueError as limb_error:
                    try:
                        recognition = identify_from_candidates(detection.candidates, catalog, geometry, image.shape, image=image)
                    except ValueError as exc:
                        try:
                            recognition = identify_from_terrain(image, geometry, CACHE)
                        except (ValueError, OSError) as terrain_error:
                            raise ValueError(f"检测到 {len(detection.candidates)} 个疑似坑缘；纹理、月盘轮廓和坑群验证均未通过。\n{limb_error}\n{exc}\n高程参考：{terrain_error}") from terrain_error
            return detection, recognition, geometry, lat, lon
        def failure(message):
            self.identification_status.setText(message+"\n可用地形点校准；已有配准保留。")
            self.error(message)
        self.identification_status.setText("正在检查月海纹理、月盘外缘与坑群位置…")
        self.run_background("正在自动识别；首次需下载约 20 MB 星历，地形后备匹配另需约 33 MB 高程数据…",
                            work, self.accept_identification, failure)

    def accept_identification(self, result):
        detection, recognition, geometry, lat, lon = result
        geometry = recognition.projection_geometry or geometry
        known = [a for a in self.project.anchors if a.get("enabled", True) and a["id"] in self.catalog_by_id]
        if len(known) >= 3:
            features = [self.catalog_by_id[a["id"]] for a in known]
            points, visible, _ = geometry.project([f["lat"] for f in features], [f["lon"] for f in features])
            errors = np.linalg.norm(transform_points(recognition.matrix, points)-np.array([a["pixel"] for a in known]), axis=1)
            if not visible.all() or np.median(errors) > max(15., recognition.rms_px*3):
                self.identification_status.setText("自动结果与现有参考点不一致，未采用。")
                self.error("自动识别与现有参考点不一致，已保留原配准。请核对日期和参考点。")
                return
        self.project.geometry = geometry
        self.project.matrix = recognition.matrix
        self.project.utc = geometry.utc
        self.project.latitude, self.project.longitude = lat, lon
        existing = {a["id"] for a in self.project.anchors}
        for match in recognition.matches:
            candidate = detection.candidates[match.candidate_index]
            fid = match.feature["id"]
            if fid not in existing:
                self.project.anchors.append({"id": fid, "pixel": [float(candidate.x), float(candidate.y)], "enabled": True, "source": "automatic"})
            # Recognition anchors prove the pose. Lettered satellites should
            # not take layout precedence over the main named formations.
            if match.feature["kind"] == "Crater, craters":
                self.project.labels.setdefault(fid, {})["force"] = True
        if recognition.image_inliers or recognition.limb_inliers:
            self.project.min_diameter = max(5., min(self.project.min_diameter, 15*MOON_RADIUS_KM/np.linalg.norm(recognition.matrix[:, 0])))
        else:
            self.project.min_diameter = min(self.project.min_diameter, 5.)
        self.project.identification = {"method": recognition.method,
                                       "candidate_count": len(detection.candidates),
                                       "matched_names": [m.feature["name"] for m in recognition.matches],
                                       "image_inliers": recognition.image_inliers,
                                       "coverage": recognition.coverage,
                                       "limb_inliers": recognition.limb_inliers,
                                       "texture_correlation": recognition.texture_correlation,
                                       "rms_px": recognition.rms_px}
        if recognition.refinement:
            self.project.identification["refinement"] = recognition.refinement
        self.accept_crater_candidates(detection)
        self.sync_controls()
        self.show_geometry()
        self.refresh_anchor_table()
        self.refresh_annotations()
        names = [m.feature["name"] for m in recognition.matches if m.feature["kind"] == "Crater, craters"]
        if recognition.limb_inliers:
            message = f"月盘外缘与月海纹理配准成功 · 纹理相关 {recognition.texture_correlation:.2f} · 外缘拟合偏差 {recognition.rms_px:.2f} px"
        elif recognition.method.startswith("LOLA"):
            message = f"已定位月面区域 · {recognition.image_inliers} 个图像对应点 · 覆盖 {recognition.coverage:.1%} · 拟合偏差 {recognition.rms_px:.2f} px。圈为目录参考轮廓，尚未贴合实际坑缘"
            if recognition.refinement:
                message += "。观测方向微调已通过分区验证"
        elif recognition.image_inliers:
            message = f"纹理配准成功 · {recognition.image_inliers} 个图像对应点 · 拟合偏差 {recognition.rms_px:.2f} px"
        else:
            message = f"识别到 {'、'.join(names[:4])} 等 {len(recognition.matches)} 处地形 · 拟合偏差 {recognition.rms_px:.2f} px"
        self.identification_status.setText(message+"。小偏差不等于绝对定位精度，请对照照片检查。")
        self.registration_status.setText(message)
        self.workspace_tabs.setCurrentIndex(1)
        self.statusBar().showMessage("已配准并标注。可拖动标签调整布局；标注位置由月面目录投影得到。")
        self.dirty = True

    def clear_crater_candidates(self):
        for item in self.crater_items:
            self.canvas.scene().removeItem(item)
        self.crater_items = []
        self.crater_candidates = []
        self.crater_result = None
        self.crater_list.clear()
        self.crater_status.setText("半径按原图像素计算。候选结果需人工核对。")
        self.update_crater_buttons()

    def accept_crater_candidates(self, result):
        self.clear_crater_candidates()
        self.crater_result = result
        self.crater_candidates = list(result.candidates)
        self.refresh_crater_candidates()
        count = len(self.crater_candidates)
        message = f"找到 {count} 个疑似中心。" if count else "没有找到候选。可调高灵敏度或调整半径范围。"
        if result.scale < .99:
            message += " 大图已缩小检测；小坑建议放大后只检测当前视野。"
        self.crater_status.setText(message)
        self.statusBar().showMessage("检测完成；选择候选，核对中心与地名。" if count else "检测完成，未找到符合条件的候选。")

    def refresh_crater_candidates(self):
        for item in self.crater_items:
            self.canvas.scene().removeItem(item)
        self.crater_items = []
        self.crater_list.blockSignals(True)
        self.crater_list.clear()
        for index, candidate in enumerate(self.crater_candidates):
            row = QListWidgetItem(f"{index+1:02d}   ({candidate.x:.0f}, {candidate.y:.0f})   ·   半径 {(candidate.major+candidate.minor)/2:.0f} px")
            row.setToolTip(("EDCircles 坑缘拟合；还需核对是否为真实环形山。" if candidate.method == "edge-drawing" else "中心已手动调整。") if candidate.support is None else
                           f"长/短半轴 {candidate.major:.1f} / {candidate.minor:.1f} px；方向 {candidate.angle:.1f}°\n边缘支持度 {candidate.support:.2f}，用于排序，不是正确率。")
            self.crater_list.addItem(row)
            overlay = CraterOverlay(candidate, index, self.crater_list.setCurrentRow)
            self.canvas.scene().addItem(overlay)
            self.crater_items.append(overlay)
        self.crater_list.blockSignals(False)
        if self.crater_candidates:
            self.crater_list.setCurrentRow(0)
        self.show_crater_overlays()
        self.update_crater_buttons()

    def select_crater_candidate(self, index):
        if self.picking_crater_index is not None and index != self.picking_crater_index:
            self.cancel_pick()
        self.show_crater_overlays()
        self.update_crater_buttons()

    def review_page_changed(self, *args):
        self.cancel_pick()
        self.show_crater_overlays()

    def show_crater_overlays(self, *args):
        visible = self.workspace_tabs.currentIndex() == 0 and self.registration_tabs.currentWidget() == self.crater_tab
        if hasattr(self, "crater_action_panel"):
            self.crater_action_panel.setVisible(visible)
        for index, item in enumerate(self.crater_items):
            item.active = index == self.crater_list.currentRow()
            item.outline = self.crater_overlay_toggle.isChecked()
            item.setVisible(visible)
            item.update()
        for item in self.reference_items:
            item.setVisible(self.workspace_tabs.currentIndex() == 0 and not visible)

    def update_crater_buttons(self, *args):
        selected = 0 <= self.crater_list.currentRow() < len(self.crater_candidates)
        self.crater_remove.setEnabled(selected)
        self.crater_repick.setEnabled(selected)
        self.crater_export.setEnabled(bool(self.crater_candidates))
        self.crater_anchor_button.setEnabled(selected and self.crater_feature.currentData() is not None)
        fid = self.crater_feature.currentData()
        self.crater_anchor_button.setText("确认地名，更新参考点" if any(a["id"] == fid for a in self.project.anchors) else "确认地名，加入参考点")

    def search_crater_features(self, text):
        normalized = lambda value: "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))
        query = normalized(text.strip())
        self.crater_feature.clear()
        # Require a deliberate name search, rather than defaulting to the
        # largest unrelated formation and encouraging an accidental assignment.
        if query:
            matches = [f for f in self.catalog if f["kind"] in ("Crater, craters", "Satellite Feature") and query in normalized(feature_search_text(f))]
            matches.sort(key=lambda f: (normalized(f["name"]) != query, -f["diameter"]))
            for feature in matches[:100]:
                self.crater_feature.addItem(self.project.label_text(feature), feature["id"])
        self.update_crater_buttons()

    def use_crater_candidate(self):
        index = self.crater_list.currentRow()
        fid = self.crater_feature.currentData()
        if not 0 <= index < len(self.crater_candidates) or fid is None:
            return
        feature = self.catalog_by_id[fid]
        if self.project.geometry is not None:
            _, visible, _ = self.project.geometry.project([feature["lat"]], [feature["lon"]])
            if not visible[0]:
                self.error("此地形位于月球背面。请核对拍摄时间或地形名称。")
                return
        self.picking_id = fid
        candidate = self.crater_candidates[index]
        self.add_anchor(candidate.x, candidate.y)
        self.update_crater_buttons()
        self.crater_status.setText(f"已确认 {feature.get('name_zh') or feature['name']}。{self.anchor_count.text()}。\n继续确认其他坑，或点击“查看已确认的参考点并校准”。")
        self.statusBar().showMessage(self.crater_status.text())

    def remove_crater_candidate(self):
        self.cancel_pick()
        index = self.crater_list.currentRow()
        if 0 <= index < len(self.crater_candidates):
            self.crater_candidates.pop(index)
            self.refresh_crater_candidates()
            self.crater_status.setText(f"保留 {len(self.crater_candidates)} 个候选；已确认的参考点仍保留。")

    def repick_crater_candidate(self):
        index = self.crater_list.currentRow()
        if 0 <= index < len(self.crater_candidates):
            self.cancel_pick()
            self.picking_crater_index = index
            self.canvas.picking = True
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.statusBar().showMessage(f"在照片上点击候选 {index+1} 的真实中心。切换工作页可取消。")

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
        self.refresh_crater_candidates()
        self.crater_list.setCurrentRow(index)
        self.crater_status.setText(f"候选 {index+1} 中心已修正，可确认地名后加入参考点。")

    def export_crater_candidates(self):
        if not self.crater_candidates:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出疑似坑候选", "crater-candidates.csv", "CSV (*.csv)")
        if path:
            try:
                with open(path if path.lower().endswith(".csv") else path+".csv", "w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["image", "candidate", "center_x_px", "center_y_px", "semimajor_px", "semiminor_px", "angle_deg", "edge_support", "method"])
                    for index, c in enumerate(self.crater_candidates):
                        writer.writerow([Path(self.project.image_path).name, index+1, f"{c.x:.3f}", f"{c.y:.3f}", f"{c.major:.3f}", f"{c.minor:.3f}", f"{c.angle:.3f}", "" if c.support is None else f"{c.support:.3f}", c.method])
                self.statusBar().showMessage("候选 CSV 已保存，坐标为原图像素。")
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

    def error(self, text):
        self.statusBar().showMessage("操作未完成。")
        QMessageBox.warning(self, "MoonLabeler", text)

    def sync_capture_time(self, *args):
        # date remains the single timestamp source for geometry and projects.
        # The disclosure only changes visibility, never the selected time.
        time = self.date.time()
        blocked = self.capture_time.blockSignals(True)
        self.capture_time.setTime(time)
        self.capture_time.blockSignals(blocked)
        self.capture_time_toggle.setText(f"具体时间 · UTC {time.toString('HH:mm:ss')}")

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
        self.project.labels.clear()
        self.clear_terrain_preview()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.geometry_status.setText("拍摄条件已改变，完成校准时会自动重算。")
        self.identification_status.setText("拍摄条件已改变，请重新自动识别或校准。")
        self.registration_status.setText("配准已失效。参考点仍保留，可重新求解。")
        if self.image is not None:
            self.dirty = True

    def calculate_geometry(self, checked=False, *, after=None):
        utc = self.utc()
        lat = self.latitude.value() if self.topocentric.isChecked() else None
        lon = self.longitude.value() if self.topocentric.isChecked() else None
        def success(geometry):
            self.project.geometry = geometry
            self.project.utc = utc.isoformat()
            self.project.latitude, self.project.longitude = lat, lon
            self.project.matrix = None
            self.project.identification.clear()
            self.clear_terrain_preview()
            self.show_geometry()
            self.refresh_anchor_table()
            self.refresh_annotations()
            self.dirty = True
            self.statusBar().showMessage("月面几何已就绪，选择已知地形并添加参考点。")
            if after is not None:
                after()
        self.run_background("计算月面几何；首次需要下载约 20 MB 的 JPL 星历数据…",
                            lambda: compute_geometry(utc, CACHE / "ephemeris", lat, lon), success)

    def show_geometry(self):
        if self.project.geometry:
            lat, lon = self.project.geometry.libration
            label = "投影视角（图像微调）" if self.project.identification.get("refinement") else "天平动"
            self.geometry_status.setText(f"{label}：纬度 {lat:+.3f}°，经度 {lon:+.3f}°")

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "保存工程", "当前工程有未保存的修改。", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def open_image(self, path=None):
        if self.busy or not self.confirm_discard():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "打开月面照片", "", "图像 (*.png *.jpg *.jpeg *.tif *.tiff *.fits *.fit *.fts)")
        if not path:
            return
        try:
            image = read_image(path)
            self.project = Project(image_path=str(Path(path).resolve()), utc=self.utc().isoformat())
            self.project_path = None
            self.set_image(image)
            self.sync_controls()
            self.dirty = False
            self.geometry_status.setText("完成校准时会按拍摄日期自动计算。")
            self.registration_status.setText("尚未配准。")
            self.identification_status.setText("照片已打开；选择拍摄日期后，点击自动识别并标注。默认按当日 UTC 15:00 计算。")
            self.statusBar().showMessage(f"{Path(path).name} · {image.shape[1]} × {image.shape[0]} 像素")
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
        self.canvas_title.setText(Path(self.project.image_path).name or "月面照片")
        self.canvas_details.setText(f"{w:,} × {h:,} px   ·   滚轮缩放")
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
            path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", "MoonLabeler (*.moonlabel)")
        if not path:
            return
        try:
            project = Project.load(path)
            if not Path(project.image_path).exists():
                replacement, _ = QFileDialog.getOpenFileName(self, "原始照片已移动，请重新选择")
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
            self.registration_status.setText("已加载工程配准。" if project.matrix is not None else "尚未配准。")
            if project.identification and project.matrix is not None:
                names = project.identification.get("matched_names", [])
                if project.identification.get("image_inliers"):
                    self.identification_status.setText(f"已加载纹理配准：{project.identification['image_inliers']} 个图像对应点。标注位置由月面目录投影得到。")
                else:
                    self.identification_status.setText("已加载自动识别结果："+"、".join(names[:4])+"。可在参考点表复核。")
            else:
                self.identification_status.setText("工程已打开，可重新自动识别或使用地形点校准。")
            self.dirty = False
            self.statusBar().showMessage(f"已打开 {Path(path).name}")
        except Exception as exc:
            self.error(str(exc))

    def save_project(self):
        if self.image is None:
            self.error("请先打开照片。")
            return False
        path, _ = QFileDialog.getSaveFileName(self, "保存工程", str(self.project_path or Path(self.project.image_path).with_suffix(".moonlabel")), "MoonLabeler (*.moonlabel)")
        if not path:
            return False
        if not path.endswith(".moonlabel"):
            path += ".moonlabel"
        try:
            self.project.save(path)
            self.project_path = Path(path)
            self.dirty = False
            self.statusBar().showMessage(f"已保存 {Path(path).name}")
            return True
        except Exception as exc:
            self.error(str(exc))
            return False

    def sync_controls(self):
        self.rebuilding = True
        self.topocentric.setChecked(self.project.latitude is not None)
        self.latitude.setValue(self.project.latitude or 0.)
        self.longitude.setValue(self.project.longitude or 0.)
        if self.project.utc:
            dt = datetime.fromisoformat(self.project.utc).astimezone(timezone.utc)
            self.date.setDateTime(QDateTime.fromString(dt.isoformat(), Qt.DateFormat.ISODate))
        self.kind.setCurrentText(self.project.kind)
        self.diameter.setValue(self.project.min_diameter)
        self.maximum.setValue(self.project.max_labels)
        self.language.setCurrentText(self.project.language)
        self.font_size.setValue(self.project.font_percent or DEFAULT_FONT_PERCENT)
        self.lit.setChecked(self.project.illuminated_only)
        self.optimize_layout.setChecked(self.project.optimize_layout)
        self.crater_outlines.setChecked(self.project.crater_outlines)
        self.pending_color = self.project.color
        self.color_button.setText(f"文字与引线颜色：{self.pending_color}")
        self.style_pending = False
        self.settings_status.setText("调整设置后，点击重新生成标注。")
        self.update_font_hint()
        if self.project.terrain_path:
            self.dem_path = self.project.terrain_path
        self.dem_status.setText(Path(self.dem_path).name if self.dem_path else "尚未选择高程数据")
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

    def update_manual_guide(self, *args):
        count = sum(a.get("enabled", True) for a in self.project.anchors)
        required = 3 if self.mirror.currentIndex() == 0 else 2
        self.anchor_count.setText(f"3  已添加 {count} 个有效参考点 · 至少需要 {required} 个")
        self.solve_button.setEnabled(self.image is not None and count >= required and not self.canvas.picking)
        item = self.feature_list.currentItem()
        picking = self.canvas.picking and self.picking_id is not None
        self.cancel_pick_button.setVisible(picking)
        self.pick_button.setEnabled(self.image is not None and item is not None and not self.canvas.picking)
        if self.image is None:
            message = "先打开要标注的照片。"
        elif picking:
            feature = self.catalog_by_id[self.picking_id]
            message = f"正在取点：{feature.get('name_zh') or feature['name']}。请在照片中点击它的坑缘中心；Esc 取消。"
        elif count >= required:
            message = "参考点数量已足够，可点击下方“完成校准并生成标注”；也可继续加点。"
        else:
            message = f"还需 {required-count} 个参考点。搜索地名、选中结果，再点击下方按钮到照片上取点。"
        self.manual_guide.setText(message)
        if picking:
            self.pick_button.setText("等待在照片中点击中心…")
        elif item is not None:
            feature = self.catalog_by_id[item.data(Qt.ItemDataRole.UserRole)]
            name = feature.get('name_zh') or feature['name']
            self.pick_button.setText(f"在照片中标记：{name}")
        else:
            self.pick_button.setText("先从搜索结果中选择地名")

    def show_manual_points(self):
        self.workspace_tabs.setCurrentIndex(0)
        self.registration_tabs.setCurrentIndex(0)
        self.scroll.ensureWidgetVisible(self.solve_button)

    def start_pick(self):
        if self.image is None:
            self.error("请先打开照片。")
            return
        item = self.feature_list.currentItem()
        if item is None:
            self.error("请先搜索并选择一个已知地形。")
            return
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
            self.statusBar().showMessage("已退出取点。" + self.manual_guide.text())

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
        self.registration_status.setText(self.manual_guide.text())
        self.statusBar().showMessage(self.manual_guide.text())
        self.dirty = True
        if self.workspace_tabs.currentIndex() == 0 and self.registration_tabs.currentIndex() == 0:
            target = self.solve_button if self.solve_button.isEnabled() else self.feature_search
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(target))

    def refresh_anchor_table(self):
        enabled = [a for a in self.project.anchors if a.get("enabled", True)]
        self.calibration = None
        diagnostics = {}
        if self.project.geometry and self.project.matrix is not None and len(enabled) >= 2:
            try:
                features = [self.catalog_by_id[a["id"]] for a in enabled]
                source, _, _ = self.project.geometry.project([f["lat"] for f in features], [f["lon"] for f in features])
                target = np.array([a["pixel"] for a in enabled])
                self.calibration = calibration_report(source, target, ["auto", "no", "yes"][self.mirror.currentIndex()])
                actual_errors = np.linalg.norm(transform_points(self.project.matrix, source)-target, axis=1)
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
            tooltip = f"中心：X {anchor['pixel'][0]:.1f}，Y {anchor['pixel'][1]:.1f}"
            if np.isfinite(check):
                tooltip += f"\n留出该点后，其他点预测它的偏差：{check:.2f} px"
            if suspect:
                tooltip += "\n建议核对此点；停用后可重新配准。程序没有自动删除它。"
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
                    projected, _, _ = self.project.geometry.project([feature["lat"]], [feature["lon"]])
                    predicted = transform_points(self.project.matrix, projected)[0]
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
        self.project.labels.clear()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.registration_status.setText(self.manual_guide.text())
        self.dirty = True

    def solve_manual(self):
        anchors = [a for a in self.project.anchors if a.get("enabled", True)]
        required = 3 if self.mirror.currentIndex() == 0 else 2
        if self.image is None or len(anchors) < required:
            self.error(f"请先添加至少 {required} 个已知环形山的参考点，尽量分散且不共线。")
            return
        if self.project.geometry is None:
            self.calculate_geometry(after=self.solve_manual)
            return
        self.cancel_pick()
        try:
            anchors = [a for a in self.project.anchors if a.get("enabled", True)]
            if len(anchors) < 2:
                raise ValueError("请先在照片上添加至少两个已知环形山中心；建议三处以上，以判断镜像和检查配准误差。")
            features = [self.catalog_by_id[a["id"]] for a in anchors]
            points, visible, _ = self.project.geometry.project([f["lat"] for f in features], [f["lon"] for f in features])
            if not np.all(visible):
                raise ValueError("参考点包含背面地形，请核对地形和拍摄时间。")
            report = calibration_report(points, [a["pixel"] for a in anchors], ["auto", "no", "yes"][self.mirror.currentIndex()])
            matrix, rms = report.matrix, report.rms_px
            self.project.matrix = matrix
            self.project.identification.clear()
            self.project.labels.clear()
            mirrored = np.linalg.det(matrix[:, :2]) < 0
            warning = "；两点无法自动判断镜像，也无法独立评估误差" if len(features) == 2 else ""
            if report.suspect_index is not None:
                warning += f"；请核对 {features[report.suspect_index]['name']}（表中橙色）"
            self.registration_status.setText(f"{len(features)} 个参考点 · 残差 {rms:.2f} px · {'镜像' if mirrored else '不镜像'}{warning}")
            self.refresh_anchor_table()
            self.refresh_annotations()
            self.workspace_tabs.setCurrentIndex(1)
            self.statusBar().showMessage("手动校准完成，已生成标注。请核对圈线位置；需要调整参考点时返回“校准”。")
            self.dirty = True
        except Exception as exc:
            self.error(str(exc))

    def accept_auto(self, result):
        match, geometry, matrix, reference_utc, latitude, longitude = result
        self.project.geometry = geometry
        self.project.matrix = matrix
        self.project.utc = reference_utc
        self.project.latitude, self.project.longitude = latitude, longitude
        self.project.anchors.clear()
        self.project.identification.clear()
        self.project.labels.clear()
        self.sync_controls()
        self.show_geometry()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.registration_status.setText(f"自动匹配：{match.inliers}/{match.matches} 个内点 · 残差 {match.rms_px:.2f} px · {'镜像' if match.mirrored else '不镜像'}")
        self.statusBar().showMessage("自动配准完成。请检查几个已知地形，随后编辑标注。")
        self.dirty = True

    def auto_nasa(self):
        if self.image is None:
            self.error("请先打开照片。")
            return
        if self.topocentric.isChecked():
            self.error("NASA 参考使用地心视角。请取消“使用拍摄地点”，或用地形参考点做站心配准。")
            return
        utc, photo = self.utc(), self.image.copy()
        def work():
            reference, geometry, matrix, _ = nasa_reference(utc, CACHE)
            match = auto_register(reference, photo)
            composed = (np.vstack((match.matrix, [0.,0.,1.])) @ np.vstack((matrix,[0.,0.,1.])))[:2]
            return match, geometry, composed, utc.isoformat(), None, None
        self.run_background("下载 NASA 同时刻影像并匹配…", work, self.accept_auto, self.nasa_failed)

    def nasa_failed(self, text):
        self.workspace_tabs.setCurrentIndex(0)
        self.registration_tabs.setCurrentIndex(0)
        self.scroll.ensureWidgetVisible(self.feature_search)
        self.registration_status.setText("NASA 配准未完成，可使用地形点。已有几何和参考点仍保留。")
        self.error(text)

    def auto_local(self):
        if self.image is None:
            self.error("请先打开照片。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择同一拍摄时刻的已校准参考工程", str(ROOT / "examples"), "MoonLabeler (*.moonlabel)")
        if not path:
            return
        try:
            reference_project = Project.load(path)
            if reference_project.matrix is None or reference_project.geometry is None:
                raise ValueError("参考工程尚未配准。")
            delta = abs((datetime.fromisoformat(reference_project.utc) - self.utc()).total_seconds())
            if delta > 3600:
                raise ValueError("参考工程与当前拍摄时间相差超过一小时，请先设置为相同拍摄时刻。不同日期的天平动不能用同一平面变换处理。")
            photo, requested_utc = self.image.copy(), self.utc().isoformat()
            def work():
                reference = read_image(reference_project.image_path)
                match = auto_register(reference, photo)
                composed = (np.vstack((match.matrix, [0.,0.,1.])) @ np.vstack((reference_project.matrix,[0.,0.,1.])))[:2]
                return match, reference_project.geometry, composed, requested_utc, reference_project.latitude, reference_project.longitude
            self.run_background("正在匹配本地参考照片…", work, self.accept_auto)
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
        self.dem_status.setText(f"{name} · 赤道采样约 {resolution:.3f} km")
        self.dem_status.setToolTip(self.dem_path)
        self.terrain_settings_changed()
        self.statusBar().showMessage("高程数据已就绪，可生成局部模拟图。")

    def import_dem(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "选择 LOLA 柱面 DEM 标签", str(Path(self.dem_path).parent if self.dem_path else CACHE),
                                                "月面高程 (*.lbl *.LBL *.img *.IMG *.npz)")
        if path:
            self.run_background("读取 DEM 元数据…", lambda: self.dem_metadata(path), self.accept_dem)

    def download_dem(self):
        def work():
            return self.dem_metadata(download_basic_dem(CACHE))
        self.run_background("下载约 33 MB LOLA 数据；完成后可离线模拟…", work, self.accept_dem)

    def clear_terrain_preview(self):
        self.terrain_reference = None
        self.terrain_geometry = None
        if self.terrain_dialog:
            self.terrain_dialog.close()
            self.terrain_dialog.deleteLater()
            self.terrain_dialog = None

    def generate_terrain(self):
        if not self.dem_path or not Path(self.dem_path).exists():
            self.error("请先导入本地 DEM，或下载基础 LOLA 高程数据。")
            return
        parameters = self.terrain_parameters()
        feature = self.catalog_by_id.get(parameters.pop("center_id"))
        if not feature:
            self.error("请搜索并选择照片中的已知区域。")
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
        self.run_background("生成局部月面模拟图，计算坡度光照和地形投影…", work, self.accept_terrain_reference)

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
        dialog.setWindowTitle("局部月面 DEM 模拟 · 辅助参考")
        dialog.resize(900, 880)
        layout = QVBoxLayout(dialog)
        note = QLabel(f"{utc} · 视野 {reference.width_km:.0f} km · 数据采样约 {reference.resolution_km:.3f} km\n"
                      "模拟图使用球面投影，未加入反照率纹理；细节和阴影可能与实拍不同。")
        note.setWordWrap(True)
        layout.addWidget(note)
        preview = Canvas()
        preview.scene().addPixmap(QPixmap.fromImage(qimage(reference.image)))
        preview.scene().setSceneRect(QRectF(0, 0, reference.image.shape[1], reference.image.shape[0]))
        layout.addWidget(preview)
        row = QHBoxLayout()
        save = QPushButton("保存模拟图与参考工程")
        save.clicked.connect(self.save_terrain_reference)
        match = QPushButton("尝试匹配当前照片")
        match.setEnabled(self.image is not None)
        match.clicked.connect(self.match_terrain_reference)
        close = QPushButton("关闭预览")
        close.clicked.connect(dialog.close)
        row.addWidget(save)
        row.addWidget(match)
        row.addWidget(close)
        layout.addLayout(row)
        self.terrain_dialog = dialog
        dialog.show()
        QTimer.singleShot(0, lambda: preview.fitInView(preview.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio))
        self.statusBar().showMessage("局部模拟完成。可观察地形、保存参考工程或尝试辅助匹配。")

    def save_terrain_reference(self):
        if self.terrain_reference is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存 DEM 模拟与参考工程", "moon-dem-reference.png", "PNG (*.png)")
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
            self.statusBar().showMessage(f"已保存 {path.name} 和对应参考工程。")
        except Exception as exc:
            self.error(str(exc))

    def match_terrain_reference(self):
        if self.image is None or self.terrain_reference is None:
            return
        reference, geometry = self.terrain_reference, self.terrain_geometry
        # Upsampling a coarse DEM cannot create the detail needed for SIFT.
        if reference.width_km/reference.resolution_km < 64:
            self.error("这个视野内不足 64 个地形采样点，细节不足以自动匹配。请导入更高分辨率 DEM，或用地形点校准。")
            return
        photo = self.image.copy()
        def work():
            match = auto_register(reference.image, photo)
            matrix = (np.vstack((match.matrix, [0., 0., 1.])) @ np.vstack((reference.matrix, [0., 0., 1.])))[:2]
            return match, geometry, matrix
        self.run_background("尝试用局部 DEM 参考匹配照片…", work, self.accept_terrain_match)

    def accept_terrain_match(self, result):
        match, geometry, matrix = result
        # Known user clicks are a separate check on a synthetic-image match.
        anchors = [a for a in self.project.anchors if a.get("enabled", True)]
        if len(anchors) >= 3:
            features = [self.catalog_by_id[a["id"]] for a in anchors]
            points, _, _ = geometry.project([f["lat"] for f in features], [f["lon"] for f in features])
            errors = np.linalg.norm(transform_points(matrix, points)-[a["pixel"] for a in anchors], axis=1)
            previous = np.linalg.norm(transform_points(self.project.matrix, points)-[a["pixel"] for a in anchors], axis=1) if self.project.matrix is not None else np.array([0.])
            if np.median(errors) > max(6., 2*np.median(previous)):
                self.error("DEM 匹配与已有地形点不一致，未采用该结果。请核对区域、时间或数据分辨率。")
                return
        self.project.geometry, self.project.matrix = geometry, matrix
        self.project.labels.clear()
        self.refresh_anchor_table()
        self.refresh_annotations()
        self.registration_status.setText(f"DEM 辅助匹配：{match.inliers}/{match.matches} 个内点 · 残差 {match.rms_px:.2f} px。请用已知地形复核。")
        self.statusBar().showMessage("已采用 DEM 辅助匹配；参考点仍保留，可继续检查偏差。")
        self.dirty = True

    def about_dialog(self):
        QMessageBox.about(self, "关于 MoonLabeler", f"MoonLabeler {__version__}\n\n"
                          "作者：Fluorine Zhu\n开源许可：GNU GPL v3.0 或更新版本\n\n"
                          "致敬 Jim Mosher 与 Henrik Bondo 创建的 Lunar Terminator Visualization Tool。"
                          "本程序参考其地形点校准与 DEM 光照思路，使用 Python / Qt 独立实现。\n\n"
                          "地名：USGS / IAU；月面高程：LRO / LOLA；星历：JPL DE421。\n"
                          "疑似坑检测改编自 Ram Maruboina 的 Lunar Crater Detector（MIT）。\n"
                          "来源和模型限制见项目目录的 ACKNOWLEDGEMENTS.md 与 README.md。")

    def style_changed(self, *args):
        if self.rebuilding:
            return
        self.style_pending = True
        self.update_font_hint()
        self.settings_status.setText("设置尚未应用；点击重新生成标注。导出仍使用当前画面。")

    def update_font_hint(self):
        if self.image is not None:
            pixels = max(6, round(min(self.image.shape[:2])*self.font_size.value()/100))
            self.font_pixels_hint.setText(f"对应原图约 {pixels} px")

    def apply_label_settings(self):
        if self.busy:
            return
        for key, value in (("min_diameter", self.diameter.value()), ("kind", self.kind.currentText()),
                           ("max_labels", self.maximum.value()), ("language", self.language.currentText()),
                           ("font_percent", self.font_size.value()), ("illuminated_only", self.lit.isChecked()),
                           ("optimize_layout", self.optimize_layout.isChecked()),
                           ("crater_outlines", self.crater_outlines.isChecked()), ("color", self.pending_color)):
            setattr(self.project, key, value)
        if self.image is not None:
            self.project.update_font_size(self.image.shape)
        self.refresh_annotations()
        self.style_pending = False
        self.settings_status.setText("设置已应用；手动调整的标签位置已保留。")
        if self.image is not None:
            self.dirty = True

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.pending_color), self)
        if color.isValid():
            self.pending_color = color.name()
            self.color_button.setText(f"文字与引线颜色：{self.pending_color}")
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
        candidates = self.project.visible_features(self.catalog, self.image.shape, image=self.image)
        # Named formations precede lettered satellite craters. User edits and
        # explicit requests retain first choice, independent of diameter.
        candidates.sort(key=lambda pair: (not bool(self.project.labels.get(pair[0]["id"], {}).get("force")),
                                          bool(re.search(r"\s[A-Z]$", pair[0]["name"])),
                                          pair[0]["name"] not in COMMON_FEATURES, -pair[0]["diameter"]))
        objects, requests = {}, []
        scale = np.sqrt(abs(np.linalg.det(self.project.matrix[:, :2]))) if self.project.matrix is not None else 1.
        for feature, xy in candidates:
            fid = feature["id"]
            data = self.project.labels.get(fid, {})
            if data.get("hidden", False):
                continue
            item = Annotation(feature, xy, self.project.label_text(feature), self.project, self.move_label, self.edit_label)
            outline = self.project.crater_outline(feature, self.image.shape)
            if outline:
                item.outline_segments = outline
                contour = QPainterPath()
                for segment in outline:
                    contour.moveTo(*segment[0])
                    for point in segment[1:]:
                        contour.lineTo(*point)
                ring = self.canvas.scene().addPath(contour, QPen(QColor(self.project.color), max(1.2, self.project.font_size*.045)))
                # Own the absolute image-coordinate contour with the leader,
                # which stays at (0, 0) when the movable caption is repositioned.
                self.canvas.scene().removeItem(ring)
                ring.setParentItem(item.line)
                ring.setZValue(-1)
                for child in item.line.childItems():
                    if isinstance(child, QGraphicsEllipseItem):
                        child.hide()
            bounds = item.boundingRect()
            fixed = (data["position"][0]+bounds.x(), data["position"][1]+bounds.y()) if "position" in data else None
            # Keep crater captions outside their projected rim, rather than
            # treating a large crater as a star-sized point marker.
            if feature["kind"] in ("Crater, craters", "Satellite Feature"):
                radius = min(min(self.image.shape[:2])*.12, max(4., feature["diameter"]*scale/(2*MOON_RADIUS_KM)))
            else:
                radius = min(self.project.font_size*1.3, max(4., feature["diameter"]*scale/(4*MOON_RADIUS_KM)))
            requests.append(LabelBox(fid, tuple(xy), bounds.width(), bounds.height(), radius, fixed,
                                     data.get("force", False), item.outline_segments))
            objects[fid] = item
        h, w = self.image.shape[:2]
        if self.project.optimize_layout:
            placements, self.auto_omitted = arrange_labels(requests, w, h, gap=max(5., self.project.font_size*.4))
        else:
            placements = {request.key: (*(request.fixed or (request.anchor[0]+request.radius+8, request.anchor[1]-request.height/2)),
                                        request.width, request.height) for request in requests}
        for feature, xy in candidates:
            fid = feature["id"]
            data = self.project.labels.get(fid, {})
            hidden = data.get("hidden", False)
            listing = QListWidgetItem(self.project.label_text(feature))
            listing.setData(Qt.ItemDataRole.UserRole, fid)
            listing.setFlags(listing.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            listing.setCheckState(Qt.CheckState.Unchecked if hidden else Qt.CheckState.Checked)
            if fid in self.auto_omitted:
                listing.setText(listing.text()+"  · 避让收起")
                listing.setForeground(QColor("#8e9fb5"))
                listing.setToolTip("当前布局没有足够空间，暂时收起；取消再勾选可优先显示，或减少其他标签。")
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
        self.layout_status.setText(f"显示 {len(self.annotation_items)} 个标签" +
                                  (f"，拥挤区域暂时收起 {len(self.auto_omitted)} 个。" if self.auto_omitted else "，自动布局已完成。" if self.project.optimize_layout else "。"))
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
        text, okay = QInputDialog.getText(self, "编辑标注名称", feature["name"], text=self.project.label_text(feature))
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
            raise ValueError("请先打开照片并配准。")
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
                raise ValueError("PNG 保存失败，请检查目标路径。")
        finally:
            for item, visible in hidden:
                item.setVisible(visible)
            for item in selected:
                item.setSelected(True)

    def export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出标注照片", "moon-annotated.png", "PNG (*.png)")
        if path:
            try:
                self.render_png(path if path.lower().endswith(".png") else path+".png")
                self.statusBar().showMessage("PNG 已导出，尺寸与原图一致。")
            except Exception as exc:
                self.error(str(exc))

    def export_vector(self):
        if self.image is None or self.project.matrix is None:
            self.error("请先打开照片并配准。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出可编辑标注", "moon-annotated.svg", "SVG (*.svg)")
        if path:
            try:
                export_svg(path if path.lower().endswith(".svg") else path+".svg", self.image, self.annotation_entries(), self.project, self.annotation_leaders())
                self.statusBar().showMessage("SVG 已导出，原图内嵌，文字和引线可编辑。")
            except Exception as exc:
                self.error(str(exc))

    def update_catalog(self):
        def success(features):
            self.catalog = features
            self.catalog_by_id = {f["id"]: f for f in features}
            self.catalog_button.setText(f"更新 USGS 地名（现有 {len(features):,} 项）")
            self.search_features(self.feature_search.text())
            self.search_crater_features(self.crater_search.text())
            self.refresh_annotations()
            self.statusBar().showMessage("已更新官方地名目录。")
        self.run_background("下载 USGS / IAU 官方地名目录…", lambda: refresh_catalog(CACHE), success)

    def open_example(self):
        self.open_project(str(ROOT / "examples" / "demo.moonlabel"))

    def help_dialog(self):
        QMessageBox.information(self, "使用 MoonLabeler",
            "1. 打开照片，选择拍摄日期。默认 UTC 15:00；展开“具体时间”可精确到秒。收起设置或更换日期不会重置时间，旧工程保留原时间。北京时间请换算为 UTC，注意日期跨天。准确校准建议填写拍摄地点。\n\n"
            "2. 点击“自动识别并标注”：检测坑缘、搜索月面地名目录并用其他坑验证，成功后直接生成标签。无需先计算几何或输入地名。失败时核对日期，或改用地形点校准。\n\n"
            "手动校准：参考点就是“已知地名 + 照片中的位置”。在“已知地名取点”中搜索并选中一个你认得的坑，点“在照片中标记”，再点照片中同一个坑的坑缘中心。重复添加 3–6 处分散、不共线的点，再点“完成校准并生成标注”；月面几何会自动计算。取点时 Esc 取消，双击参考点表格可重选中心。\n\n"
            "“校准 → 疑似坑”可先检测候选中心；调节原图像素半径和灵敏度，或只检测当前视野。选中候选、搜索并确认地名后加入参考点。它不会自动识别名称。\n\n"
            "配准后表格显示每点偏差。橙色行提示核对；取消勾选可停用，再次配准。双击该行可重选中心。参考点至少五个时，才提示明显可疑的单点。\n\n"
            "3. “DEM 模拟”可导入本地 LOLA 的 LBL/IMG 数据，或下载一次基础数据。搜索区域、选择视野，生成当前时刻的局部模拟图，可保存为参考工程或尝试辅助匹配。\n\n"
            "基础 DEM 约 1.9 km/采样点；高倍细节需更高分辨率数据。模拟暂用球面投影与坡度光照，未加入反照率纹理，不适用于月缘。\n\n"
            "4. 在“标注”页调整设置，点击“重新生成标注”统一应用；字号为照片短边的百分比。"
            "大坑显示投影坑缘轮廓，小坑使用短引线。拖动标签、双击改名后可保存工程并导出 PNG / SVG。原照片不会被覆盖。\n\n"
            "拟合残差只反映一致性。DEM 自动匹配仍需已知地形复核；NASA 下载失败不影响离线流程。")

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage("后台操作仍在进行，请稍候再关闭。")
            event.ignore()
        elif self.confirm_discard():
            self.clear_terrain_preview()
            event.accept()
        else:
            event.ignore()


def main():
    prepare_cache()
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("MoonLabeler")
    application.setOrganizationName("MoonLabeler")
    window = MainWindow()
    window.showMaximized()
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.suffix == ".moonlabel":
            window.open_project(str(path))
        else:
            window.open_image(str(path))
    sys.exit(application.exec())
