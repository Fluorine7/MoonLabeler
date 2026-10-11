# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Widget construction and pure-presentation interaction logic.

MainWindow (app.py) supplies the existing callbacks/state. Preserve
self.<widget> names, signal connections and widget types consumed by app.py.
workspace_tabs indices: calibration=0, annotation=1, reference=2.

Layout contract notes:
- self.scroll is the calibration page's QScrollArea; feature_search must stay
  a descendant of it (nasa_failed calls scroll.ensureWidgetVisible).
- self.crater_action_panel lives in the calibration page's fixed footer (not
  inside the scroll), so app.py's show/hide keeps the confirmation controls
  reachable while the detector settings scroll.
- crater_overlay_toggle controls temporary detection overlays; crater_outlines
  controls persistent exported annotations. They are independent.
- The manual calibration section (manual_section_toggle / manual_section_block)
  is collapsed by default; ui_set_manual_section_expanded() is the hook for
  app.py to open it on manual picks or identification failures.
- crater_feature is a QListWidget of explicit name choices; each item's
  UserRole holds the catalog feature ID. Searching clears the current choice.
Do not import app.py here (it imports this mixin).
"""
from pathlib import Path
from PySide6.QtCore import Qt, QDateTime, QEvent, QTimer, QTime, QTimeZone
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QPushButton, QToolButton, QLabel, QLineEdit, QComboBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QDateTimeEdit, QTimeEdit, QGroupBox, QScrollArea,
    QSplitter, QTableWidget, QHeaderView, QListWidget, QAbstractItemView,
    QListView, QTabWidget, QSizePolicy,
)


class WidePopupComboBox(QComboBox):
    """Combo box whose drop-down widens to the longest item.

    The styled popup otherwise keeps the combo's own width and clips long
    Chinese entries, e.g. 坑缘轮廓（手绘风） or search results.
    """
    def showPopup(self):
        super().showPopup()
        view = self.view()
        widest = view.sizeHintForColumn(0) + 30  # item padding + vertical scrollbar
        view.setFixedWidth(max(widest, self.width()))


class WindowUiMixin:
    # ------------------------------------------------------------------ helpers
    def ui_note(self, text, object_name="noteLabel"):
        """Muted helper copy; pure presentation."""
        note = QLabel(text)
        note.setWordWrap(True)
        note.setObjectName(object_name)
        return note

    def ui_form(self, parent=None):
        form = QFormLayout(parent)
        # Cocoa's styled group boxes can clip the last form row without a
        # bottom inset, especially the checkbox indicator.
        form.setContentsMargins(0, 4, 0, 10 if parent is not None else 0)
        form.setVerticalSpacing(7)
        form.setHorizontalSpacing(10)
        # macOS otherwise keeps short fields at their tiny size hints, which
        # also leaves too little room for the popup's checkmark and text.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    def ui_section(self, title):
        """Flat titled section: a QGroupBox without the box."""
        group = QGroupBox(title)
        return group

    def ui_combo(self, minimum_contents_length=None):
        """Combo with a stylesheet-friendly view whose popup fits its items."""
        combo = WidePopupComboBox()
        combo.setView(QListView(combo))
        if minimum_contents_length is not None:
            combo.setMinimumContentsLength(minimum_contents_length)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        return combo

    # Manual calibration section (collapsed by default). These two methods are
    # the presentation hook for app.py: open the section when a manual pick
    # starts or after identification fails, close it on flow completion.
    def ui_set_manual_section_expanded(self, expanded):
        self.manual_section_toggle.setChecked(bool(expanded))

    def ui_manual_section_expanded(self):
        return self.manual_section_toggle.isChecked()

    def ui_expand_for_pick(self):
        """Extra listener on pick_button.clicked: entering manual picking must
        surface the section. No-op when it is already open (the usual case,
        since the button itself lives inside it)."""
        self.ui_set_manual_section_expanded(True)

    def ui_size_review_list(self, widget, maximum_rows):
        count = widget.count()
        widget.setVisible(count > 0)
        if count:
            row_height = max(24, widget.sizeHintForRow(0))
            widget.setFixedHeight(min(count, maximum_rows)*row_height + 2*widget.frameWidth() + 4)

    def ui_refresh_crater_hits_view(self, *args):
        """Show actual matches without consuming space for an empty list."""
        self.ui_size_review_list(self.crater_feature, 2)

    def ui_refresh_crater_review(self):
        if not hasattr(self, 'crater_action_panel'):
            return  # The detector controls are constructed before the footer.
        self.ui_size_review_list(self.crater_list, 3)
        self.ui_crater_tools_toggle.setVisible(bool(self.crater_candidates))
        self.ui_crater_tools_block.setVisible(bool(self.crater_candidates) and self.ui_crater_tools_toggle.isChecked())
        index = self.crater_list.currentRow()
        candidate = self.crater_candidates[index] if 0 <= index < len(self.crater_candidates) else None
        self.ui_crater_selection.setText(
            f"候选 {index+1:02d} · ({candidate.x:.0f}, {candidate.y:.0f}) · 半径 {(candidate.major+candidate.minor)/2:.0f} px"
            if candidate else "未选择候选坑")
        item = self.crater_feature.currentItem()
        name = f"地名：{item.text()}" if item is not None else "地名：未选择"
        self.ui_crater_name.setText(self.ui_crater_name.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, max(120, self.crater_action_panel.width()-20)))
        self.ui_crater_name.setToolTip(name)
        count = len(self.project.anchors)
        self.crater_finish_button.setText(f"查看参考点（{count}）并继续配准" if count else "查看参考点并继续配准")
        self.ui_refresh_crater_hits_view()
        self.ui_update_registration_height()

    def ui_update_registration_height(self, *args):
        if not hasattr(self, 'crater_action_panel'):
            return
        height = 16777215
        if self.registration_tabs.currentWidget() is self.crater_tab:
            # QTabWidget otherwise reserves the much taller manual-points page,
            # leaving blank space and scrolling the detector out of sight.
            layout = self.crater_tab.layout()
            height = self.crater_tab.sizeHint().height()
            if layout.hasHeightForWidth():
                height = max(height, layout.totalHeightForWidth(self.crater_tab.width()))
            height += self.registration_tabs.tabBar().sizeHint().height() + 4
        if self.registration_tabs.maximumHeight() != height:
            self.registration_tabs.setMaximumHeight(height)

    def ui_scroll_to_crater_controls(self):
        self.ui_crater_scroll_timer.start(0)

    def ui_reveal_crater_controls(self):
        if self.crater_action_panel.isVisible() and self.registration_tabs.currentWidget() is self.crater_tab:
            control = self.crater_search if self.crater_candidates else self.crater_button
            # Scroll the full frame, not Qt's input cursor / item-view focus rect.
            center = control.mapTo(self.scroll.widget(), control.rect().center())
            self.scroll.ensureVisible(center.x(), center.y(), 0, control.height()//2+12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'ui_crater_scroll_timer'):
            self.ui_refresh_crater_review()

    def ui_update_time_summary(self, *args):
        """折叠时标题附带当前时间；展开后编辑框就在眼前，标题只留“具体时间”。
        app.sync_capture_time calls this after synchronizing the editor."""
        if self.capture_time_toggle.isChecked():
            self.capture_time_toggle.setText("具体时间")
        else:
            self.capture_time_toggle.setText(
                f"具体时间 · UTC {self.capture_time.time().toString('HH:mm:ss')}")

    def ui_reconcile_confirm_bar(self, expanded):
        """While 辅助找坑 review is active, the fixed confirmation bar must not
        outlive a manually collapsed section. app.py re-evaluates the bar on
        every review-page change, so stashing it here stays consistent."""
        if not expanded and self.crater_action_panel.isVisible():
            self.crater_action_panel.hide()

    def eventFilter(self, watched, event):
        # app.py reveals the cancel button when a manual pick starts and the
        # crater confirmation bar when 辅助找坑 review starts; expand the
        # collapsed manual section at the same moment so those controls are
        # actually on screen. Pure presentation: app.py keeps its own flow.
        if event.type() == QEvent.Type.Show and watched in (getattr(self, "cancel_pick_button", None),
                                                            getattr(self, "crater_action_panel", None)):
            if not self.manual_section_toggle.isChecked():
                self.manual_section_toggle.setChecked(True)
            if watched is self.crater_action_panel:
                self.ui_scroll_to_crater_controls()
        if watched is getattr(self, 'crater_tab', None) and event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize):
            self.ui_update_registration_height()
        return super().eventFilter(watched, event)

    def ui_collapsible(self, title, expanded=False):
        """Disclosure triangle plus a hidden content block, shared by the
        crater detector settings and the DEM render parameters."""
        toggle = QToolButton()
        toggle.setObjectName("sectionToggle")
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        toggle.setText(title)
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(7)

        def sync(is_expanded):
            block.setVisible(is_expanded)
            toggle.setArrowType(Qt.ArrowType.DownArrow if is_expanded else Qt.ArrowType.RightArrow)
        toggle.toggled.connect(sync)
        sync(expanded)
        return toggle, block, layout

    # Pure-UI conveniences: select the first search hit on Enter, and let
    # Escape leave the canvas pick mode. They only change selection state and
    # reuse the existing business entry points.
    def ui_select_first_feature(self):
        if self.feature_list.count():
            self.feature_list.setCurrentRow(0)

    def ui_select_first_crater_match(self):
        if self.crater_feature.count():
            self.crater_feature.setCurrentRow(0)

    def ui_select_first_terrain_match(self):
        if self.terrain_center.count():
            self.terrain_center.setCurrentIndex(0)

    def ui_cancel_pick(self):
        self.cancel_pick()

    # ------------------------------------------------------------------ toolbar
    def build_toolbar(self):
        self.toolbar = self.addToolBar("文件与导出")
        self.toolbar.setObjectName("mainToolbar")
        self.toolbar.setMovable(False)
        self.actions = []
        def action(text, callback, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(lambda checked=False: callback())
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            self.toolbar.addAction(a)
            self.actions.append(a)
            return a
        primary = action("打开照片", lambda: self.open_image(), "Ctrl+O")
        self.toolbar.widgetForAction(primary).setProperty("primary", True)
        action("打开工程", lambda: self.open_project(), "Ctrl+Shift+O")
        action("保存工程", self.save_project, "Ctrl+S")
        self.toolbar.addSeparator()
        action("导出 PNG", self.export_png)
        action("导出 SVG", self.export_vector)
        self.toolbar.addSeparator()
        action("适合窗口", self.fit_canvas, "Ctrl+0")
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        action("打开示例", self.open_example)
        action("帮助", self.help_dialog)
        action("致谢", self.about_dialog)
        delete = QAction("隐藏所选名称", self)
        delete.setShortcut(QKeySequence("Backspace"))
        delete.triggered.connect(self.hide_selected)
        delete.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.canvas.addAction(delete)
        escape = QAction("取消拾取", self)
        escape.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        escape.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.triggered.connect(lambda checked=False: self.ui_cancel_pick())
        self.canvas.addAction(escape)

    # ------------------------------------------------------------------ sidebar
    def build_sidebar(self):
        self.sidebar = QWidget()
        self.sidebar.setObjectName("inspectorPanel")
        self.sidebar.setMinimumWidth(340)
        self.sidebar.setMaximumWidth(432)
        outer = QVBoxLayout(self.sidebar)
        outer.setContentsMargins(14, 12, 12, 12)
        outer.setSpacing(10)
        title = QLabel("MoonLabeler")
        title.setObjectName("title")
        outer.addWidget(title)

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName("workspaceTabs")
        self.workspace_tabs.setDocumentMode(True)
        self.workspace_tabs.tabBar().setDrawBase(False)
        outer.addWidget(self.workspace_tabs, 1)

        def workspace_page(caption):
            """Each workspace page: scrolling content plus a fixed footer that
            stays visible while the content above scrolls."""
            container = QWidget()
            container_box = QVBoxLayout(container)
            container_box.setContentsMargins(10, 8, 10, 10)
            container_box.setSpacing(8)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            page = QVBoxLayout(content)
            page.setContentsMargins(0, 0, 4, 8)
            page.setSpacing(8)
            scroll.setWidget(content)
            container_box.addWidget(scroll, 1)
            footer = QWidget()
            footer_box = QVBoxLayout(footer)
            footer_box.setContentsMargins(0, 4, 0, 0)
            footer_box.setSpacing(8)
            container_box.addWidget(footer)
            self.workspace_tabs.addTab(container, caption)
            return page, footer_box, scroll

        layout, calibration_footer, calibration_scroll = workspace_page("校准")
        labels_layout, _, _ = workspace_page("标注")
        reference_layout, _, _ = workspace_page("参考")
        self.scroll = calibration_scroll

        # -------------------------------------------------- 校准 · 拍摄条件
        group = QGroupBox("拍摄条件")
        self.geometry_group = group
        form = self.ui_form(group)
        self.date = QDateTimeEdit(QDateTime.currentDateTimeUtc())
        self.date.setTimeZone(QTimeZone(b"UTC"))
        self.date.setDateTime(QDateTime.currentDateTimeUtc())
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setTime(QTime(15, 0))
        self.date.setToolTip("默认 UTC 15:00；展开“具体时间”可修改。修改日期或收起设置不会重置已选时间。")
        self.date.setCalendarPopup(True)
        form.addRow("拍摄日期", self.date)
        self.capture_time_toggle, self.capture_time_block, time_box = self.ui_collapsible("具体时间 · UTC 15:00:00")
        self.capture_time = QTimeEdit(QTime(15, 0))
        # 时:分 keeps typed entry short — 两位小时后自动跳到分钟，无需点击定位或删除；
        # 秒保留默认或工程原值，仍随 time() 一起读写。
        self.capture_time.setDisplayFormat("HH:mm")
        self.capture_time.setToolTip("输入 UTC 时:分；秒保留默认或工程原值。北京时间需减 8 小时，注意日期跨天。")
        time_form = self.ui_form()
        time_form.addRow("时间（UTC）", self.capture_time)
        time_box.addLayout(time_form)
        self.reset_capture_time = QPushButton("恢复默认 15:00:00 UTC")
        self.reset_capture_time.clicked.connect(lambda: self.date.setTime(QTime(15, 0)))
        time_box.addWidget(self.reset_capture_time)
        form.addRow(self.capture_time_toggle)
        form.addRow(self.capture_time_block)
        self.capture_time.timeChanged.connect(self.date.setTime)
        self.date.dateTimeChanged.connect(self.sync_capture_time)
        self.capture_time_toggle.toggled.connect(self.ui_update_time_summary)
        self.date.dateTimeChanged.connect(self.geometry_changed)
        self.topocentric = QCheckBox("使用拍摄地点")
        self.topocentric.toggled.connect(self.geometry_changed)
        form.addRow(self.topocentric)
        self.latitude, self.longitude = QDoubleSpinBox(), QDoubleSpinBox()
        self.latitude.setRange(-90, 90)
        self.longitude.setRange(-180, 180)
        for control in (self.latitude, self.longitude):
            control.setDecimals(4)
            control.valueChanged.connect(self.geometry_changed)
        form.addRow("纬度（北为正）", self.latitude)
        form.addRow("经度（东为正）", self.longitude)
        def show_location(checked, location_form=form):
            location_form.setRowVisible(self.latitude, checked)
            location_form.setRowVisible(self.longitude, checked)
        self.topocentric.toggled.connect(show_location)
        show_location(False)
        layout.addWidget(group)

        # -------------------------------------------------- 校准 · 自动识别
        group = QGroupBox("自动识别")
        auto_layout = QVBoxLayout(group)
        auto_layout.setContentsMargins(0, 4, 0, 0)
        auto_layout.setSpacing(8)
        self.identify_button = QPushButton("自动识别并标注")
        self.identify_button.setToolTip("按上方拍摄日期识别。首次需下载星历和高程数据，之后可离线使用。")
        self.identify_button.setProperty("primary", True)
        self.identify_button.clicked.connect(self.identify_photo)
        auto_layout.addWidget(self.identify_button)
        self.identification_status = QLabel("未识别")
        self.identification_status.setWordWrap(True)
        self.identification_status.setObjectName("statusStrong")
        auto_layout.addWidget(self.identification_status)
        layout.addWidget(group)

        # -------------------------------------------------- 校准 · 手动校准（默认折叠）
        # Collapsed so the automatic flow owns the page; ui_set_manual_section_expanded()
        # is the hook app.py uses to open it when a manual pick starts or after
        # identification fails. The toggle below stays visible as the entry point.
        self.manual_section_toggle, self.manual_section_block, group_box = \
            self.ui_collapsible("辅助校准 · 辅助找坑 / 已知地名取点")
        layout.addWidget(self.manual_section_toggle)
        layout.addWidget(self.manual_section_block)
        self.registration_tabs = QTabWidget()
        self.registration_tabs.setObjectName("subTabs")
        self.registration_tabs.setDocumentMode(True)
        self.registration_tabs.tabBar().setDrawBase(False)
        self.registration_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        manual = QWidget()
        automatic = QWidget()
        terrain = QWidget()
        craters = QWidget()
        self.registration_tabs.addTab(craters, "辅助找坑")
        self.registration_tabs.addTab(manual, "已知地名取点")
        self.crater_tab = craters
        self.crater_tab.installEventFilter(self)
        self.manual_tab = manual
        self.reference_tabs = QTabWidget()
        self.reference_tabs.setObjectName("subTabs")
        self.reference_tabs.setDocumentMode(True)
        self.reference_tabs.tabBar().setDrawBase(False)
        self.reference_tabs.addTab(automatic, "影像匹配")
        self.reference_tabs.addTab(terrain, "DEM 模拟")
        reference_layout.addWidget(self.reference_tabs, 1)
        reference_layout.addStretch()
        group_box.addWidget(self.registration_tabs)
        # With the manual section collapsed the page is shorter than the
        # viewport; the trailing stretch keeps sections at their natural height
        # instead of being stretched apart.
        layout.addStretch(1)

        # 影像匹配（自动配准入口）
        auto_box = QVBoxLayout(automatic)
        auto_box.setContentsMargins(0, 6, 0, 0)
        auto_box.setSpacing(8)
        self.nasa_button = QPushButton("自动配准 · NASA 同时刻影像")
        self.nasa_button.clicked.connect(self.auto_nasa)
        auto_box.addWidget(self.nasa_button)
        self.local_button = QPushButton("自动配准 · 本地参考工程")
        self.local_button.clicked.connect(self.auto_local)
        auto_box.addWidget(self.local_button)
        auto_box.addWidget(self.ui_note("NASA 参考支持 2026 年，需联网。"))
        self.nasa_button.setToolTip("使用地心视角。高倍局部照片可能因参考细节不足而无法匹配。")
        auto_box.addStretch()

        # 地形点（手动地形参考点）
        box = QVBoxLayout(manual)
        box.setContentsMargins(0, 6, 0, 0)
        box.setSpacing(8)
        box.addWidget(self.ui_note("选 3–6 个已知坑，分散取点，避免共线。"))
        box.addWidget(QLabel("1  选择地名"))
        self.feature_search = QLineEdit()
        self.feature_search.setPlaceholderText("搜索已知地形：哥白尼 / Copernicus")
        self.feature_search.textChanged.connect(self.search_features)
        self.feature_search.returnPressed.connect(self.ui_select_first_feature)
        box.addWidget(self.feature_search)
        self.feature_list = QListWidget()
        self.feature_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feature_list.setMaximumHeight(120)
        self.feature_list.itemDoubleClicked.connect(lambda item: self.start_pick())
        box.addWidget(self.feature_list, 1)
        box.addWidget(QLabel("2  标记坑中心"))
        self.manual_guide = self.ui_note("请打开照片", "statusStrong")
        box.addWidget(self.manual_guide)
        self.pick_button = QPushButton("选择地名后取点")
        self.pick_button.setToolTip("点击按钮，再到照片中点所选坑的完整坑缘中心。不要点亮斑或阴影中心；可先放大照片。同名取点会更新位置。")
        self.pick_button.clicked.connect(self.start_pick)
        self.pick_button.clicked.connect(self.ui_expand_for_pick)
        box.addWidget(self.pick_button)
        self.cancel_pick_button = QPushButton("取消取点 · Esc")
        self.cancel_pick_button.clicked.connect(self.cancel_pick)
        self.cancel_pick_button.hide()
        box.addWidget(self.cancel_pick_button)
        box.addWidget(QLabel("3  校准"))
        self.anchor_count = QLabel("0 个有效参考点 · 最少 3 个")
        box.addWidget(self.anchor_count)
        self.anchor_table = QTableWidget(0, 3)
        self.anchor_table.setHorizontalHeaderLabels(["使用", "地形", "偏差 px"])
        self.anchor_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.anchor_table.setColumnWidth(0, 40)
        self.anchor_table.setColumnWidth(2, 65)
        self.anchor_table.setMaximumHeight(140)
        self.anchor_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.anchor_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.anchor_table.verticalHeader().setVisible(False)
        self.anchor_table.setAlternatingRowColors(True)
        self.anchor_table.verticalHeader().setDefaultSectionSize(26)
        self.anchor_table.itemChanged.connect(self.anchor_enabled_changed)
        self.anchor_table.cellDoubleClicked.connect(self.repick_anchor)
        self.anchor_table.setToolTip("编号对应照片上的十字；双击重选，取消勾选停用。拟合偏差只表示参考点的一致性。")
        box.addWidget(self.anchor_table, 1)
        row = QHBoxLayout()
        remove = QPushButton("移除参考点")
        remove.clicked.connect(self.remove_anchor)
        clear = QPushButton("清空")
        clear.clicked.connect(self.clear_anchors)
        row.addWidget(remove)
        row.addWidget(clear)
        box.addLayout(row)
        self.solve_button = QPushButton("完成校准并生成标注")
        self.solve_button.setProperty("primary", True)
        self.solve_button.clicked.connect(self.solve_manual)
        box.addWidget(self.solve_button)
        self.guided_identify_button = QPushButton("用参考点自动配准")
        self.guided_identify_button.clicked.connect(self.identify_photo)
        self.guided_identify_button.setToolTip("确认一两个已知点后，自动搜索附近地形；周围图像仍需通过验证。")
        box.addWidget(self.guided_identify_button)
        self.registration_status = QLabel("")
        self.registration_status.setWordWrap(True)
        self.registration_status.setObjectName("statusStrong")
        box.addWidget(self.registration_status)
        box.addWidget(self.ui_note("双击重选 · 取消勾选停用"))
        toggle, block, advanced = self.ui_collapsible("高级 · 镜像与月面几何")
        box.addWidget(toggle)
        box.addWidget(block)
        mirror_form = self.ui_form()
        self.mirror = self.ui_combo()
        self.mirror.addItems(["自动判断镜像（至少三点）", "不镜像", "镜像"])
        mirror_form.addRow("镜像判定", self.mirror)
        advanced.addLayout(mirror_form)
        self.geometry_button = QPushButton("重新计算月面几何")
        self.geometry_button.clicked.connect(self.calculate_geometry)
        advanced.addWidget(self.geometry_button)
        self.geometry_status = self.ui_note("未计算", "statusLabel")
        self.geometry_button.setToolTip("校准时会自动计算，通常无需单独操作。")
        advanced.addWidget(self.geometry_status)
        self.feature_list.currentItemChanged.connect(self.manual_selection_changed)
        self.mirror.currentIndexChanged.connect(self.update_manual_guide)
        box.addStretch()

        # 疑似坑（检测与确认）
        self.build_crater_controls(craters)
        self.registration_tabs.currentChanged.connect(self.registration_page_changed)
        self.registration_tabs.currentChanged.connect(self.ui_update_registration_height)
        self.workspace_tabs.currentChanged.connect(self.review_page_changed)

        # -------------------------------------------------- 校准 · DEM 模拟页签
        terrain_box = QVBoxLayout(terrain)
        terrain_box.setContentsMargins(0, 6, 0, 0)
        terrain_box.setSpacing(8)
        self.dem_status = QLabel(Path(self.dem_path).name if self.dem_path else "尚未选择高程数据")
        self.dem_status.setWordWrap(True)
        self.dem_status.setObjectName("statusLabel")
        terrain_box.addWidget(self.dem_status)
        self.dem_import = QPushButton("导入本地 LOLA DEM（LBL / IMG）")
        self.dem_import.clicked.connect(self.import_dem)
        terrain_box.addWidget(self.dem_import)
        self.dem_download = QPushButton("下载基础 LOLA DEM · 约 33 MB")
        self.dem_download.clicked.connect(self.download_dem)
        terrain_box.addWidget(self.dem_download)
        self.terrain_search = QLineEdit()
        self.terrain_search.setPlaceholderText("搜索模拟区域：Aristarchus / 阿里斯塔克斯")
        self.terrain_search.textChanged.connect(self.search_terrain_features)
        self.terrain_search.returnPressed.connect(self.ui_select_first_terrain_match)
        terrain_box.addWidget(self.terrain_search)
        self.terrain_center = self.ui_combo()
        self.terrain_center.setMinimumContentsLength(12)
        self.terrain_center.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        terrain_box.addWidget(self.terrain_center)
        terrain_form = self.ui_form()
        self.terrain_width = QDoubleSpinBox()
        self.terrain_width.setRange(10, 2000)
        self.terrain_width.setValue(300)
        self.terrain_width.setSuffix(" km")
        terrain_form.addRow("视野宽度", self.terrain_width)
        terrain_box.addLayout(terrain_form)
        self.terrain_advanced_toggle, self.terrain_advanced_block, advanced_box = \
            self.ui_collapsible("渲染参数 · 图像尺寸 / 光照 / 投影")
        terrain_box.addWidget(self.terrain_advanced_toggle)
        terrain_box.addWidget(self.terrain_advanced_block)
        advanced_form = self.ui_form()
        self.terrain_size = self.ui_combo()
        self.terrain_size.addItems(["512", "768", "1024", "1536"])
        self.terrain_size.setCurrentText("768")
        advanced_form.addRow("图像边长", self.terrain_size)
        self.terrain_model = self.ui_combo()
        self.terrain_model.addItems(["Lommel-Seeliger", "Lambert"])
        advanced_form.addRow("光照模型", self.terrain_model)
        self.terrain_gamma = QDoubleSpinBox()
        self.terrain_gamma.setRange(.3, 4)
        self.terrain_gamma.setSingleStep(.1)
        self.terrain_gamma.setValue(1.6)
        advanced_form.addRow("提亮 Gamma", self.terrain_gamma)
        advanced_box.addLayout(advanced_form)
        self.terrain_shadows = QCheckBox("计算地形投影（耗时稍长）")
        self.terrain_shadows.setChecked(True)
        advanced_box.addWidget(self.terrain_shadows)
        self.terrain_button = QPushButton("生成模拟图")
        self.terrain_button.setProperty("primary", True)
        self.terrain_button.clicked.connect(self.generate_terrain)
        terrain_box.addWidget(self.terrain_button)
        terrain_box.addWidget(self.ui_note("基础采样约 1.9 km，近月缘区域不适用。"))
        self.terrain_button.setToolTip("球面投影与坡度光照参考。增加输出尺寸不会增加地形细节；高倍照片需更高分辨率 DEM。")
        terrain_box.addStretch()
        self.terrain_search.setText("Aristarchus")
        for control in (self.terrain_width, self.terrain_gamma):
            control.valueChanged.connect(self.terrain_settings_changed)
        for control in (self.terrain_center, self.terrain_size, self.terrain_model):
            control.currentIndexChanged.connect(self.terrain_settings_changed)
        self.terrain_shadows.toggled.connect(self.terrain_settings_changed)

        # -------------------------------------------------- 标注
        group = QGroupBox("筛选与数量")
        form = self.ui_form(group)
        self.kind = self.ui_combo()
        self.kind.addItems(["全部"] + sorted(set(f["kind"] for f in self.catalog)))
        self.kind.currentTextChanged.connect(self.style_changed)
        form.addRow("地形类别", self.kind)
        self.diameter = QDoubleSpinBox()
        self.diameter.setRange(0, 3000)
        self.diameter.setSuffix(" km")
        self.diameter.setValue(40)
        self.diameter.valueChanged.connect(self.style_changed)
        form.addRow("最小直径", self.diameter)
        self.maximum = QSpinBox()
        self.maximum.setRange(1, 1000)
        self.maximum.setValue(self.project.max_labels)
        self.maximum.valueChanged.connect(self.style_changed)
        form.addRow("最多显示", self.maximum)
        self.lit = QCheckBox("仅标注受光地形")
        self.lit.setToolTip("检查照片上的坑体与坑缘明暗，保留亮坑缘、暗坑底；避免日期计算误删可见地形。")
        self.lit.setChecked(True)
        self.lit.toggled.connect(self.style_changed)
        form.addRow(self.lit)
        labels_layout.addWidget(group)

        group = QGroupBox("名称与文字")
        form = self.ui_form(group)
        self.language = self.ui_combo()
        self.language.addItems(["双语", "英文", "中文"])
        self.language.currentTextChanged.connect(self.style_changed)
        form.addRow("名称语言", self.language)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(.05, 8.)
        self.font_size.setDecimals(2)
        self.font_size.setSingleStep(.1)
        self.font_size.setSuffix(" %")
        self.font_size.setValue(self.project.font_percent)
        self.font_size.setToolTip("按照片短边计算，缩放与导出保持相同比例。调整后点击重新生成标注。")
        self.font_size.valueChanged.connect(self.style_changed)
        form.addRow("字号（短边比例）", self.font_size)
        self.font_pixels_hint = QLabel("")
        self.font_pixels_hint.setObjectName("statusLabel")
        form.addRow(self.font_pixels_hint)
        self.color_button = QPushButton("选择文字与引线颜色")
        self.color_button.clicked.connect(self.choose_color)
        form.addRow(self.color_button)
        labels_layout.addWidget(group)

        group = QGroupBox("排版选项")
        option_box = QVBoxLayout(group)
        option_box.setContentsMargins(0, 4, 0, 0)
        option_box.setSpacing(8)
        self.optimize_layout = QCheckBox("自动避让")
        self.optimize_layout.setToolTip("避让标签、地形中心和引线。")
        self.optimize_layout.setChecked(True)
        self.optimize_layout.toggled.connect(self.style_changed)
        option_box.addWidget(self.optimize_layout)
        self.crater_outlines = QCheckBox("大坑显示坑缘圈")
        self.crater_outlines.setChecked(True)
        self.crater_outlines.toggled.connect(self.style_changed)
        self.crater_outlines.setToolTip("直径至少 35 km 且在照片中足够大的环形山显示轮廓，小坑保留短引线。")
        option_box.addWidget(self.crater_outlines)
        outline_form = QFormLayout()
        self.crater_outline_shape = self.ui_combo()
        self.crater_outline_shape.addItem("椭圆", "ellipse")
        self.crater_outline_shape.addItem("坑缘轮廓（手绘风）", "terrain")
        self.crater_outline_shape.setToolTip("椭圆：将投影坑缘拟合为平滑椭圆。坑缘轮廓：保留高程数据中的不规则形状；无高程坑缘时使用目录参考圈。")
        self.crater_outline_shape.currentIndexChanged.connect(self.style_changed)
        outline_form.addRow("轮廓形状", self.crater_outline_shape)
        option_box.addLayout(outline_form)
        labels_layout.addWidget(group)

        group = QGroupBox("应用与标签列表")
        apply_box = QVBoxLayout(group)
        apply_box.setContentsMargins(0, 4, 0, 0)
        apply_box.setSpacing(8)
        self.generate_labels_button = QPushButton("重新生成标注")
        self.generate_labels_button.setProperty("primary", True)
        self.generate_labels_button.clicked.connect(self.apply_label_settings)
        apply_box.addWidget(self.generate_labels_button)
        self.settings_status = QLabel("")
        self.settings_status.setWordWrap(True)
        self.settings_status.setObjectName("statusLabel")
        apply_box.addWidget(self.settings_status)
        self.layout_status = QLabel("")
        self.layout_status.setWordWrap(True)
        self.layout_status.setObjectName("statusLabel")
        apply_box.addWidget(self.layout_status)
        reflow = QPushButton("重新自动排布标签")
        reflow.clicked.connect(self.reflow_labels)
        apply_box.addWidget(reflow)
        self.names = QListWidget()
        self.names.itemChanged.connect(self.label_visibility_changed)
        self.names.itemDoubleClicked.connect(lambda item: self.edit_label(self.catalog_by_id[item.data(Qt.ItemDataRole.UserRole)]))
        self.names.setMinimumHeight(170)
        apply_box.addWidget(self.names, 1)
        restore = QPushButton("恢复名称与默认位置")
        restore.clicked.connect(self.reset_labels)
        apply_box.addWidget(restore)
        apply_box.addWidget(self.ui_note("拖动调整位置 · 双击编辑文字"))
        self.language.setToolTip("中文译名未收录时显示官方原名。")
        # The label list absorbs any surplus page height on tall windows.
        labels_layout.addWidget(group, 1)
        self.catalog_button = QPushButton(f"更新 USGS 地名（现有 {len(self.catalog):,} 项）")
        self.catalog_button.clicked.connect(self.update_catalog)
        labels_layout.addWidget(self.catalog_button)
        labels_layout.addStretch()

        # -------------------------------------------------- 疑似坑确认操作条
        # Only the current candidate/name pair and confirmation stay pinned.
        # Detection, candidates and name search share the page's scroll area.
        self.crater_action_panel = QWidget()
        self.crater_action_panel.setObjectName("confirmPanel")
        self.ui_crater_scroll_timer = QTimer(self)
        self.ui_crater_scroll_timer.setSingleShot(True)
        self.ui_crater_scroll_timer.timeout.connect(self.ui_reveal_crater_controls)
        # Showing either widget is app.py's way of entering a manual flow;
        # the section opens with them (see eventFilter).
        for review_widget in (self.cancel_pick_button, self.crater_action_panel):
            review_widget.installEventFilter(self)
        self.manual_section_toggle.toggled.connect(self.ui_reconcile_confirm_bar)
        self.manual_section_toggle.toggled.connect(self.review_page_changed)
        action_box = QVBoxLayout(self.crater_action_panel)
        action_box.setContentsMargins(10, 8, 10, 8)
        action_box.setSpacing(5)
        self.ui_crater_selection = QLabel()
        self.ui_crater_selection.setObjectName("reviewSelection")
        self.ui_crater_name = QLabel()
        self.ui_crater_name.setObjectName("statusStrong")
        self.ui_crater_name.setMinimumWidth(0)
        self.ui_crater_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        action_box.addWidget(self.ui_crater_selection)
        action_box.addWidget(self.ui_crater_name)
        self.crater_anchor_button.setProperty("primary", True)
        action_box.addWidget(self.crater_anchor_button)
        calibration_footer.addWidget(self.crater_action_panel)
        self.crater_action_panel.hide()

        # -------------------------------------------------- 画布在左、检查器在右
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        canvas_panel = QWidget()
        canvas_box = QVBoxLayout(canvas_panel)
        canvas_box.setContentsMargins(0, 0, 0, 0)
        canvas_box.setSpacing(0)
        header = QWidget()
        header.setObjectName("canvasHeader")
        header_box = QHBoxLayout(header)
        header_box.setContentsMargins(16, 9, 16, 9)
        header_box.setSpacing(12)
        self.canvas_title = QLabel("月面照片")
        self.canvas_title.setObjectName("canvasTitle")
        self.canvas_details = QLabel("滚轮缩放 · 拖动空白处平移")
        self.canvas_details.setObjectName("canvasDetails")
        header_box.addWidget(self.canvas_title)
        header_box.addStretch()
        header_box.addWidget(self.canvas_details)
        canvas_box.addWidget(header)
        canvas_box.addWidget(self.canvas, 1)
        splitter.addWidget(canvas_panel)
        splitter.addWidget(self.sidebar)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1050, 390])
        self.setCentralWidget(splitter)
        self.search_features("")
        self.ui_refresh_crater_review()

    def build_crater_controls(self, page):
        box = QVBoxLayout(page)
        self.crater_controls_layout = box
        box.setContentsMargins(0, 6, 0, 0)
        box.setSpacing(8)
        self.crater_settings_toggle, self.crater_settings_block, config_box = \
            self.ui_collapsible("检测设置 · 半径 8–180 px")
        box.addWidget(self.crater_settings_toggle)
        box.addWidget(self.crater_settings_block)
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        self.crater_min, self.crater_max = QSpinBox(), QSpinBox()
        for control in (self.crater_min, self.crater_max):
            control.setRange(3, 4000)
            control.setSuffix(" px")
        self.crater_min.setValue(8)
        self.crater_max.setValue(180)
        form.addWidget(QLabel("最小半径"), 0, 0)
        form.addWidget(QLabel("最大半径"), 0, 1)
        form.addWidget(self.crater_min, 1, 0)
        form.addWidget(self.crater_max, 1, 1)
        self.crater_sensitivity = QSpinBox()
        self.crater_sensitivity.setRange(0, 100)
        self.crater_sensitivity.setValue(50)
        self.crater_sensitivity.setToolTip("调高会保留更多候选，也会增加误检。")
        form.addWidget(QLabel("灵敏度"), 2, 0)
        form.addWidget(self.crater_sensitivity, 3, 0)
        self.crater_limit = QSpinBox()
        self.crater_limit.setRange(1, 500)
        self.crater_limit.setValue(80)
        form.addWidget(QLabel("候选上限"), 2, 1)
        form.addWidget(self.crater_limit, 3, 1)
        config_box.addLayout(form)
        self.crater_viewport = QCheckBox("只检测当前视野")
        self.crater_viewport.setToolTip("先放大到感兴趣的区域，减少大片阴影、边框和水印的干扰。")
        config_box.addWidget(self.crater_viewport)
        self.crater_button = QPushButton("检测疑似坑中心")
        self.crater_button.setProperty("primary", True)
        self.crater_button.clicked.connect(self.detect_photo_craters)
        box.addWidget(self.crater_button)
        self.crater_status = QLabel("未检测")
        self.crater_status.setWordWrap(True)
        self.crater_status.setObjectName("statusLabel")
        box.addWidget(self.crater_status)
        candidate_heading = QHBoxLayout()
        candidate_heading.addWidget(QLabel("1  选择候选坑"))
        candidate_heading.addStretch()
        self.ui_crater_tools_toggle, self.ui_crater_tools_block, tools_box = self.ui_collapsible("更多操作")
        candidate_heading.addWidget(self.ui_crater_tools_toggle)
        box.addLayout(candidate_heading)
        self.crater_list = QListWidget()
        self.crater_list.currentRowChanged.connect(self.select_crater_candidate)
        self.crater_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.crater_list.setToolTip("选列表中的编号，或点击照片中的候选坑。当前编号始终显示在底部确认条。")
        box.addWidget(self.crater_list)
        self.crater_overlay_toggle = QCheckBox("显示全部候选轮廓")
        self.crater_overlay_toggle.toggled.connect(self.show_crater_overlays)
        row = QHBoxLayout()
        self.crater_review_actions = row
        self.crater_remove = QPushButton("移除候选")
        self.crater_remove.clicked.connect(self.remove_crater_candidate)
        self.crater_repick = QPushButton("重选中心")
        self.crater_repick.clicked.connect(self.repick_crater_candidate)
        self.crater_export = QPushButton("导出 CSV")
        self.crater_export.clicked.connect(self.export_crater_candidates)
        row.addWidget(self.crater_repick)
        row.addWidget(self.crater_remove)
        row.addWidget(self.crater_export)
        tools_box.addLayout(row)
        tools_box.addWidget(self.crater_overlay_toggle)
        box.addWidget(self.ui_crater_tools_block)
        box.addWidget(QLabel("2  选择地名"))
        self.crater_search = QLineEdit()
        self.crater_search.setPlaceholderText("搜索环形山：Hadley C / 哥白尼")
        self.crater_search.textChanged.connect(self.search_crater_features)
        self.crater_search.returnPressed.connect(self.ui_select_first_crater_match)
        box.addWidget(self.crater_search)
        # Show search hits directly, including a single result. A combo box
        # silently preselects that result and opens a popup over confirmation.
        self.crater_feature = QListWidget()
        self.crater_feature.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.crater_feature.setToolTip("点击地名后确认。这里只列环形山；月溪、山脉等在“已知地名取点”中选择。")
        self.crater_feature.currentItemChanged.connect(self.update_crater_buttons)
        self.crater_feature.hide()
        box.addWidget(self.crater_feature)
        self.crater_anchor_button = QPushButton("确认地名，加入参考点")
        self.crater_anchor_button.clicked.connect(self.use_crater_candidate)
        box.addWidget(self.crater_anchor_button)
        self.crater_finish_button = QPushButton("查看已确认的参考点并校准")
        self.crater_finish_button.clicked.connect(self.show_manual_points)
        box.addWidget(self.crater_finish_button)
        self.crater_button.setToolTip("只检测疑似坑中心，地名需人工确认。阴影、山脊可能误检；中心有偏差时可重选。半径以原图像素计算。")
        box.addStretch()
        for control in (self.crater_min, self.crater_max, self.crater_sensitivity, self.crater_limit):
            control.valueChanged.connect(self.crater_settings_changed)
        self.crater_viewport.toggled.connect(self.crater_settings_changed)
        self.update_crater_buttons()
