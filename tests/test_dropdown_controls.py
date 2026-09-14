"""REG-DROPDOWN: visible arrow glyphs and working hit targets with production QSS."""
import pytest
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (QApplication, QCalendarWidget, QComboBox, QDateEdit,
    QSpinBox, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox)
from repairshop.ui_widgets import STYLE


@pytest.fixture
def styled_controls(qapp):
    previous = qapp.styleSheet()
    qapp.setStyle('Fusion')
    qapp.setStyleSheet(STYLE)
    yield
    qapp.setStyleSheet(previous)


@pytest.mark.parametrize('kind', ['choice', 'editable', 'disabled', 'calendar', 'quantity'])
def test_arrow_is_painted_and_control_operates(qtbot, styled_controls, kind):
    if kind == 'calendar':
        control = QDateEdit(QDate(2026, 9, 13))
        control.setCalendarPopup(True)
    elif kind == 'quantity':
        control = QSpinBox()
        control.setValue(5)
    else:
        control = QComboBox()
        control.addItems(['Select a category', 'Laptop', 'Desktop'])
        control.setEditable(kind == 'editable')
        control.setEnabled(kind != 'disabled')
    qtbot.addWidget(control)
    control.resize(320, 42)
    control.show()
    qtbot.wait(40)
    if isinstance(control, QComboBox) or kind == 'calendar':
        option = QStyleOptionComboBox()
        if isinstance(control, QComboBox):
            control.initStyleOption(option)
        else:
            # Calendar-popup dates paint a combo dropdown, not spin up/down buttons.
            option.initFrom(control)
        arrow = control.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxArrow, control)
    else:
        option = QStyleOptionSpinBox()
        control.initStyleOption(option)
        arrow = control.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, control)
    assert arrow.width() >= 24
    # Inspect the interior of the arrow's hit target, excluding text and borders.
    rendered = control.grab().toImage()
    ratio = rendered.devicePixelRatio()
    centre = arrow.center()
    dark = 0
    for x in range(centre.x() - 6, centre.x() + 7):
        for y in range(centre.y() - 5, centre.y() + 6):
            color = rendered.pixelColor(round(x * ratio), round(y * ratio))
            dark += color.red() < 145 and color.green() < 145 and color.blue() < 155
    assert dark >= 4, f'{kind}: arrow glyph not rendered'
    if kind == 'disabled':
        assert not control.isEnabled()
    elif isinstance(control, QComboBox):
        qtbot.mouseClick(control, Qt.MouseButton.LeftButton, pos=centre)
        qtbot.waitUntil(lambda: control.view().isVisible())
        qtbot.keyClick(control.view(), Qt.Key.Key_Down)
        qtbot.keyClick(control.view(), Qt.Key.Key_Return)
        assert control.currentIndex() == 1
    elif kind == 'calendar':
        qtbot.mouseClick(control, Qt.MouseButton.LeftButton, pos=centre)
        qtbot.waitUntil(lambda: control.calendarWidget().isVisible())
        control.calendarWidget().window().hide()
    else:
        qtbot.mouseClick(control, Qt.MouseButton.LeftButton, pos=centre)
        assert control.value() == 6
