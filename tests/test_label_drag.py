# SPDX-License-Identifier: GPL-3.0-or-later
"""Real viewport gestures must not rearrange labels during navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QFocusEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from moonlabeler.app import Canvas, Annotation
from moonlabeler.annotation_style import ART_STYLES
from moonlabeler.project import Project
from moonlabeler.ui.map_layers import ElevationLegend

CTRL = Qt.KeyboardModifier.ControlModifier  # Qt maps this to Command on macOS.
NONE = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton

@pytest.fixture(params=[(zoom, style) for style in ART_STYLES for zoom in (1., 2.)])
def view(request):
    app = QApplication.instance() or QApplication([])
    canvas = Canvas(); canvas.resize(600, 450)
    canvas.setSceneRect(0, 0, 2000, 1600)
    moves, edits = [], []
    zoom, style = request.param
    label = Annotation({'id': 'test', 'name': 'Tycho'}, (850, 700), 'Tycho', Project(art_style=style),
                       lambda *args: moves.append(args), edits.append)
    canvas.scene().addItem(label); canvas.scene().addItem(label.line)
    label.setPos(950, 780); moves.clear()
    canvas.scale(zoom, zoom)
    canvas.show(); canvas.centerOn(1000, 800); app.processEvents()
    yield canvas, label, moves, edits
    canvas.close()


def point(canvas, label):
    return canvas.mapFromScene(label.mapToScene(label.boundingRect().center()))


def mouse(canvas, kind, pos, modifiers=NONE):
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else LEFT
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else LEFT
    event = QMouseEvent(kind, QPointF(pos), QPointF(canvas.viewport().mapToGlobal(pos)),
                        button, buttons, modifiers)
    QApplication.sendEvent(canvas.viewport(), event)


@pytest.fixture(params=[.5, 2.])
def legend_view(request):
    application = QApplication.instance() or QApplication([])
    canvas = Canvas()
    canvas.resize(600, 450)
    canvas.setSceneRect(0, 0, 2000, 1600)
    project = Project(art_style='manuscript', elevation_enabled=True, legend_position=[800., 680.])
    moves = []
    legend = ElevationLegend((1600, 2000, 3), project, moved=moves.append)
    canvas.scene().addItem(legend)
    canvas.scale(request.param, request.param)
    canvas.show()
    canvas.centerOn(1040, 730)
    application.processEvents()
    yield canvas, legend, project, moves
    canvas.close()


def test_ordinary_drag_and_wheel_over_legend_only_navigate(legend_view):
    from PySide6.QtGui import QWheelEvent
    canvas, legend, project, moves = legend_view
    start = point(canvas, legend)
    original = legend.pos()
    scroll = canvas.horizontalScrollBar().value()
    mouse(canvas, QEvent.Type.MouseButtonPress, start)
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(40, 20))
    mouse(canvas, QEvent.Type.MouseButtonRelease, start+QPoint(40, 20))
    assert canvas.horizontalScrollBar().value() != scroll
    assert legend.pos() == original and project.legend_position == [800., 680.] and not moves
    start = point(canvas, legend)
    scale = canvas.transform().m11()
    wheel = QWheelEvent(QPointF(start), QPointF(canvas.viewport().mapToGlobal(start)),
                        QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                        NONE, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(canvas.viewport(), wheel)
    assert canvas.transform().m11() > scale
    assert legend.pos() == original and not moves


def test_modifier_drag_moves_legend_and_stops_on_key_release_or_focus_loss(legend_view):
    canvas, legend, project, moves = legend_view
    start = point(canvas, legend)
    original = legend.pos()
    scroll = canvas.horizontalScrollBar().value()
    mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(40, 20), CTRL)
    assert legend.pos() == original+QPointF(40, 20)/canvas.transform().m11()
    assert project.legend_position == [legend.pos().x(), legend.pos().y()] == moves[-1]
    assert canvas.horizontalScrollBar().value() == scroll
    stopped = legend.pos()
    QTest.keyRelease(canvas, Qt.Key.Key_Control)
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(80, 40), CTRL)
    assert legend.pos() == stopped
    mouse(canvas, QEvent.Type.MouseButtonRelease, start+QPoint(80, 40))
    start = point(canvas, legend)
    mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
    QApplication.sendEvent(canvas, QFocusEvent(QEvent.Type.FocusOut))
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(40, 20), CTRL)
    assert legend.pos() == stopped
    mouse(canvas, QEvent.Type.MouseButtonRelease, start)


def test_reference_pick_on_legend_takes_precedence(legend_view):
    canvas, legend, project, moves = legend_view
    picked = []
    canvas.point_clicked.connect(lambda x, y: picked.append((x, y)))
    canvas.picking = True
    QTest.mouseClick(canvas.viewport(), LEFT, CTRL, point(canvas, legend))
    assert len(picked) == 1 and not moves
    assert project.legend_position == [800., 680.]


def test_legend_stays_inside_photo_when_dragged_past_edges(legend_view):
    canvas, legend, project, moves = legend_view
    start = point(canvas, legend)
    mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
    mouse(canvas, QEvent.Type.MouseMove, start-QPoint(10000, 10000), CTRL)
    assert legend.pos() == QPointF(0, 0)
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(10000, 10000), CTRL)
    assert legend.sceneBoundingRect().right() == 2000
    assert legend.sceneBoundingRect().bottom() == 1600
    mouse(canvas, QEvent.Type.MouseButtonRelease, start, CTRL)
    assert project.legend_position == moves[-1]


@pytest.mark.parametrize('modifier', [NONE, Qt.KeyboardModifier.MetaModifier, Qt.KeyboardModifier.ShiftModifier])
def test_ordinary_drag_over_label_pans_without_moving_label(view, modifier):
    canvas, label, moves, _ = view
    start = point(canvas, label); original = label.pos()
    scroll = canvas.horizontalScrollBar().value()
    mouse(canvas, QEvent.Type.MouseButtonPress, start, modifier)
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(50, 20), modifier)
    mouse(canvas, QEvent.Type.MouseButtonRelease, start, modifier)
    assert label.pos() == original and not moves
    assert canvas.horizontalScrollBar().value() != scroll


def test_modifier_drag_moves_only_label_and_releasing_modifier_stops(view):
    from PySide6.QtCore import QPoint
    canvas, label, moves, _ = view
    start = point(canvas, label); original = label.pos()
    scroll = canvas.horizontalScrollBar().value()
    mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(40, 20), CTRL)
    assert label.pos() == original+QPointF(40, 20)/canvas.transform().m11() and moves
    stopped = label.pos()
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(80, 40), NONE)
    assert label.pos() == stopped
    mouse(canvas, QEvent.Type.MouseMove, start+QPoint(100, 50), CTRL)
    assert label.pos() == stopped
    mouse(canvas, QEvent.Type.MouseButtonRelease, start+QPoint(80, 40), NONE)
    assert canvas.horizontalScrollBar().value() == scroll


def test_double_click_still_edits_without_modifier(view):
    canvas, label, _, edits = view
    QTest.mouseDClick(canvas.viewport(), LEFT, pos=point(canvas, label))
    assert edits == [label.feature]


def test_reference_pick_on_label_takes_precedence(view):
    canvas, label, moves, _ = view
    picked = [];canvas.point_clicked.connect(lambda x,y:picked.append((x,y)))
    canvas.picking = True
    QTest.mouseClick(canvas.viewport(), LEFT, CTRL, point(canvas, label))
    assert len(picked) == 1 and not moves


def test_wheel_over_label_zooms_without_moving_it(view):
    from PySide6.QtGui import QWheelEvent
    canvas, label, moves, _ = view
    pos = point(canvas, label); original = label.pos()
    scale = canvas.transform().m11()
    event = QWheelEvent(QPointF(pos), QPointF(canvas.viewport().mapToGlobal(pos)),
                        QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                        NONE, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(canvas.viewport(), event)
    assert canvas.transform().m11() > scale
    assert label.pos() == original and not moves


@pytest.mark.parametrize('style', ART_STYLES[1:])
def test_art_drag_keeps_leader_visibility_when_the_position_is_saved(style):
    from moonlabeler.app import MainWindow
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win.resize(1200, 700)
        win.project = Project(art_style=style)
        canvas = win.canvas
        canvas.setSceneRect(0, 0, 2000, 1600)
        win.rebuilding = True
        label = Annotation({'id': 'test', 'name': 'Tycho'}, (850, 700), 'Tycho', win.project,
                           win.move_label, win.edit_label)
        canvas.scene().addItem(label)
        canvas.scene().addItem(label.line)
        label.setPos(950, 780)
        win.annotation_items = [label]
        win.rebuilding = False
        win.show()
        canvas.centerOn(1000, 800)
        app.processEvents()
        visible = label.line.isVisible()
        original = label.pos()
        start = point(canvas, label)
        mouse(canvas, QEvent.Type.MouseButtonPress, start)
        mouse(canvas, QEvent.Type.MouseMove, start+QPoint(40, 20))
        mouse(canvas, QEvent.Type.MouseButtonRelease, start+QPoint(40, 20))
        assert label.pos() == original and not win.project.labels
        assert label.line.isVisible() == visible
        start = point(canvas, label)
        mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
        assert label.line.isVisible(), 'Dragging should temporarily identify the formation'
        mouse(canvas, QEvent.Type.MouseMove, start+QPoint(40, 20), CTRL)
        assert label.line.isVisible()
        label.set_export_mode(True)
        assert label.line.isVisible() == visible, 'The locator must not leak into an export mid-drag'
        label.set_export_mode(False)
        assert label.line.isVisible()
        mouse(canvas, QEvent.Type.MouseButtonRelease, start+QPoint(40, 20), CTRL)
        assert label.pos() == original+QPointF(40, 20)
        assert win.project.labels['test']['position'] == [label.pos().x(), label.pos().y()]
        assert label.line.isVisible() == visible
        start = point(canvas, label)
        mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
        mouse(canvas, QEvent.Type.MouseMove, start+QPoint(10, 0), NONE)
        assert label.line.isVisible() == visible, 'Releasing Cmd while moving ends the locator'
        mouse(canvas, QEvent.Type.MouseButtonRelease, start+QPoint(10, 0), NONE)
        mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
        assert label.line.isVisible()
        QTest.keyRelease(canvas, Qt.Key.Key_Control)
        assert label.line.isVisible() == visible, 'Releasing Cmd without moving also ends the locator'
        mouse(canvas, QEvent.Type.MouseButtonRelease, start, NONE)
        mouse(canvas, QEvent.Type.MouseButtonPress, start, CTRL)
        assert label.line.isVisible()
        app.sendEvent(canvas, QFocusEvent(QEvent.Type.FocusOut))
        assert label.line.isVisible() == visible
        mouse(canvas, QEvent.Type.MouseButtonRelease, start, NONE)
    finally:
        win.dirty = False
        win.close()
