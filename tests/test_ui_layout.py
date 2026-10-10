# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Layout-contract tests for the rebuilt inspector (moonlabeler/ui only)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from moonlabeler.app import MainWindow


def make_window():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    application.processEvents()
    return window, application


def test_workspace_tabs_keep_calibration_annotation_reference_contract():
    window, application = make_window()
    try:
        assert [window.workspace_tabs.tabText(i) for i in range(window.workspace_tabs.count())] \
            == ["校准", "标注", "参考"]
        assert [window.registration_tabs.tabText(i) for i in range(window.registration_tabs.count())] \
            == ["辅助找坑", "已知地名取点"]
        assert window.registration_tabs.currentWidget() is window.crater_tab
        assert window.reference_tabs.count() == 2
        # Both assistance paths remain inside the calibration scroll area.
        assert window.scroll.widget().isAncestorOf(window.feature_search)
    finally:
        window.dirty = False
        window.close()


def test_crater_confirmation_bar_is_pinned_outside_the_scrolling_content():
    window, application = make_window()
    try:
        page0 = window.workspace_tabs.widget(0)
        panel = window.crater_action_panel
        assert page0.isAncestorOf(panel)
        assert not window.scroll.widget().isAncestorOf(panel), \
            "确认操作条必须固定在校准页脚，而不是随检测设置一起滚动"
        assert panel.isHidden()
        # app.py's own visibility rule: calibration page + 疑似坑 tab.
        window.registration_tabs.setCurrentWidget(window.crater_tab)
        window.ui_set_manual_section_expanded(True)
        application.processEvents()
        assert panel.isVisible()
        window.registration_tabs.setCurrentWidget(window.manual_tab)
        application.processEvents()
        assert not panel.isVisible()
        window.registration_tabs.setCurrentWidget(window.crater_tab)
        window.workspace_tabs.setCurrentIndex(1)
        application.processEvents()
        assert not panel.isVisible()
    finally:
        window.dirty = False
        window.close()


def test_canvas_is_the_primary_pane_and_sits_left_of_the_inspector():
    window, application = make_window()
    try:
        splitter = window.centralWidget()
        assert splitter.indexOf(window.sidebar) == 1
        window.resize(1440, 930)
        application.processEvents()
        assert window.canvas.width() > window.sidebar.width()
        assert splitter.widget(0).isAncestorOf(window.canvas)
    finally:
        window.dirty = False
        window.close()


def test_primary_actions_are_marked_for_the_theme():
    window, application = make_window()
    try:
        for button in (window.identify_button, window.solve_button,
                       window.generate_labels_button, window.crater_button):
            assert button.property("primary") is True
        open_action = next(a for a in window.actions if a.text() == "打开照片")
        assert window.toolbar.widgetForAction(open_action).property("primary") is True
        texts = [a.text() for a in window.actions]
        for expected in ("打开工程", "保存工程", "导出 PNG", "导出 SVG", "适合窗口", "帮助"):
            assert expected in texts
        shortcuts = {a.text(): a.shortcut().toString() for a in window.actions}
        assert shortcuts["打开照片"] == "Ctrl+O"
        assert shortcuts["保存工程"] == "Ctrl+S"
        assert shortcuts["适合窗口"] == "Ctrl+0"
    finally:
        window.dirty = False
        window.close()


def test_low_frequency_settings_collapse_but_stay_wired():
    window, application = make_window()
    try:
        window.registration_tabs.setCurrentWidget(window.crater_tab)
        window.ui_set_manual_section_expanded(True)
        assert not window.crater_settings_block.isVisible()
        window.crater_settings_toggle.click()
        assert window.crater_settings_block.isVisible()
        # Values changed while collapsed must still reach the project state.
        window.crater_settings_toggle.click()
        window.crater_min.setValue(20)
        assert window.project.crater_settings["min_radius"] == 20
        assert not window.terrain_advanced_block.isVisible()
        window.terrain_gamma.setValue(2.0)
        assert window.project.terrain_settings["gamma"] == 2.0
        window.workspace_tabs.setCurrentIndex(2)
        window.reference_tabs.setCurrentIndex(1)
        window.terrain_advanced_toggle.click()
        assert window.terrain_advanced_block.isVisible()
    finally:
        window.dirty = False
        window.close()


def test_every_business_consumed_widget_exists():
    window, application = make_window()
    try:
        required = (
            "toolbar", "sidebar", "workspace_tabs", "registration_tabs",
            "reference_tabs", "crater_tab", "scroll", "geometry_group",
            "date", "topocentric", "latitude", "longitude",
            "geometry_button", "geometry_status",
            "identify_button", "identification_status",
            "nasa_button", "local_button",
            "feature_search", "feature_list", "pick_button", "anchor_table",
            "mirror", "solve_button", "registration_status",
            "dem_status", "dem_import", "dem_download",
            "terrain_search", "terrain_center", "terrain_width", "terrain_size",
            "terrain_model", "terrain_gamma", "terrain_shadows", "terrain_button",
            "kind", "diameter", "maximum", "language", "font_size",
            "font_pixels_hint", "color_button", "lit", "optimize_layout",
            "crater_outlines", "crater_overlay_toggle", "generate_labels_button", "settings_status",
            "layout_status", "names", "catalog_button",
            "crater_settings_toggle", "crater_settings_block",
            "crater_min", "crater_max", "crater_sensitivity", "crater_limit",
            "crater_viewport", "crater_button", "crater_status", "crater_list",
            "crater_remove", "crater_repick", "crater_export",
            "crater_search", "crater_feature", "crater_anchor_button",
            "crater_action_panel", "canvas_title", "canvas_details",
        )
        missing = [name for name in required if not hasattr(window, name)]
        assert not missing, f"业务契约控件缺失: {missing}"
        # The image-matching entries live inside the 参考 page's first tab.
        assert window.reference_tabs.widget(0).isAncestorOf(window.nasa_button)
        assert window.reference_tabs.widget(0).isAncestorOf(window.local_button)
        assert window.reference_tabs.widget(1).isAncestorOf(window.terrain_button)
        # Persistent annotation style and temporary review overlays are separate.
        assert window.crater_outlines.text() == "大坑显示坑缘圈"
    finally:
        window.dirty = False
        window.close()


def test_enter_prefills_first_search_hit_and_escape_leaves_pick_mode():
    window, application = make_window()
    try:
        window.search_features("阿里斯塔克斯")
        assert window.feature_list.count() > 0
        assert window.feature_list.currentRow() < 0
        window.ui_select_first_feature()
        assert window.feature_list.currentRow() == 0
        window.search_crater_features("Aristarchus")
        assert window.crater_feature.count() > 0
        window.ui_select_first_crater_match()
        assert window.crater_feature.currentItem().data(Qt.ItemDataRole.UserRole) is not None
        window.search_terrain_features("哥白尼")
        window.ui_select_first_terrain_match()
        assert window.terrain_center.currentIndex() == 0
        # Escape is wired on the canvas and resets the pick state.
        window.canvas.picking = True
        window.ui_cancel_pick()
        assert not window.canvas.picking
    finally:
        window.dirty = False
        window.close()


def test_manual_calibration_section_collapsed_by_default_with_expand_hook():
    window, application = make_window()
    try:
        # Collapsed on start, but the toggle stays visible as the entry point.
        assert not window.manual_section_block.isVisible()
        assert window.ui_manual_section_expanded() is False
        assert window.manual_section_toggle.isVisible()
        # All contract widgets keep living inside the collapsible block.
        assert window.manual_section_block.isAncestorOf(window.registration_tabs)
        assert window.manual_section_block.isAncestorOf(window.feature_search)
        assert window.manual_section_block.isAncestorOf(window.crater_button)
        # Public expand/collapse hook drives visibility both ways.
        window.ui_set_manual_section_expanded(True)
        application.processEvents()
        assert window.manual_section_block.isVisible()
        assert not window.crater_settings_block.isVisible()
        window.registration_tabs.setCurrentWidget(window.crater_tab)
        window.crater_settings_toggle.click()
        assert window.crater_settings_block.isVisible()
        window.ui_set_manual_section_expanded(False)
        application.processEvents()
        assert not window.manual_section_block.isVisible()
        # app.py revealing the confirmation bar (辅助找坑 review) expands the
        # section in the same moment, keeping controls and bar consistent.
        # Re-entering the review tab is the real app.py path: it re-evaluates
        # the bar via review_page_changed, and the section follows.
        assert not window.crater_action_panel.isVisible()
        window.registration_tabs.setCurrentWidget(window.manual_tab)
        window.registration_tabs.setCurrentWidget(window.crater_tab)
        application.processEvents()
        assert window.crater_action_panel.isVisible()
        assert window.ui_manual_section_expanded() is True
        # Entering manual picking expands the section: an extra ui_ listener on
        # pick_button.clicked opens it alongside the business callback. A feature
        # is selected first, mirroring the real flow (button is disabled otherwise).
        window.open_example()
        feature = next(f for f in window.catalog if f["name"] == "Copernicus")
        window.feature_search.setText("Copernicus")
        for row in range(window.feature_list.count()):
            if window.feature_list.item(row).data(Qt.ItemDataRole.UserRole) == feature["id"]:
                window.feature_list.setCurrentRow(row)
                break
        window.ui_set_manual_section_expanded(False)
        window.pick_button.click()
        application.processEvents()
        assert window.ui_manual_section_expanded() is True
        # 拍摄条件 stays outside the collapsible and always visible.
        assert window.geometry_group.isVisible()
    finally:
        window.dirty = False
        window.close()
