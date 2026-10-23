# SPDX-License-Identifier: GPL-3.0-or-later
"""Real viewport gestures must not rearrange labels during navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from moonlabeler.app import Canvas, Annotation
from moonlabeler.project import Project

CTRL = Qt.KeyboardModifier.ControlModifier  # Qt maps this to Command on macOS.
NONE = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton

@pytest.fixture(params=[(1., "standard"), (2., "standard"), (1., "manuscript"), (2., "manuscript")])
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
