"""Exercise real styled geometry, including the collapsed dashboard regression."""
import pytest
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton
from repairshop.ui import MainWindow
from repairshop.ui_widgets import STYLE, MetricCard, Grid, FlowLayout


@pytest.mark.parametrize('size', [(1920, 1000), (1366, 700), (1024, 650), (900, 600)])
def test_dashboard_cards_survive_production_styles_and_resize(qtbot, service, size):
    app = QApplication.instance()
    old_style = app.styleSheet()
    app.setStyleSheet(STYLE)
    window = MainWindow(service)
    qtbot.addWidget(window)
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.resize(*size)
    window.show()
    try:
        qtbot.wait(100)
        cards = window.findChildren(MetricCard)
        assert len(cards) == 8
        for card in cards:
            assert card.height() >= 112
            for label in (card.caption, card.value):
                assert label.height() >= label.fontMetrics().height()
                assert card.rect().contains(label.geometry())
        # Windows clamps oversized windows to the available logical screen at high DPI.
        assert 900 <= window.width() <= size[0]
        called = []
        window.lifecycle_list = lambda key: called.append(key)
        cards[0].setFocus()
        qtbot.keyClick(cards[0], Qt.Key.Key_Space)
        assert called == ['received']
    finally:
        qtbot.waitUntil(lambda: not window.tasks, timeout=10000)
        window.close()
        app.setStyleSheet(old_style)


def test_empty_grid_never_selects_placeholder(qtbot):
    grid = Grid()
    qtbot.addWidget(grid)
    grid.show()
    grid.fill([], ['name'])
    assert grid.empty.isVisible()
    assert grid.selected() is None and grid.rowCount() == 0
    grid.fill([{'name': 'Saved customer'}], ['name'])
    assert not grid.empty.isVisible()
    assert grid.selected()['name'] == 'Saved customer'


def test_action_toolbar_wraps_and_keeps_buttons_clickable(qtbot):
    box = QWidget()
    qtbot.addWidget(box)
    flow = FlowLayout(box)
    buttons = [QPushButton('Action number ' + str(i)) for i in range(8)]
    for button in buttons:
        flow.addWidget(button)
    box.resize(320, 400)
    box.show()
    qtbot.wait(20)
    assert buttons[-1].y() > buttons[0].y()
    assert all(box.rect().contains(button.geometry()) for button in buttons)
