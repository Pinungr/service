import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from PyQt6.QtCore import Qt, QObject, QRunnable, pyqtSignal, QSize, QRect, QPoint
from PyQt6.QtWidgets import QLayout, QSizePolicy, QGridLayout, QApplication
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QFormLayout, QDialogButtonBox, QLineEdit, QTextEdit, QComboBox, QCheckBox, QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea, QMessageBox)
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QColor
from .domain import rupees, zone as shop_zone


class Cancelled(Exception):
    """Raised by a Form submit callback to abort the save without reporting an error."""


STYLE = """
QWidget {
    font-family: 'Segoe UI', 'Noto Sans', Arial;
    font-size: 14px;
    color: #1f2937;
    background: #f6f8fb;
}
QMainWindow, QDialog {background: #f6f8fb;}
QWidget#sidebar {background: #102a43;}
QWidget#navContent {background: #102a43;}
QWidget#sidebar QLabel {background: transparent;color: #cbd5e1;}
QWidget#sidebar QPushButton {
    background: transparent;
    color: #e2e8f0;
    text-align: left;
    padding: 8px 12px;
    min-height: 20px;
    border: 0;
    border-radius: 8px;
    font-weight: 600;
}
QWidget#sidebar QPushButton:hover {background: #1d3f5f;color: white;}
QWidget#sidebar QPushButton[active='true'] {
    background: #dbeafe;
    color: #0f3057;
    font-weight: 700;
}
QWidget#sidebar QLabel#brand {font-size: 24px;font-weight: 700;color: white;}
QWidget#sidebar QLabel#navGroup {font-size: 11px;font-weight: 700;color: #9fb6cd;padding-top: 12px;}
QLabel#eyebrow {
    color: #93a4b8;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
}
QLabel#title {font-size: 30px;font-weight: 750;color: #102a43;}
QLabel#subtitle {color: #52647b;font-size: 14px;}
QLabel#sectionTitle {font-size: 15px;font-weight: 750;color: #102a43;}
QLabel#metric {font-size: 30px;font-weight: 800;color: #0f766e;}
QLabel#muted {color: #52647b;}
QLabel {background: transparent;}
QLabel#badge {
    background: #e0f2fe;
    color: #075985;
    border: 1px solid #bae6fd;
    border-radius: 8px;
    padding: 7px 12px;
    font-weight: 700;
}
QLabel#successBadge {background:#dcfce7;color:#166534;border:1px solid #bbf7d0;border-radius:8px;padding:5px 10px;font-weight:700;}
QLabel#warningBadge {background:#fef3c7;color:#92400e;border:1px solid #fde68a;border-radius:8px;padding:5px 10px;font-weight:700;}
QLabel#errorBadge {background:#fee2e2;color:#991b1b;border:1px solid #fecaca;border-radius:8px;padding:5px 10px;font-weight:700;}
QWidget#card, QWidget#panel {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}
QWidget#card QLabel, QWidget#panel QLabel {background: transparent;}
QPushButton {
    background: white;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 13px;
    min-height: 22px;
    font-weight: 650;
    color: #1e293b;
}
QPushButton:hover {background: #f1f5f9;border-color: #94a3b8;}
QPushButton:pressed {background: #e2e8f0;}
QPushButton#primary {
    background: #0f766e;
    color: white;
    border-color: #0f766e;
}
QPushButton#primary:hover {background: #115e59;border-color: #115e59;}
QPushButton#danger {
    background: #fee2e2;
    color: #991b1b;
    border-color: #fecaca;
}
QPushButton#danger:hover {background: #fecaca;}
QPushButton#metricCard {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 0;
    text-align: left;
    min-height: 112px;
}
QPushButton#metricCard:hover {background: #f8fafc;border-color: #99f6e4;}
QPushButton:focus {border: 2px solid #0f766e;}
QWidget#sidebar QPushButton:focus {border: 2px solid #7dd3fc;}
QPushButton#metricCard QLabel {background: transparent;}
QPushButton#metricCard[tone='warning'] QLabel#metric {color: #92400e;}
QPushButton#metricCard[tone='info'] QLabel#metric {color: #075985;}
QPushButton#metricCard[tone='error'] QLabel#metric {color: #b91c1c;}
QLabel#emptyState {color: #52647b;background: white;padding: 24px;}
QProgressBar {border:0;background:#e2e8f0;max-height:4px;}
QProgressBar::chunk {background:#0f766e;}
QScrollBar:vertical {background:transparent;width:12px;margin:0;}
QScrollBar::handle:vertical {background:#b8c6d5;min-height:32px;border-radius:5px;}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {background:transparent;}
QPushButton:disabled {color: #94a3b8;background: #f1f5f9;border-color: #e2e8f0;}
QLineEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox {
    background: white;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #bae6fd;
}
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover {border-color: #94a3b8;}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {
    border: 1px solid #0f766e;
}
QComboBox, QDateEdit {padding-right: 38px;min-height: 22px;}
QComboBox::drop-down, QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 32px;
    border-left: 1px solid #cbd5e1;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    background: #edf2f7;
}
QComboBox::drop-down:hover, QDateEdit::drop-down:hover {background: #dbeafe;}
QComboBox::down-arrow, QDateEdit::down-arrow {
    image: url("__ARROW_DOWN__");
    width: 16px;
    height: 16px;
}
QComboBox:disabled, QDateEdit:disabled {color: #94a3b8;background: #f1f5f9;}
QComboBox::drop-down:disabled, QDateEdit::drop-down:disabled {background: #f1f5f9;}
QComboBox QLineEdit {border: 0;padding: 0;background: transparent;}
QComboBox QAbstractItemView {background: white;selection-background-color: #ccfbf1;selection-color: #134e4a;outline: 0;}
QSpinBox {padding-right: 32px;min-height: 22px;}
QSpinBox::up-button, QSpinBox::down-button {subcontrol-origin: border;width: 28px;background: #edf2f7;border-left: 1px solid #cbd5e1;}
QSpinBox::up-button {subcontrol-position: top right;border-top-right-radius: 7px;}
QSpinBox::down-button {subcontrol-position: bottom right;border-bottom-right-radius: 7px;}
QSpinBox::up-arrow {image: url("__ARROW_UP__");width: 12px;height: 12px;}
QSpinBox::down-arrow {image: url("__ARROW_DOWN__");width: 12px;height: 12px;}
QTableWidget {
    background: white;
    alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    gridline-color: #eef2f7;
    selection-background-color: #ccfbf1;
    selection-color: #134e4a;
}
QHeaderView::section {
    background: #f1f5f9;
    color: #475569;
    border: 0;
    border-bottom: 1px solid #e2e8f0;
    padding: 10px 9px;
    font-size: 12px;
    font-weight: 800;
}
QTableWidget::item {padding: 8px;border-bottom: 1px solid #f1f5f9;}
QTableWidget::item:hover {background: #f0fdfa;}
QTabWidget::pane {border: 1px solid #e2e8f0;border-radius: 10px;background:white;}
QTabBar::tab {
    background: #e2e8f0;
    color: #334155;
    padding: 10px 14px;
    border: 0;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
    font-weight: 650;
}
QTabBar::tab:selected {background: white;color: #0f766e;}
QScrollArea {border: 0;background: transparent;}
__CHECKBOX__
QDialogButtonBox QPushButton {min-width: 92px;}
QStatusBar {background: #e2e8f0;color: #475569;}
"""
# Single source of lifecycle status semantics for every screen that draws one.
# Each entry is (icon, wording, ink, surface, border). Icons and wording carry
# the meaning on their own so nothing depends on colour alone.
STATUS_STATES = {
    'completed': ('\u2713', 'Completed', '#166534', '#edf9f0', '#b7dec2'),
    'current': ('\u25cf', 'Current', '#0f766e', '#eaf7f5', '#0f766e'),
    'upcoming': ('\u25cb', 'Upcoming', '#64748b', '#f8fafc', '#dde5ee'),
    'waiting': ('!', 'Waiting / blocked', '#92400e', '#fff7e6', '#e9bd69'),
    'failed': ('\u00d7', 'Failed', '#b42318', '#fff1f0', '#efb4ad'),
    'cancelled': ('\u00d7', 'Cancelled', '#b42318', '#fff1f0', '#efb4ad'),
    'skipped': ('\u2014', 'Skipped / N/A', '#64748b', '#f1f5f9', '#d7dfe8'),
}


# Qt stops painting a native indicator as soon as QCheckBox::indicator is styled,
# so every state has to be drawn explicitly or the box renders blank.
CHECKBOX_STYLE = """
QCheckBox {spacing: 8px;padding: 4px;background: transparent;}
QCheckBox::indicator {width: 18px;height: 18px;border: 1px solid #8193a5;border-radius: 4px;background: white;}
QCheckBox::indicator:hover {border-color: #0f766e;}
QCheckBox::indicator:checked {border-color: #0f766e;background: #0f766e;image: url("__CHECK__");}
QCheckBox::indicator:disabled {border-color: #cbd5e1;background: #edf2f7;}
QCheckBox::indicator:checked:disabled {border-color: #94a3b8;background: #94a3b8;image: url("__CHECK__");}
""".replace('__CHECK__', (Path(__file__).parent / 'assets' / 'checkmark.svg').as_posix())

STYLE = STYLE.replace('__ARROW_DOWN__', (Path(__file__).parent / 'assets' / 'chevron-down.svg').as_posix()).replace('__ARROW_UP__', (Path(__file__).parent / 'assets' / 'chevron-up.svg').as_posix()).replace('__CHECKBOX__', CHECKBOX_STYLE)


class FlowLayout(QLayout):
    """Action rows wrap without hiding buttons on smaller displays."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, True)

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def _arrange(self, rect, apply):
        x, y, height = rect.x(), rect.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            if x > rect.x() and x + size.width() > rect.right() + 1:
                x, y, height = rect.x(), y + height + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        return y + height - rect.y()


class MetricCard(QPushButton):
    """A keyboard-operable card whose size accounts for its child labels."""
    def __init__(self, title, value, callback, tone="info"):
        super().__init__()
        self.setObjectName("metricCard")
        self.setProperty("tone", tone)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{title}: {value}. Open matching repairs")
        self.setToolTip(f"View {title.lower()} repairs")
        self.clicked.connect(callback)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        self.caption = QLabel(title)
        self.caption.setObjectName("muted")
        self.caption.setWordWrap(True)
        self.value = QLabel(str(value))
        self.value.setObjectName("metric")
        for label in (self.caption, self.value):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)

    def sizeHint(self):
        return self.layout().sizeHint().expandedTo(QSize(172, 114))

    def minimumSizeHint(self):
        return self.sizeHint()


class CardGrid(QWidget):
    def __init__(self, cards):
        super().__init__()
        self.cards = cards
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.reflow(4)

    def reflow(self, columns):
        if columns == self.columns:
            return
        old_columns = self.columns
        self.columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for col in range(max(columns, old_columns)):
            self.grid.setColumnStretch(col, 1 if col < columns else 0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow(max(1, min(4, (event.size().width() + 12) // 195)))

    def minimumSizeHint(self):
        return QSize(180, self.grid.minimumSize().height())


def button(text, callback, primary=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    if text.lower().startswith(("delete", "remove", "reverse", "restore")) or "write off" in text.lower():
        b.setObjectName("danger")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    # Qt reads "&" as a mnemonic and "&&" as a literal ampersand; strip the same
    # way so the tooltip matches the caption the user actually sees.
    plain = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    b.setToolTip(plain)
    b.setAccessibleName(plain)
    b.clicked.connect(callback)
    return b


def badge(text, tone="info"):
    label = QLabel(text)
    label.setObjectName({"success": "successBadge", "warning": "warningBadge", "error": "errorBadge"}.get(tone, "badge"))
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def panel(title=None, subtitle=None):
    box = QWidget()
    box.setObjectName("panel")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    if title:
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
    if subtitle:
        copy = QLabel(subtitle)
        copy.setObjectName("subtitle")
        copy.setWordWrap(True)
        layout.addWidget(copy)
    return box, layout


def combo(options, selected=None, editable=False):
    c = QComboBox()
    c.setEditable(editable)
    if editable:
        c.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        c.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        c.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    for option in options:
        label, value = option if isinstance(option, tuple) else (str(option).replace("_", " ").title(), option)
        c.addItem(label, value)
    if selected is not None:
        idx = c.findData(selected)
        if idx >= 0:
            c.setCurrentIndex(idx)
    return c


class MasterSelector(QWidget):
    def __init__(self, service, kind, category=None):
        super().__init__()
        self.s, self.kind, self.category = service, kind, category
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.box = combo([], editable=True)
        layout.addWidget(self.box, 1)
        add = button("+ Add new", self.add)
        self.add_button = add
        add.setEnabled(not service.db.readonly and service.user["role"] != "technician")
        layout.addWidget(add)
        self.reload()

    def reload(self, selected=None):
        self.box.clear()
        self.box.addItem('Choose a product category first…' if self.kind=='service' and not self.category else 'Select…', None)
        rows=self.s.services_for_category(self.category) if self.kind=='service' else self.s.masters(self.kind)
        for row in rows:
            self.box.addItem(row['name']+(' (all categories)' if self.kind=='service' and row['general'] else ''), row['id'])
        self.add_button.setEnabled(not self.s.db.readonly and self.s.user['role']!='technician' and (self.kind!='service' or bool(self.category)))
        if selected:
            self.box.setCurrentIndex(self.box.findData(selected))

    def set_category(self,category):
        selected=self.value()
        self.category=category
        self.reload(selected)
        if self.box.currentIndex()<0:self.box.setCurrentIndex(0)

    def value(self):
        return self.box.currentData() if self.box.findText(self.box.currentText()) >= 0 else None

    def text(self):
        return self.box.currentText() if self.value() else ""

    LABELS = {'vendor': 'Third Party', 'centre': 'Authorized Service Center', 'supplier': 'Parts Supplier',
              'technician': 'Internal Technician', 'service': 'Repair / Service', 'category': 'Product Category'}

    def add(self):
        # Shop-owner wording. A quick add stays quick; the full third-party postal address
        # and photo are completed from Directories.
        d = Form("Add " + self.LABELS.get(self.kind, self.kind.replace('_', ' ').title()), self)
        d.text("name", "Name")
        d.text("contact", "Mobile" if self.kind in ('vendor', 'centre', 'supplier') else "Phone / contact")
        d.text("details", "Notes", multiline=True)
        def save(v):
            self.reload(self.s.save_master(self.kind, v["name"], v["contact"], v["details"], category_id=self.category))
        d.submit(save)


class Form(QDialog):
    def __init__(self, title, parent=None, description=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(660, 640)
        self.fields = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)
        header = QLabel(title)
        header.setObjectName("title")
        header.setWordWrap(True)
        outer.addWidget(header)
        if description:
            label = QLabel(description)
            label.setWordWrap(True)
            label.setObjectName("subtitle")
            outer.addWidget(label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.layout = QFormLayout(body)
        self.layout.setContentsMargins(2, 2, 10, 2)
        self.layout.setHorizontalSpacing(18)
        self.layout.setVerticalSpacing(12)
        self.layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("errorBadge")
        self.error.hide()
        outer.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        outer.addWidget(self.buttons)

    def add(self, key, label, widget):
        self.fields[key] = widget
        self.layout.addRow(label, widget)
        widget.setAccessibleName(label)
        field_label = self.layout.labelForField(widget)
        if field_label:
            field_label.setBuddy(widget)
        return widget

    def section(self, title):
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        self.layout.addRow(heading)

    def showEvent(self, event):
        super().showEvent(event)
        available = self.screen().availableGeometry()
        self.resize(min(self.width(), available.width() - 40), min(self.height(), available.height() - 60))
        self.move(max(available.left(), min(self.x(), available.right() - self.width())),
                  max(available.top(), min(self.y(), available.bottom() - self.height() - 30)))

    def text(self, key, label, value="", multiline=False, password=False):
        w = QTextEdit() if multiline else QLineEdit()
        if multiline:
            w.setPlainText(str("" if value is None else value))
            w.setMaximumHeight(100)
        else:
            w.setText(str("" if value is None else value))
            if password:
                w.setEchoMode(QLineEdit.EchoMode.Password)
        return self.add(key, label, w)

    def check(self, key, label, value=False):
        w = QCheckBox()
        w.setChecked(bool(value))
        return self.add(key, label, w)

    def select(self, key, label, options, selected=None):
        return self.add(key, label, combo(options, selected, editable=True))

    def date(self, key, label, value=None):
        w = QDateEdit()
        w.setCalendarPopup(True)
        w.setDisplayFormat("dd MMM yyyy")
        w.setMinimumDate(QDate(1900, 1, 1))
        w.setSpecialValueText("Not set")
        w.setDate(QDate.fromString(value[:10], "yyyy-MM-dd") if value else QDate(1900, 1, 1))
        return self.add(key, label, w)

    def values(self):
        result = {}
        for k, w in self.fields.items():
            if isinstance(w, MasterSelector):
                result[k] = w.value()
            elif isinstance(w, CustomerSelector):
                result[k] = w.text()
            elif isinstance(w, QComboBox):
                result[k] = w.currentData()
            elif isinstance(w, QCheckBox):
                result[k] = w.isChecked()
            elif isinstance(w, QDateEdit):
                result[k] = None if w.date() == w.minimumDate() else w.date().toString("yyyy-MM-dd")
            elif isinstance(w, QTextEdit):
                result[k] = w.toPlainText().strip()
            else:
                result[k] = w.text().strip()
        return result

    def submit(self, callback):
        def save():
            save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
            if not save_button.isEnabled():
                return
            previous_text = save_button.text()
            save_button.setEnabled(False)
            save_button.setText("Saving…")
            self.error.hide()
            try:
                callback(self.values())
                self.accept()
            except Cancelled:
                pass
            except Exception as exc:
                self.error.setText("Unable to save. " + str(exc))
                self.error.show()
            finally:
                save_button.setText(previous_text)
                save_button.setEnabled(True)
        self.buttons.accepted.connect(save)
        return self.exec()


class CustomerSelector(QWidget):
    def __init__(self, service, selected=None, create=None):
        super().__init__()
        self.s = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find customer by name, phone or alternate number…")
        self.box = QComboBox()
        layout.addWidget(self.search)
        layout.addWidget(self.box)
        self.create = create
        if create:
            self.create_button = button('+ New customer', self.new_customer)
            self.create_button.setEnabled(not service.db.readonly and service.may('customer_records'))
            layout.addWidget(self.create_button)
            self.hint = QLabel()
            self.hint.setWordWrap(True)
            layout.addWidget(self.hint)
        self.search.textChanged.connect(self.reload)
        self.reload("")
        if selected:
            self.select(selected)

    def reload(self, text):
        from .queries import Queries
        self.box.clear()
        self.box.addItem("Select customer…", None)
        for row in Queries(self.s).customers(text):
            self.box.addItem(row["name"] + " · " + row["phone"], row["id"])
        if self.create:
            self.hint.setText('No matching customer. Use New customer to register them.' if self.box.count()==1 and text.strip() else 'Choose a saved customer from the list, or register a new customer.')

    def select(self, ident):
        row = self.s.db.one('SELECT id,name,phone FROM customers WHERE id=?',(ident,))
        if not row:
            return
        self.search.blockSignals(True)
        self.search.setText(row['name'])
        self.search.blockSignals(False)
        self.box.blockSignals(True)
        self.box.clear()
        self.box.addItem('Select customer…',None)
        self.box.addItem(row['name']+' · '+row['phone'],row['id'])
        self.box.setCurrentIndex(1)
        self.box.blockSignals(False)
        if self.create:self.hint.setText('Customer selected. Continue with their photo and device details.')
        self.box.currentIndexChanged.emit(1)

    def new_customer(self):
        ident = self.create(self.search.text().strip())
        if ident:
            self.select(ident)

    def text(self):
        return self.box.currentData()


class Grid(QTableWidget):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(43)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setMinimumSectionSize(96)
        self.setWordWrap(False)
        self.setMinimumHeight(180)
        self.empty = QLabel("No records yet\nAdd a record using the actions above, or adjust your search and filters.", self.viewport())
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.empty.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.empty.setGeometry(self.viewport().rect())

    def set_empty_text(self, text):
        self.empty.setText(text)

    def fill(self, rows, columns=None):
        self.rows = rows
        self.empty.setVisible(not rows)
        self.empty.setGeometry(self.viewport().rect())
        keys = columns or (list(rows[0]) if rows else ["No matching records"])
        self.setColumnCount(len(keys))
        self.setHorizontalHeaderLabels([k.replace("_", " ").title() for k in keys])
        if not rows:
            self.clearSpans()
            self.setRowCount(0)
            self.setToolTip("No records to show")
            self.resizeColumnsToContents()
            self.horizontalHeader().setStretchLastSection(True)
            return
        self.setToolTip("")
        self.clearSpans()
        self.setRowCount(len(rows))
        money_keys = {"purchase_cost", "customer_price", "margin","balance", "amount", "cost", "costs", "revenue", "margin_before_overheads", "total", "estimate", "running_balance", "unapplied", "allocated", "total_expense"}
        for r, row in enumerate(rows):
            for col, key in enumerate(keys):
                value = row.get(key, "")
                if key in money_keys and isinstance(value, int):
                    text = rupees(value)
                elif isinstance(value, str) and "T" in value and len(value)>19 and value[4:5] == "-":
                    try:
                        text = datetime.fromisoformat(value).astimezone(shop_zone()).strftime("%d %b %Y %H:%M")
                    except ValueError:
                        text = value
                else:
                    text = str(value if value is not None else "—")
                if key in ("stage", "state", "route"):
                    text = text.replace("_", " ").title()
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if key in ("stage", "state", "status", "procurement_status", "stock_state", "effective_status", "warranty_indicator"):
                    palette = {
                        "diagnosis": ("#92400e", "#fef3c7"), "awaiting_estimate": ("#92400e", "#fef3c7"),
                        "awaiting_approval": ("#92400e", "#fef3c7"), "waiting_parts": ("#92400e", "#fef3c7"),
                        "under_repair": ("#075985", "#e0f2fe"), "ready_dispatch": ("#9a3412", "#ffedd5"),
                        "awaiting_return": ("#6d28d9", "#ede9fe"), "ready_repaired": ("#166534", "#dcfce7"),
                        "ready_unrepaired": ("#991b1b", "#fee2e2"), "installed": ("#166534", "#dcfce7"),
                        "planned": ("#475569", "#f1f5f9"), "reserved": ("#92400e", "#fef3c7"),
                        "issued": ("#075985", "#e0f2fe"), "ACTIVE": ("#166534", "#dcfce7"),
                        "OPEN": ("#92400e", "#fef3c7"), "REJECTED": ("#991b1b", "#fee2e2"),
                    }
                    colors = palette.get(value, palette.get(text, None))
                    if colors:
                        item.setForeground(QColor(colors[0]))
                        item.setBackground(QColor(colors[1]))
                self.setItem(r, col, item)
        self.resizeColumnsToContents()
        for col in range(len(keys)):
            self.setColumnWidth(col, min(320, max(90, self.columnWidth(col))))
        if rows:
            self.selectRow(0)

    def selected(self):
        return self.rows[self.currentRow()] if 0 <= self.currentRow() < len(self.rows) else None


class Signals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class Task(QRunnable):
    def __init__(self, work):
        super().__init__()
        # Python callers retain the runnable until its queued result is handled.
        # Avoid competing Qt/Python destruction of its QObject signal bridge.
        self.setAutoDelete(False)
        self.work = work
        self.signals = Signals()

    def run(self):
        try:
            self.signals.finished.emit(self.work())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
