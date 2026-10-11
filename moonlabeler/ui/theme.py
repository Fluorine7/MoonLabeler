# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Application chrome stylesheet; does not control exported annotations.

Design language: "observatory dark". The photo owns the window — the canvas
sits on the near-black left side, the inspector panel on the right recedes
into a calm dark blue-grey. A single warm "moon dust" accent is reserved for
primary actions and focus; sections are flat (hairlines and spacing instead
of boxed frames) so the sidebar reads as text hierarchy, not a stack of boxes.
Checkboxes and item-view check indicators are plain: an empty bordered box
when unchecked, a light check mark inside the same box when checked
(assets/check_dark.png, drawn programmatically).
"""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
CHECK_MARK = (ASSETS / "check_dark.png").as_posix()

BG = "#131821"          # window chrome / toolbar / status bar
PANEL = "#171d28"       # inspector panel
SURFACE = "#0f141d"     # inputs, lists, tables
SURFACE_HI = "#1c2432"  # raised surface (context bar)
LINE = "#242e3c"        # hairlines
LINE_HI = "#3a4a61"     # hovered / emphasized hairlines
TEXT = "#dfe6ef"
TEXT_2 = "#9badc0"
TEXT_3 = "#76889d"
ACCENT = "#d9a96c"
ACCENT_HI = "#e8be86"
ACCENT_DOWN = "#c6975c"
ACCENT_TEXT = "#1f1506"
FOCUS = "#5d87b6"
SELECT = "#31435c"
DISABLED_TEXT = "#5c6a7d"

STYLE = f"""
/* Widgets stay transparent by default so panels show through; surfaces opt in. */
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QWidget:disabled {{ color: {DISABLED_TEXT}; }}
QWidget#inspectorPanel {{ background: {PANEL}; }}
QWidget#canvasHeader {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
QCalendarWidget {{ background: #131a25; }}

/* ---- toolbar ---------------------------------------------------------- */
QToolBar {{ background: {PANEL}; border: 0; border-bottom: 1px solid {LINE};
           padding: 7px 14px; spacing: 3px; }}
QToolBar::separator {{ background: {LINE}; width: 1px; margin: 5px 8px; }}
QToolButton {{ background: transparent; border: 0; border-radius: 6px;
              padding: 6px 11px; color: #aebccc; }}
QToolButton:hover {{ background: #242f3e; color: #eef3f9; }}
QToolButton:pressed {{ background: #2b3748; }}
QToolButton:disabled {{ color: {DISABLED_TEXT}; background: transparent; }}
QToolButton[primary="true"] {{ background: {ACCENT}; color: {ACCENT_TEXT};
                              font-weight: 600; padding: 6px 14px; }}
QToolButton[primary="true"]:hover {{ background: {ACCENT_HI}; }}
QToolButton[primary="true"]:pressed {{ background: {ACCENT_DOWN}; }}
QToolButton[primary="true"]:disabled {{ background: #4a4335; color: #8b8172; }}
QToolButton#sectionToggle {{ padding: 3px 2px; color: {TEXT_2};
                            font-weight: 600; font-size: 12px; }}
QToolButton#sectionToggle:hover {{ background: transparent; color: #dbe5f0; }}

/* ---- buttons ----------------------------------------------------------- */
QPushButton {{ background: #222c3a; border: 1px solid #333f51; border-radius: 6px;
              padding: 6px 12px; color: #cfd9e5; }}
QPushButton:hover {{ background: #2b3849; border-color: #47596f; color: #eef3f9; }}
QPushButton:pressed {{ background: #26303f; }}
QPushButton:disabled {{ color: {DISABLED_TEXT}; background: #1d2531; border-color: #2a3441; }}
QPushButton[primary="true"] {{ background: {ACCENT}; border-color: {ACCENT};
                              color: {ACCENT_TEXT}; font-weight: 600; padding: 7px 12px; }}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton[primary="true"]:pressed {{ background: {ACCENT_DOWN}; border-color: {ACCENT_DOWN}; }}
QPushButton[primary="true"]:disabled {{ background: #453f32; border-color: #453f32; color: #8b8172; }}

/* ---- flat sections ------------------------------------------------------ */
QGroupBox {{ border: 0; margin-top: 16px; padding: 1px 0 0 0; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
                   left: 1px; padding: 0; color: {TEXT_2}; font-weight: 600; }}
QWidget#confirmPanel {{ background: {SURFACE_HI}; border-top: 1px solid {LINE_HI}; }}
QLabel#reviewSelection {{ color: #eef3f9; font-weight: 600; }}

/* ---- inputs -------------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {{
    background: {SURFACE}; border: 1px solid #2e3a4b; border-radius: 6px;
    padding: 5px 8px; color: {TEXT}; selection-background-color: {SELECT};
    selection-color: #f0f4f9; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateTimeEdit:focus {{ border-color: {FOCUS}; background: #111823; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QDateTimeEdit:disabled {{ background: #151b25; border-color: #262f3b; color: {DISABLED_TEXT}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{ background: #1a212d; border: 1px solid {LINE_HI};
    border-radius: 6px; padding: 4px; color: {TEXT}; outline: 0;
    selection-background-color: {SELECT}; selection-color: #f0f4f9; }}

QCheckBox {{ spacing: 7px; color: #c3cedb; }}
QCheckBox:disabled {{ color: {DISABLED_TEXT}; }}
/* One plain check style everywhere: form checkboxes, label list, anchor table. */
QCheckBox::indicator, QListView::indicator, QTableView::indicator {{
    width: 13px; height: 13px; border: 1px solid #3a485c;
    border-radius: 4px; background: {SURFACE}; }}
QCheckBox::indicator:hover, QListView::indicator:hover,
QTableView::indicator:hover {{ border-color: #4d6079; }}
QCheckBox::indicator:checked, QListView::indicator:checked,
QTableView::indicator:checked {{ image: url({CHECK_MARK}); }}
QCheckBox::indicator:disabled, QListView::indicator:disabled,
QTableView::indicator:disabled {{ border-color: #333f4d; background: #151b25; }}

/* ---- lists and tables ----------------------------------------------------- */
QListWidget, QTableWidget {{ background: {SURFACE}; border: 1px solid {LINE};
                            border-radius: 7px; color: #d5dee9;
                            alternate-background-color: #121823; }}
QListWidget::item {{ padding: 5px 7px; border-radius: 4px; }}
QListWidget::item:hover {{ background: #1b2534; }}
QListWidget::item:selected {{ background: {SELECT}; color: #f0f4f9; }}
QTableWidget {{ gridline-color: #1d2634; }}
QHeaderView::section {{ background: #1a2230; color: #93a5ba; padding: 6px 8px;
                       border: 0; border-bottom: 1px solid {LINE}; font-size: 12px; }}

/* ---- tabs: level 1 = segmented, level 2 = underline ------------------------ */
QTabWidget::pane {{ border: 0; }}
QTabWidget#workspaceTabs > QTabBar::tab {{ background: #1d2532; color: #8fa1b6;
    padding: 7px 4px; min-width: 84px; margin-right: 4px; border-radius: 6px;
    font-size: 12px; font-weight: 600; }}
QTabWidget#workspaceTabs > QTabBar::tab:selected {{ background: #2c3950; color: #eef3f9; }}
QTabWidget#workspaceTabs > QTabBar::tab:hover:!selected {{ color: #c6d2e0; }}
QTabWidget#subTabs > QTabBar::tab {{ background: transparent; color: {TEXT_3};
    padding: 4px 2px 5px; min-width: 100px; margin-right: 12px; border-bottom: 2px solid transparent;
    font-size: 12px; font-weight: 600; }}
QTabWidget#subTabs > QTabBar::tab:selected {{ color: #e8eef6; border-bottom: 2px solid {ACCENT}; }}
QTabWidget#subTabs > QTabBar::tab:hover:!selected {{ color: #b9c7d8; }}

/* ---- scrolling, status, splitter ------------------------------------------- */
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 1px 1px 1px 0; }}
QScrollBar::handle:vertical {{ background: #313e4f; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #43536a; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0 1px 1px 1px; }}
QScrollBar::handle:horizontal {{ background: #313e4f; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #43536a; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; }}
QStatusBar {{ background: {PANEL}; color: #8fa0b4; border-top: 1px solid {LINE}; font-size: 12px; }}
QStatusBar::item {{ border: 0; }}
QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:hover {{ background: #3d4d66; }}

/* ---- text roles ------------------------------------------------------------- */
QLabel#title {{ font-size: 15px; font-weight: 700; color: #ecf1f8; }}
QLabel#subtitle {{ font-size: 11px; color: {TEXT_3}; }}
QLabel#canvasTitle {{ font-size: 13px; font-weight: 600; color: #e2e9f2; }}
QLabel#canvasDetails {{ font-size: 12px; color: {TEXT_3}; }}
QLabel#noteLabel {{ font-size: 12px; color: {TEXT_3}; }}
QLabel#statusLabel {{ font-size: 12px; color: #93a6bb; }}
QLabel#statusStrong {{ font-size: 12px; color: #c7d5e6; }}

QToolTip {{ background: #1e2735; color: #dde5ef; border: 1px solid {LINE_HI};
           padding: 6px 8px; font-size: 12px; }}
QMessageBox {{ background: {PANEL}; }}
QMessageBox QLabel {{ color: {TEXT}; background: transparent; }}

/* ---- calendar popup (date field) ---------------------------------------------- */
QCalendarWidget QWidget {{ alternate-background-color: #1b2432; }}
QCalendarWidget QToolButton {{ background: #232d3b; color: #dce4ef; border-radius: 5px;
                              padding: 4px 8px; font-size: 12px; }}
QCalendarWidget QToolButton:hover {{ background: #2e3a4b; }}
QCalendarWidget #qt_calendar_navigationbar {{ background: #1c2532; }}
QCalendarWidget QAbstractItemView:enabled {{ background: #131a25; color: #cfd9e5;
    selection-background-color: #375072; selection-color: #f0f4f9; }}
"""
