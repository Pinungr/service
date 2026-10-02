"""Render control diagnostics only for the explicit --smoke-test developer mode."""
from pathlib import Path
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QWidget, QFormLayout, QComboBox, QDateEdit, QSpinBox


def capture_controls(destination):
    for name in ('chevron-down.svg', 'chevron-up.svg'):
        if QPixmap(str(Path(__file__).parent / 'assets' / name)).isNull():
            raise RuntimeError('Bundled control icon could not be loaded: ' + name)
    window = QWidget()
    layout = QFormLayout(window)
    for title in ('Product category', 'Repair / service (editable)', 'Disabled selection'):
        choice = QComboBox()
        choice.addItems(['Select…', 'Laptop', 'Desktop'])
        choice.setEditable('editable' in title)
        choice.setEnabled('Disabled' not in title)
        layout.addRow(title, choice)
    calendar = QDateEdit(QDate(2026, 9, 13))
    calendar.setCalendarPopup(True)
    layout.addRow('Collection date', calendar)
    layout.addRow('Accessory quantity', QSpinBox())
    window.resize(620, 300)
    window.show()
    QApplication.processEvents()
    if not window.grab().save(str(destination)):
        raise RuntimeError('Could not save control diagnostic image')
    window.close()
    window.deleteLater()
