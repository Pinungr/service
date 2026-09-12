import json
from datetime import datetime
from zoneinfo import ZoneInfo
from PyQt6.QtCore import Qt, QObject, QRunnable, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QFormLayout, QDialogButtonBox, QLineEdit, QTextEdit, QComboBox, QCheckBox, QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea, QMessageBox)
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QColor
from .domain import rupees

STYLE = """
QWidget {font-family:'Segoe UI';font-size:13px;color:#213b39;background:#f5f7f6;}
QMainWindow {background:#f5f7f6;}
QWidget#sidebar {background:#133e37;}
QWidget#sidebar QLabel {background:transparent;color:#c4ded7;}
QWidget#sidebar QPushButton {background:transparent;color:#dcebe7;text-align:left;padding:12px 18px;border:0;border-radius:7px;}
QWidget#sidebar QPushButton:hover {background:#20564b;}
QWidget#sidebar QPushButton[active='true'] {background:#daf0b8;color:#193c32;font-weight:600;}
QLabel#brand {font-size:23px;font-weight:700;color:white;}
QLabel#title {font-size:29px;font-weight:650;color:#133e37;}
QLabel#subtitle {color:#6c7e7a;font-size:13px;}
QLabel#metric {font-size:28px;font-weight:650;color:#194f43;}
QWidget#card {background:white;border:1px solid #dde5e2;border-radius:9px;}
QWidget#card QLabel {background:transparent;}
QPushButton {background:white;border:1px solid #cddbd5;border-radius:6px;padding:8px 13px;font-weight:500;}
QPushButton:hover {background:#e8f1ed;border-color:#91b6a8;}
QPushButton#primary {background:#246a56;color:white;border-color:#246a56;}
QPushButton#primary:hover {background:#1b5544;}
QPushButton:disabled {color:#9aa8a2;background:#ecf0ed;}
QLineEdit,QTextEdit,QComboBox,QDateEdit {background:white;border:1px solid #cedbd5;border-radius:5px;padding:8px;selection-background-color:#c0dccf;}
QLineEdit:focus,QTextEdit:focus,QComboBox:focus {border:1px solid #2a8065;}
QTableWidget {background:white;alternate-background-color:#f5f8f6;border:1px solid #dde5e2;border-radius:7px;gridline-color:#edf1ef;selection-background-color:#dfeee6;selection-color:#173f32;}
QHeaderView::section {background:#edf3f0;color:#526d61;border:0;border-bottom:1px solid #dce5df;padding:11px 9px;font-size:12px;font-weight:600;}
QTableWidget::item {padding:7px;}
QTabWidget::pane {border:1px solid #dce5df;border-radius:6px;}
QTabBar::tab {background:#e8eeea;padding:10px 13px;border:0;}
QTabBar::tab:selected {background:#d9ebdf;color:#174e35;}
QScrollArea {border:0;}
QCheckBox {spacing:8px;padding:3px;}
QStatusBar {background:#e9f0ec;color:#536f60;}
"""


def button(text, callback, primary=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    b.clicked.connect(callback)
    return b


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

    def add(self):
        d = Form("Add " + self.kind, self)
        d.text("name", "Name")
        d.text("contact", "Phone / contact")
        d.text("details", "Notes", multiline=True)
        def save(v):
            self.reload(self.s.save_master(self.kind, v["name"], v["contact"], v["details"], category_id=self.category))
        d.submit(save)


class Form(QDialog):
    def __init__(self, title, parent=None, description=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(610, 600)
        self.fields = {}
        outer = QVBoxLayout(self)
        header = QLabel(title)
        header.setObjectName("title")
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
        self.layout.setSpacing(12)
        self.layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#b04132")
        outer.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

    def add(self, key, label, widget):
        self.fields[key] = widget
        self.layout.addRow(label, widget)
        return widget

    def text(self, key, label, value="", multiline=False, password=False):
        w = QTextEdit() if multiline else QLineEdit()
        if multiline:
            w.setPlainText(str(value or ""))
            w.setMaximumHeight(100)
        else:
            w.setText(str(value or ""))
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
            try:
                callback(self.values())
                self.accept()
            except Exception as exc:
                self.error.setText(str(exc))
        self.buttons.accepted.connect(save)
        return self.exec()


class CustomerSelector(QWidget):
    def __init__(self, service, selected=None, create=None):
        super().__init__()
        self.s = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find existing customer by name or phone…")
        self.box = QComboBox()
        layout.addWidget(self.search)
        layout.addWidget(self.box)
        self.create = create
        if create:
            self.create_button = button('+ New customer', self.new_customer)
            self.create_button.setEnabled(not service.db.readonly and service.user['role'] in ('owner','counter'))
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
        self.setWordWrap(False)

    def fill(self, rows, columns=None):
        self.rows = rows
        keys = columns or (list(rows[0]) if rows else ["No matching records"])
        self.setColumnCount(len(keys))
        self.setHorizontalHeaderLabels([k.replace("_", " ").title() for k in keys])
        self.setRowCount(len(rows))
        money_keys = {"purchase_cost", "customer_price", "margin","balance", "amount", "cost", "costs", "revenue", "margin_before_overheads", "total", "estimate", "running_balance", "unapplied", "allocated", "total_expense"}
        for r, row in enumerate(rows):
            for col, key in enumerate(keys):
                value = row.get(key, "")
                if key in money_keys and isinstance(value, int):
                    text = rupees(value)
                elif isinstance(value, str) and "T" in value and len(value)>19 and value[4:5] == "-":
                    try:
                        text = datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y %H:%M")
                    except ValueError:
                        text = value
                else:
                    text = str(value if value is not None else "—")
                if key in ("stage", "state", "route"):
                    text = text.replace("_", " ").title()
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if key == 'stage':
                    palette = {'diagnosis':'#8a6725','awaiting_estimate':'#8a6725','awaiting_approval':'#8a6725','under_repair':'#326d9d','ready_dispatch':'#a36326','awaiting_return':'#785d98','ready_repaired':'#28704e','ready_unrepaired':'#965347','waiting_parts':'#947134'}
                    item.setForeground(QColor(palette.get(value,'#355c4c')))
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
