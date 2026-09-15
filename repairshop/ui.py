import json
from pathlib import Path
import uuid
from datetime import date, timedelta
from decimal import Decimal
from PyQt6.QtCore import Qt, QThreadPool, QTimer, QUrl, QDate
from PyQt6 import sip
from PyQt6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget, QDialog, QTabWidget, QMessageBox, QFileDialog, QLineEdit, QCheckBox, QScrollArea, QGridLayout, QPushButton, QSpinBox, QProgressBar)
from .ui_widgets import Form, Grid, MasterSelector, CustomerSelector, Task, button, combo, STYLE, badge, panel, MetricCard, CardGrid, FlowLayout
from .domain import RuleError, money, rupees, STAGES, ROUTES, MASTER_KINDS, today
from .queries import Queries
from .documents import Documents
from .backup import Backups
from .messaging import Outbox, secret

# Shop-owner wording. Internal table values stay as they are, so no data migration risk.
DIRECTORY_LABELS = {'vendor': 'Third Party', 'centre': 'Authorized Service Center', 'supplier': 'Parts Supplier',
                    'technician': 'Internal Technician', 'service': 'Repair / Service'}
from .customer_records import CustomerRecords
from .customer_ui import CustomerOverview, IntakeForm, IntakePhotos, DevicePhotos
from .local_files import managed_path
from .lifecycle import Lifecycle, LABELS
from .lifecycle_ui import JobWorkspace, COLUMNS


def amount_text(value):
    return str(Decimal(value or 0) / 100)


class MainWindow(QMainWindow):
    def __init__(self, service, demo=False):
        super().__init__()
        self.s, self.db = service, service.db
        self.q = Queries(service)
        self.docs = Documents(service)
        self.demo = demo
        self.setWindowTitle("RepairShop Manager" + (" · DEMONSTRATION DATA" if demo else "") + (" · READ-ONLY ARCHIVE" if self.db.readonly else ""))
        self.resize(1400, 880)
        self.setMinimumSize(900, 600)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.tasks = set()
        self.closing = False
        self.close_when_idle = False
        self.worker_busy = False
        self.folder_busy = False
        self.page_name = "Dashboard"
        self.pages = {}
        self.nav = {}
        main = QWidget()
        root = QHBoxLayout(main)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(main)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 20, 12, 16)
        nav.setSpacing(7)
        brand = QLabel("RepairShop")
        brand.setObjectName("brand")
        nav.addWidget(brand)
        nav_label = QLabel("SERVICE & REPAIR MANAGER")
        nav_label.setObjectName("eyebrow")
        nav.addWidget(nav_label)
        nav.addSpacing(8)
        navigation = QWidget()
        navigation.setObjectName('navContent')
        links = QVBoxLayout(navigation)
        links.setContentsMargins(0, 0, 4, 0)
        links.setSpacing(4)
        names = ["Dashboard", "New Repair Intake", "Active Repairs", "Ready for Delivery", "Repair History", "Inventory", "Customers", "Products sold", "Dispatch & receive", "Directories", "Quotations", "Customer accounts", "Vendor accounts", "Reports", "Notifications", "Backups", "Settings & staff"]
        for name in names:
            groups = {'Dashboard': 'WORKSHOP', 'Customers': 'PEOPLE & SALES', 'Quotations': 'ACCOUNTS', 'Notifications': 'MANAGEMENT'}
            if name in groups:
                group = QLabel(groups[name]); group.setObjectName('navGroup'); links.addWidget(group)
            b = button(name.replace('&', '&&'), lambda checked=False, n=name: self.navigate(n))
            self.nav[name] = b
            links.addWidget(b)
            if not self.may_open(name):
                b.hide()
        links.addStretch()
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setWidget(navigation)
        nav.addWidget(sidebar_scroll, 1)
        offline = badge("Offline ready", "success")
        nav.addWidget(offline)
        user = QLabel(service.user["name"] + " · " + service.user["role"].title())
        user.setObjectName("subtitle")
        user.setWordWrap(True)
        nav.addWidget(user)
        root.addWidget(sidebar)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(30, 24, 30, 20)
        body.setSpacing(14)
        top = QHBoxLayout()
        top.setSpacing(16)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setWordWrap(True)
        heading.addWidget(self.title)
        heading.addWidget(self.subtitle)
        top.addLayout(heading, 1)
        state_badge = badge("READ-ONLY ARCHIVE" if self.db.readonly else "SYNTHETIC DEMO" if demo else self.db.setting("shop_name", "Your shop"), "warning" if self.db.readonly else "info")
        top.addWidget(state_badge, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(top)
        self.stack = QStackedWidget()
        body.addWidget(self.stack)
        root.addWidget(content, 1)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedWidth(110)
        self.busy.setAccessibleName('Background work in progress')
        self.statusBar().addPermanentWidget(self.busy)
        self.busy.hide()
        self.statusBar().showMessage("Ready · All amounts in INR · Event times shown in " + self.db.setting("timezone", "Asia/Kolkata"))
        # The shortcut follows the same rule as the button it mirrors.
        if self.may_open('New Repair Intake'):
            QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.safe(self.intake))
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        self.navigate("Dashboard")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.background)
        if not self.db.readonly:
            Outbox(self.s).recover_claims()
            self.timer.start(30000)
            self.startup_worker = QTimer(self)
            self.startup_worker.setSingleShot(True)
            self.startup_worker.timeout.connect(self.background)
            self.startup_worker.start(2000)
            self.startup_backup = QTimer(self)
            self.startup_backup.setSingleShot(True)
            self.startup_backup.timeout.connect(lambda: self.run(lambda: Backups(self.s).due(), "Checking scheduled backups…", refresh=False))
            self.startup_backup.start(4000)
            self.backup_timer = QTimer(self)
            self.backup_timer.timeout.connect(lambda: self.run(lambda: Backups(self.s).due(), 'Checking scheduled backups…', refresh=False))
            self.backup_timer.start(3600000)

    def closeEvent(self, event):
        if self.tasks:
            self.close_when_idle = True
            for timer in self.findChildren(QTimer):
                if not sip.isdeleted(timer):
                    timer.stop()
            self.statusBar().showMessage('Finishing background work before closing…')
            event.ignore()
        else:
            self.closing = True
            for timer in self.findChildren(QTimer):
                if not sip.isdeleted(timer):
                    timer.stop()
            event.accept()

    def run(self, work, message="Working…", callback=None, refresh=True, failure=None):
        if self.closing or sip.isdeleted(self):
            return
        task = Task(work)
        self.tasks.add(task)
        self.busy.show()
        self.statusBar().showMessage(message)
        def done(result):
            self.tasks.discard(task)
            if self.closing or sip.isdeleted(self):
                return
            if self.close_when_idle:
                if not self.tasks:self.close()
                return
            self.busy.setVisible(bool(self.tasks))
            self.statusBar().showMessage("Completed · " + message.rstrip('…'), 5000)
            if callback:
                self.safe(lambda: callback(result))
            if refresh:
                self.refresh()
        def failed(error):
            self.tasks.discard(task)
            if self.closing or sip.isdeleted(self):
                return
            if self.close_when_idle:
                if not self.tasks:self.close()
                return
            self.busy.setVisible(bool(self.tasks))
            self.statusBar().showMessage("Could not complete: " + error)
            if failure:
                # The caller still needs to continue: the business records are committed
                # even when an optional document or message step failed.
                self.safe(lambda: failure(error))
                return
            if self.isVisible():
                notice=QMessageBox(QMessageBox.Icon.Warning,'Action needs attention',error,parent=self)
                notice.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                notice.open()
        task.signals.finished.connect(done)
        task.signals.failed.connect(failed)
        self.pool.start(task)

    def background(self):
        if self.worker_busy or self.db.readonly:
            return
        self.worker_busy = True
        def work():
            try:
                out = Outbox(self.s)
                out.schedule_reminders()
                for _ in range(10):
                    if not out.process_one():
                        break
            finally:
                self.worker_busy = False
        self.run(work, "Checking notification queue…", refresh=self.page_name in ("Notifications", "Dashboard"))

    def safe(self, action):
        try:
            return action()
        except Exception as exc:
            QMessageBox.warning(self, "Please review", str(exc))

    # Screens a role may not use at all. Hiding a button is only tidiness: `navigate`
    # refuses the screen and every service call behind it enforces the rule again.
    #: The permission each screen needs. A screen with no entry is open to any signed-in
    #: user. This is the same table the services check, so a hidden button and a refused
    #: service call can never disagree.
    SCREENS = {
        'New Repair Intake': 'intake', 'Customers': 'customer_records',
        'Products sold': 'customer_records', 'Dispatch & receive': 'handover',
        'Inventory': 'inventory', 'Directories': 'directories',
        'Quotations': 'create_quote', 'Customer accounts': 'collect_payment',
        'Vendor accounts': 'vendor_accounts', 'Reports': 'reports',
        'Notifications': 'messaging', 'Backups': 'backup_restore',
        'Settings & staff': 'settings', 'Repair History': 'view_all_jobs',
        'Ready for Delivery': 'customer_delivery', 'Jobs': 'view_all_jobs',
    }

    def may_open(self, name):
        permission = self.SCREENS.get(name)
        return permission is None or self.s.may(permission)

    def navigate(self, name):
        if not self.may_open(name):
            raise RuleError('Your role cannot open ' + name + '.')
        self.page_name = name
        self.title.setText(name)
        descriptions = {"Dashboard": "Your shop at a glance · physical items and work progress", "Jobs": "Track each repair from intake to collection", "Dispatch & receive": "Choose the actual items handed over; accessories can stay at the shop", "Customer accounts": "Bills, receipts and refunds · balances remain after collection", "Vendor accounts": "Confirmed payables and monthly settlement", "Backups": "Verified recovery copies, long-term archives and historical viewing", "Notifications": "Preview and manage updates · provider acceptance is not delivery"}
        descriptions.update({'New Repair Intake': 'Receive a customer’s devices and create their repair jobs', 'Active Repairs': 'Find a repair and continue its next step', 'Ready for Delivery': 'Repairs ready for customer collection', 'Repair History': 'Look up previous visits and the complete repair record', 'Inventory': 'Track available, reserved and issued repair parts', 'Customers': 'Find customers, their devices and previous visits', 'Products sold': 'Record sales, warranties and customer collection', 'Directories': 'Manage repairers, suppliers, categories and services', 'Quotations': 'Prepare estimates and record customer decisions', 'Reports': 'Review shop activity and export your records', 'Settings & staff': 'Manage your shop, staff access and local preferences'})
        self.subtitle.setText(descriptions.get(name, "Saved records · changes persist on this computer"))
        for n, b in self.nav.items():
            b.setProperty("active", n == name)
            b.style().unpolish(b)
            b.style().polish(b)
        self.refresh()

    def refresh(self):
        self.safe(self._refresh)
        if not self.db.readonly and not self.folder_busy:
            self.folder_busy = True
            def folders():
                try:
                    CustomerRecords(self.s).sync_pending()
                finally:
                    self.folder_busy = False
            self.run(folders, 'Updating browsable customer folders…', refresh=False)

    def _refresh(self):
        old = self.stack.currentWidget()
        page = QWidget()
        self.layout = QVBoxLayout(page)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(14)
        method = {"Dashboard": self.dashboard, "New Repair Intake": self.intake_landing, "Active Repairs": self.active_repairs, "Ready for Delivery": lambda: self.active_repairs('ready'), "Repair History": lambda: self.active_repairs('history'), "Inventory": self.inventory, "Customers": self.customers, "Products sold": self.sales, "Jobs": self.jobs, "Dispatch & receive": self.custody, "Directories": self.directories, "Quotations": self.quotes, "Customer accounts": lambda: self.accounts("customer"), "Vendor accounts": lambda: self.accounts("vendor"), "Reports": self.reports, "Notifications": self.notifications, "Backups": self.backups, "Settings & staff": self.settings}[self.page_name]
        method()
        for index in range(self.layout.count()):
            widget = self.layout.itemAt(index).widget()
            if isinstance(widget, QLabel):
                widget.setWordWrap(True)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.stack.addWidget(scroll)
        self.stack.setCurrentWidget(scroll)
        if old:
            self.stack.removeWidget(old)
            old.deleteLater()

    def inventory(self):
        from .inventory_ui import InventoryPage
        self.layout.addWidget(InventoryPage(self))

    def toolbar(self, actions):
        bar = FlowLayout()
        bar.setSpacing(8)
        for text, call, primary in actions:
            b = button(text, lambda checked=False, fn=call: self.safe(fn), primary)
            if self.db.readonly and text.startswith(("+", "Record", "Issue", "Edit", "Restore", "Retry", "Cancel", "Save", "Collect", "Reverse", "Backup", "Configure")):
                b.setEnabled(False)
            bar.addWidget(b)
        self.layout.addLayout(bar)
        return bar

    def table(self, rows, columns=None):
        grid = Grid()
        grid.fill(rows, columns)
        self.layout.addWidget(grid, 1)
        return grid

    def selected(self, grid):
        row = grid.selected()
        if not row:
            raise RuleError("Select a record first.")
        return row

    def intake_landing(self):
        intro, intro_layout = panel('Start a repair intake', 'Search or register the customer, capture the mandatory customer photo, then add one or more physical products for the same visit.')
        steps = QLabel('1. Customer and photo  |  2. Product details and complaint  |  3. Accessories and received condition')
        steps.setWordWrap(True)
        steps.setObjectName('muted')
        intro_layout.addWidget(steps)
        self.layout.addWidget(intro)
        self.toolbar([('+ New repair intake', self.intake, True), ('Resume saved intake draft', self.intake_drafts, False), ('Customers', lambda: self.navigate('Customers'), False)])
        self.layout.addStretch()

    def active_repairs(self, filter_key=''):
        life = Lifecycle(self.s)
        filters, filter_layout = panel('Find repair work', 'Use search and status filters together. Double-click any row to open the repair workspace.')
        row = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText('Search job, customer, phone, device or serial…')
        choices = [('All active repairs',''), ('Ready for delivery','ready'), ('Attention required','attention'), ('At service center','external_centre'), ('With third party','external_vendor'), ('In-house','in_house'), ('Warranty claims','warranty_claims'), ('All repair history','history')] + [(label,key) for key,label in LABELS.items()]
        selector = combo(choices, filter_key)
        row.addWidget(search, 3)
        row.addWidget(selector, 1)
        filter_layout.addLayout(row)
        self.layout.addWidget(filters)
        grid = self.table([], COLUMNS)
        offset = [0]
        def reload(): grid.fill(life.rows(search.text(),selector.currentData(),offset[0]),COLUMNS)
        timer = QTimer(search); timer.setSingleShot(True);timer.setInterval(250);timer.timeout.connect(reload)
        search.textChanged.connect(lambda: (offset.__setitem__(0,0),timer.start()))
        selector.currentIndexChanged.connect(lambda: (offset.__setitem__(0,0),reload()))
        self.toolbar([('Open selected repair',lambda:self.job_detail(self.selected(grid)['id']),True), ('← Previous',lambda:(offset.__setitem__(0,max(0,offset[0]-50)),reload()),False), ('Next 50 →',lambda:(offset.__setitem__(0,offset[0]+50),reload()),False)])
        grid.cellDoubleClicked.connect(lambda *_:self.safe(lambda:self.job_detail(self.selected(grid)['id'])))
        reload()

    def dashboard(self):
        life = Lifecycle(self.s)
        rows = life.rows(filter_key="attention",limit=50)
        totals = life.dashboard_counts()
        self.toolbar([('+ New intake',self.intake,True),('Active repairs',lambda:self.navigate('Active Repairs'),False),('Resume draft',self.intake_drafts,False)])
        heading = QLabel('Your work queue')
        heading.setObjectName('sectionTitle')
        self.layout.addWidget(heading)
        definitions = [('Received','received','info'),('Under diagnosis','diagnosis','info'),('Waiting for approval','awaiting_approval','warning'),('Waiting for parts','waiting_parts','warning'),('Repair in progress','under_repair','info'),('Final quality check','final_qc','info'),('Ready for delivery','ready','success'),('Overdue','overdue','error')]
        cards = [MetricCard(title, totals.get(key, 0), lambda checked=False, k=key: self.safe(lambda: self.lifecycle_list(k)), tone)
                 for title, key, tone in definitions]
        self.layout.addWidget(CardGrid(cards))
        locations, locations_layout = panel('Location & history', 'These views can include the same repair. Counts are not added together.')
        location_links = FlowLayout()
        for title, key in [('In-house','in_house'),('At service center','external_centre'),('With third party','external_vendor'),('Warranty claims','warranty_claims'),('Delivered','collected')]:
            location_links.addWidget(button(f'{title} · {totals.get(key, 0)}', lambda checked=False, k=key: self.safe(lambda: self.lifecycle_list(k))))
        locations_layout.addLayout(location_links)
        self.layout.addWidget(locations)
        heading = QLabel('Attention required')
        heading.setObjectName('sectionTitle')
        self.layout.addWidget(heading)
        helper = QLabel('Latest 50 matching repairs. Double-click a job to act.')
        helper.setObjectName('subtitle')
        self.layout.addWidget(helper)
        attention=[r for r in rows if r['attention']]
        grid=self.table(attention,['number','device','location','attention','next_action'])
        grid.set_empty_text('Nothing needs attention right now\nStart a new intake when a customer arrives. Repairs that need action will appear here.')
        for col,width in enumerate((130,180,170,210,220)):
            grid.setColumnWidth(col,width)
        grid.cellDoubleClicked.connect(lambda *_:self.safe(lambda:self.job_detail(self.selected(grid)['id'])))
        data=self.q.dashboard()
        details = [f"{r['account_type'].title()} balance: {rupees(r['balance'])}" for r in data['balances']]
        details += [f"Products awaiting collection: {data['sales']}", f"Loose accessories: {sum(r['units'] for r in data['locations'] if r['type']=='accessory')}"]
        text=' · '.join(details)
        backup=data['backup']
        footer, footer_layout = panel('Shop status')
        from .lifecycle import local_time
        summary = QLabel(text+'\nLast verified backup: '+(local_time(backup['created']) if backup else 'No backup yet')+' · Messaging: '+self.db.setting('messaging_mode','test'))
        summary.setWordWrap(True)
        footer_layout.addWidget(summary)
        self.layout.addWidget(footer)

    def lifecycle_list(self,key):
        d=QDialog(self);d.setWindowTitle('Matching repairs');d.resize(1150,650)
        layout=QVBoxLayout(d);g=Grid();g.fill(Lifecycle(self.s).rows(filter_key=key,limit=0),COLUMNS);layout.addWidget(g)
        layout.addWidget(button('Open selected repair',lambda:self.safe(lambda:self.job_detail(self.selected(g)['id'])),True))
        g.cellDoubleClicked.connect(lambda *_:self.safe(lambda:self.job_detail(self.selected(g)['id'])))
        d.exec()

    def operations_dashboard(self):
        data = self.q.dashboard()
        counts = {(r["location"], r["type"]): r["units"] for r in data["locations"]}
        cards = QHBoxLayout()
        for label, key, color in (("Devices at shop", "shop", "#246a56"), ("With repairers", "vendor", "#916729"), ("At service centres", "centre", "#367e88"), ("In transit", "transit", "#7f6396")):
            card = QWidget()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(18, 14, 18, 14)
            box.addWidget(QLabel(label))
            # Items held by staff, by a technician or on a shop shelf are all "at shop".
            kinds = ("shop", "staff", "technician") if key == "shop" else (key,)
            value = QLabel(str(sum(counts.get((k, "device"), 0) for k in kinds)))
            value.setObjectName("metric")
            value.setStyleSheet("color:" + color)
            box.addWidget(value)
            box.addWidget(button("View matching jobs →", lambda checked=False, k=key: self.filtered_jobs(location=k + ":")))
            cards.addWidget(card)
        self.layout.addLayout(cards)
        secondary = QHBoxLayout()
        accessory = sum(r["units"] for r in data["locations"] if r["type"] == "accessory")
        secondary.addWidget(QLabel(f"Loose accessories: {accessory}     •     Sold items awaiting collection: {data['sales']}     •     Overdue jobs: {data['overdue']}"))
        secondary.addStretch()
        self.layout.addLayout(secondary)
        self.toolbar([("+ New intake", self.intake, True), ("+ Customer", self.customer_form, False), ("View overdue", lambda: self.filtered_jobs(overdue=True), False)])
        panel = QHBoxLayout()
        stages = Grid()
        stages.fill(data["stages"], ["stage", "jobs"])
        stages.cellDoubleClicked.connect(lambda *_: self.filtered_jobs(stage=self.selected(stages)["stage"]))
        panel.addWidget(stages, 2)
        aside = QWidget()
        aside.setObjectName("card")
        box = QVBoxLayout(aside)
        box.setContentsMargins(20, 20, 20, 20)
        box.addWidget(QLabel("ACCOUNTS & ATTENTION"))
        for row in data["balances"]:
            box.addWidget(QLabel(row["account_type"].title() + " balance\n" + rupees(row["balance"])))
        box.addSpacing(12)
        for row in data["messages"]:
            box.addWidget(QLabel(f"{row['messages']} message(s) · {row['state'].replace('_',' ')}"))
        box.addStretch()
        backup = data["backup"]
        box.addWidget(QLabel("Last verified backup\n" + (backup["created"][:16].replace("T", " ") + " UTC" if backup else "No backup yet")))
        box.addWidget(QLabel("Messaging: " + self.db.setting("messaging_mode", "test") + " mode"))
        panel.addWidget(aside, 1)
        self.layout.addLayout(panel, 1)
        self.layout.addWidget(QLabel("Location totals count physical primary devices. Work stages are a separate view of those jobs."))

    def filtered_jobs(self, **filters):
        d = QDialog(self)
        d.setWindowTitle("Matching jobs")
        d.resize(1100, 650)
        layout = QVBoxLayout(d)
        g = Grid()
        g.fill(self.q.jobs(**filters))
        layout.addWidget(g)
        layout.addWidget(button("Open selected job", lambda: self.safe(lambda: self.job_detail(self.selected(g)["id"])), True))
        d.exec()

    def customers(self):
        self.toolbar([("+ Customer", self.customer_form, True), ("Edit selected", lambda: self.customer_form(self.selected(grid)), False), ("Customer overview", lambda: self.customer_history(self.selected(grid)["id"]), False)])
        search = QLineEdit()
        search.setPlaceholderText("Search customer name or phone…")
        self.layout.addWidget(search)
        grid = self.table(self.q.customers())
        offset = [0]
        def reload():
            grid.fill(self.q.customers(search.text(), offset[0]))
        search.textChanged.connect(lambda: (offset.__setitem__(0, 0), reload()))
        self.toolbar([("← Previous", lambda: (offset.__setitem__(0, max(0, offset[0]-50)), reload()), False), ("Next 50 →", lambda: (offset.__setitem__(0, offset[0]+50), reload()), False)])
        grid.cellDoubleClicked.connect(lambda *_: self.customer_history(self.selected(grid)["id"]))

    def customer_form(self, row=None, *, parent=None, initial=None, refresh=True):
        if row:
            row = self.db.one("SELECT * FROM customers WHERE id=?", (row["id"],))
        from .customer_registration import register_customer
        ident = register_customer(self, row, parent=parent, initial=initial)
        if ident:
            if refresh:self.refresh()
            return ident

    def customer_history(self, ident):
        CustomerOverview(self, ident).exec()

    def intake_drafts(self):
        d = QDialog(self)
        d.setWindowTitle('Saved intake drafts')
        d.resize(1000, 550)
        layout = QVBoxLayout(d)
        grid = Grid()
        grid.fill(CustomerRecords(self.s).drafts(), ['id', 'customer', 'updated'])
        layout.addWidget(grid)
        def resume():
            row = self.selected(grid)
            d.accept()
            self.intake(draft=row)
        layout.addWidget(button('Resume selected draft', lambda: self.safe(resume)))
        grid.cellDoubleClicked.connect(lambda *_: self.safe(resume))
        d.exec()

    def sales(self):
        self.toolbar([("+ Sold product", self.sale_form, True), ("Collect selected product", lambda: self.sale_collect(self.selected(grid)["id"]), False), ("+ Warranty/service job", lambda: self.intake(sale=self.selected(grid)), False), ("Add purchase proof", lambda: self.attach(sale_id=self.selected(grid)["id"]), False)])
        grid = self.table(self.db.rows("SELECT s.*,c.name AS customer FROM sales s JOIN customers c ON c.id=s.customer_id ORDER BY s.id DESC LIMIT 200"), ["id", "customer", "device", "serial", "invoice_ref", "sale_date", "amount", "provider", "warranty_end", "collected"])

    def sale_form(self):
        d = Form("Register a sold product", self)
        d.add("customer_id", "Customer", CustomerSelector(self.s))
        d.add("category_id", "Category", MasterSelector(self.s, "category"))
        for key, label in (("device", "Brand / model"), ("serial", "Serial number (optional)"), ("invoice_ref", "Invoice reference"), ("provider", "Warranty provider"), ("warranty_terms", "Warranty terms")):
            d.text(key, label, multiline=key == "warranty_terms")
        for key, label in (("sale_date", "Sale date"), ("invoice_date", "Invoice date"), ("warranty_start", "Warranty starts"), ("warranty_end", "Warranty ends")):
            d.date(key, label, today() if key in ("sale_date", "invoice_date") else None)
        d.text("amount", "Sale amount (INR)", "0")
        d.text("cost", "Shop cost (INR)", "0")
        def save(v):
            v["amount"], v["cost"] = money(v["amount"]), money(v["cost"])
            self.s.save_sale(**v)
        if d.submit(save):
            self.refresh()

    def export_rows(self, title, rows):
        path, _ = QFileDialog.getSaveFileName(self, "Export " + title, title + ".xlsx", "Excel (*.xlsx);;CSV (*.csv);;PDF (*.pdf)")
        if path:
            self.run(lambda: self.docs.export(path, title, rows), "Exporting report…", callback=lambda p: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))

    def reports(self):
        controls = FlowLayout()
        kind = combo(["jobs", "custody", "overdue", "warranty", "job_cards", "repair_parts", "part_warranties", "warranty_claims", "customer_dues", "vendor_dues", "payments", "transport", "margins"])
        start = QLineEdit(today()[:8] + "01")
        end = QLineEdit(today())
        route = combo([("All routes", "")] + [(x.replace("_", " "), x) for x in ROUTES])
        controls.addWidget(kind)
        controls.addWidget(QLabel("From"))
        controls.addWidget(start)
        controls.addWidget(QLabel("To"))
        controls.addWidget(end)
        controls.addWidget(route)
        self.layout.addLayout(controls)
        filters = FlowLayout()
        customer = QLineEdit()
        customer.setPlaceholderText("Customer ID (optional)")
        category = combo([("All categories", None)] + [(r["name"], r["id"]) for r in self.s.masters("category")])
        vendor = combo([("All vendors / centres", None)] + [(r["name"], r["id"]) for r in self.db.rows("SELECT id,name FROM masters WHERE kind IN ('vendor','centre')")])
        filters.addWidget(customer)
        filters.addWidget(category)
        filters.addWidget(vendor)
        self.layout.addLayout(filters)
        self.toolbar([("Run report", lambda: self.run(lambda: self.q.report(kind.currentData(), start.text(), end.text(), route.currentData(), int(customer.text()) if customer.text() else None, category.currentData(), vendor.currentData()), "Running report…", callback=lambda rows: grid.fill(rows), refresh=False), True), ("Export PDF / Excel / CSV", lambda: self.export_rows(kind.currentText(), grid.rows), False)])
        grid = self.table([])
        self.layout.addWidget(QLabel("Dues are current account balances. Payments use posting dates; job reports use intake dates. Margin is before overheads; payments do not change revenue."))

    def notifications(self):
        self.toolbar([("Preview selected", lambda: self.message_preview(self.selected(grid)), True), ("Retry confirmed failure", lambda: (Outbox(self.s).action(self.selected(grid)["id"], "retry"), self.refresh()), False), ("Cancel selected", lambda: (Outbox(self.s).action(self.selected(grid)["id"], "cancel"), self.refresh()), False), ("Process queue", self.background, False), ("Configure channels", self.channel_settings, False)])
        if self.s.user['role']=='owner':
            self.toolbar([('Configure staff / vendor recipients',self.recipient_form,False),('Send saved statement PDF',self.send_document_form,False)])
        grid = self.table(self.db.rows("SELECT * FROM outbox ORDER BY id DESC LIMIT 300"), ["id", "job_id", "event", "channel", "destination", "state", "attempts", "error", "created"])
        self.layout.addWidget(QLabel("Captured = local test only. Accepted = provider accepted, delivery unknown. Uncertain outcomes are never automatically resent."))

    def recipient_form(self):
        d=Form('Staff or vendor notification recipient',self,'Owners and assigned technicians can receive job updates. Vendor recipients are used for deliberately selected statements.')
        d.select('kind','Recipient role',['staff','vendor'])
        d.text('entity_id','Staff ID or vendor directory ID')
        d.select('channel','Channel',['email','whatsapp'])
        d.text('destination','Email / international phone')
        d.check('consent','Recipient agreed to this channel')
        d.check('active','Enabled',True)
        if d.submit(lambda v:self.s.save_recipient(**{**v,'entity_id':int(v['entity_id'])})):
            self.refresh()

    def send_document_form(self):
        d=Form('Review statement recipient before queueing',self,'This queues the selected saved PDF for the selected email recipient. In test mode it remains local. In live mode the worker submits it after this action.')
        d.select('attachment_id','Saved issued document',[(r['title'],r['id']) for r in self.db.rows("SELECT * FROM attachments WHERE kind='issued_document' ORDER BY id DESC LIMIT 300")])
        d.select('recipient_id','Configured email destination',[(r['destination'],r['id']) for r in self.db.rows("SELECT * FROM recipients WHERE channel='email' AND active=1 ORDER BY destination")])
        d.text('subject','Email subject','Your account statement')
        d.text('body','Message','Please find the requested account statement attached.',multiline=True)
        if d.submit(lambda v:self.s.queue_document(**v,operation_id=uuid.uuid4().hex)):
            self.refresh()

    def message_preview(self, row):
        payload = json.loads(row["payload"])
        d = Form("Notification preview", self, f"To: {row['destination']} via {row['channel']}\nState: {row['state']}\nProvider reference: {row['provider_id'] or 'None'}")
        subject = d.text("subject", "Subject", payload["subject"])
        subject.setReadOnly(True)
        body = d.text("body", "Exact saved body", payload["body"], multiline=True)
        body.setMaximumHeight(350)
        body.setReadOnly(True)
        d.buttons.button(d.buttons.StandardButton.Save).hide()
        d.exec()

    def backups(self):
        self.toolbar([("Backup now", lambda: self.run(lambda: Backups(self.s).create(), "Creating and validating recovery backup…"), True), ("Create long-term archive", lambda: self.run(lambda: Backups(self.s).create("archive"), "Creating complete long-term archive…"), False), ("Validate archive", lambda: self.choose_backup("validate"), False), ("Open backup for viewing", lambda: self.choose_backup("view"), False), ("Restore backup", lambda: self.choose_backup("restore"), False)])
        self.table(self.db.rows("SELECT * FROM backups ORDER BY id DESC LIMIT 100"))
        self.layout.addWidget(button('Retry pending external-drive copies', lambda: self.run(lambda: Backups(self.s).retry_external(), 'Verifying external-drive copies…')))
        self.layout.addWidget(QLabel("Daily recovery copies: " + str(self.db.setting("backup_retention", 30)) + " retained. Long-term archives: every " + str(self.db.setting("archive_days", 90)) + " days; never automatically deleted.\nDestination: " + str(self.db.setting("backup_destination") or self.db.root / "backups")))

    def choose_backup(self, action):
        path, _ = QFileDialog.getOpenFileName(self, "Select a verified RepairShop archive", str(self.db.root / "backups"), "RepairShop archive (*.zip)")
        if not path:
            return
        def preview(manifest):
            summary = f"Backup: {manifest['created']}\nSchema: {manifest['schema']}\nCustomers: {manifest['customers']}\nJobs: {manifest['jobs']}\nFiles: {len(manifest['files'])}"
            if action == "validate":
                QMessageBox.information(self, "Archive verified", summary)
            elif action == "view":
                view_db = Backups(self.s).open_view(path)
                from .services import Service
                view_service = Service(view_db)
                # Archived roles are not accepted as live authorization. Owner has already authorized opening; use the archived owner solely for read-only queries.
                view_service.user = view_db.one("SELECT * FROM users WHERE role='owner' AND active=1 LIMIT 1")
                viewer = MainWindow(view_service)
                if not hasattr(self, "viewers"):
                    self.viewers = []
                self.viewers.append(viewer)
                viewer.show()
            else:
                if self.tasks or self.worker_busy:
                    raise RuleError("Wait for background work to finish before restoring.")
                d = Form("Restore database and attachments", self, summary + "\nThis replaces live shop data. A verified safety backup and previous files are retained. Outgoing messages stay paused. Restart and sign in with the restored account afterward.")
                d.text("confirmation", "Type RESTORE to confirm")
                def restore(v):
                    self.timer.stop()
                    self.run(lambda: Backups(self.s).restore(path, v["confirmation"]), "Restoring verified archive…", callback=lambda p: (QMessageBox.information(self, "Restore complete", "Restart the application. Previous state is retained at:\n" + str(p)), QApplication.quit()), refresh=False)
                d.submit(restore)
        self.run(lambda: Backups.validate(path), "Validating archive and preview…", callback=preview, refresh=False)

    def settings(self):
        self.toolbar([("Edit shop & backup settings", self.shop_settings, True), ("Printing & documents", self.print_settings, False), ("Configure messaging", self.channel_settings, False), ("+ Staff login", self.staff_form, False), ("Edit selected staff", lambda: self.staff_form(self.selected(grid)), False)])
        self.layout.addWidget(QLabel(f"{self.db.setting('shop_name')}\nINR · {self.db.setting('timezone')}\nData location: {self.db.root}\nMessaging: {self.db.setting('messaging_mode','test')} mode · Sending paused: {self.db.setting('notifications_paused',False)}"))
        grid = self.table(self.db.rows("SELECT id,username,name,role,active FROM users ORDER BY name"))

    def shop_settings(self):
        d = Form("Shop & backup settings", self)
        for key, label in (("shop_name", "Shop name"), ("address", "Shop address"), ("hours", "Opening hours"), ("timezone", "Display timezone"), ("backup_destination", "Recovery backup folder"), ("external_backup", "Optional existing external-drive folder")):
            d.text(key, label, self.db.setting(key, ""), multiline=key == "address")
        d.select("decline_policy", "Default for new jobs", [("No customer charge", "NO_CUSTOMER_CHARGE"), ("Agreed transport only", "AGREED_TRANSPORT_ONLY")], self.db.setting("decline_policy"))
        d.text("backup_retention", "Recent daily copies to keep", self.db.setting("backup_retention", 30))
        d.select("archive_days", "Long-term archive interval", [("60 days", 60), ("90 days", 90)], self.db.setting("archive_days", 90))
        def save(v):
            v["backup_retention"] = int(v["backup_retention"])
            self.s.settings(v)
        if d.submit(save):
            self.refresh()

    def print_settings(self):
        d = Form("Printing & documents", self,
                 "These apply to every generated PDF. A4 is the shop standard; A5 re-lays the same "
                 "content for a smaller sheet rather than shrinking it.")
        d.select("paper_size", "Default paper size", [("A4", "A4"), ("A5", "A5")], self.db.setting("paper_size", "A4"))
        d.select("include_photos", "Include photos in WhatsApp / email",
                 [("No", False), ("Yes", True)], bool(self.db.setting("include_photos", False)))
        d.layout.addRow(QLabel("Only customer-facing product and accessory photos are ever attached. "
                               "Internal evidence and local file paths are never sent."))
        if d.submit(lambda v: self.s.settings(v)):
            self.refresh()

    def staff_form(self, row=None):
        row = row or {}
        d = Form("Staff access", self, "Each staff member has a separate local login. Keep at least one active owner.")
        for key, label in (("username", "Username"), ("name", "Display name")):
            d.text(key, label, row.get(key))
        d.select("role", "Role", ["owner", "counter", "technician"], row.get("role", "counter"))
        d.text("password", "New password (10+ characters)", password=True)
        d.check("active", "Active login", row.get("active", True))
        if d.submit(lambda v: self.s.save_staff(**v, ident=row.get("id"))):
            self.refresh()

    def channel_settings(self):
        self.s.require_permission('messaging_admin')
        d = Form("Messaging channels & credentials", self, "Test mode captures locally. Live mode sends queued, consented updates while the app is open. Credentials are stored in Windows Credential Manager.")
        d.resize(700, 850)
        d.select("mode", "Sending mode", [("Local test capture (no internet)", "test"), ("Live providers", "live")], self.db.setting("messaging_mode", "test"))
        d.check("paused", "Pause outgoing messages", self.db.setting("notifications_paused", False))
        wa = self.db.setting("whatsapp", {})
        smtp = self.db.setting("smtp", {})
        d.text("phone_number_id", "WhatsApp phone number ID", wa.get("phone_number_id"))
        d.text("api_version", "Supported Meta Graph API version", wa.get("api_version"))
        d.text("wa_token", "New WhatsApp token (blank keeps stored)", password=True)
        d.text("templates", "Event | approved template name | language per line", "\n".join(f"{event} | {cfg['name']} | {cfg.get('language','en')}" for event,cfg in self.db.setting("templates", {}).items()), multiline=True)
        d.text("host", "SMTP server", smtp.get("host"))
        d.text("port", "STARTTLS port", smtp.get("port", 587))
        d.text("username", "SMTP account", smtp.get("username"))
        d.text("from_address", "Sender email", smtp.get("from_address"))
        d.select("auth", "Provider authentication", [("OAuth2 access token", "oauth2"), ("Provider-supported app password", "app_password")], smtp.get("auth", "oauth2"))
        d.text("smtp_token", "New email token / app password", password=True)
        d.text('reminder_days','Collection reminder interval days (0 = off, max 3 per job)',self.db.setting('reminder_days',0))
        d.text('email_subject','Email subject template',self.db.setting('email_subject','{job_number} · {event}'))
        d.text('message_template','Message body template',self.db.setting('message_template','{shop_name}\n{job_number} · {device}\n{message}'),multiline=True)
        d.layout.addRow('',QLabel('Variables: {shop_name}, {job_number}, {device}, {message},\n{event}, {shop_address}, {shop_hours}'))
        def save(v):
            templates = {}
            for line in v["templates"].splitlines():
                if line.strip():
                    event, name, language = [x.strip() for x in line.split("|")]
                    templates[event] = dict(name=name, language=language)
            if v["wa_token"]:
                secret("whatsapp_token", v["wa_token"])
            if v["smtp_token"]:
                secret("smtp_credential", v["smtp_token"])
            self.s.settings({"messaging_mode": v["mode"], "notifications_paused": v["paused"], "whatsapp": {"phone_number_id": v["phone_number_id"], "api_version": v["api_version"]}, "smtp": {"host": v["host"], "port": int(v["port"]), "username": v["username"], "from_address": v["from_address"], "auth": v["auth"]}, "templates": templates, 'reminder_days':int(v['reminder_days']),'email_subject':v['email_subject'],'message_template':v['message_template']})
        if d.submit(save):
            self.refresh()

    def sale_collect(self, ident):
        d = Form("Product collection", self)
        d.text("collector", "Collector's name / relationship")
        d.text("acknowledgment", "Acknowledgment / reference", multiline=True)
        if d.submit(lambda v: self.s.collect_sale(ident, **v)):
            self.refresh()

    def jobs(self):
        if not self.db.readonly and self.s.user["role"] in ("owner", "counter"):
            self.toolbar([("Intake drafts", self.intake_drafts, False)])
        self.toolbar([("+ New intake", self.intake, True), ("Open job", lambda: self.job_detail(self.selected(grid)["id"]), False), ("+ Linked follow-up", lambda: self.intake(parent=self.selected(grid)["id"]), False)])
        bar = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Job number, customer, phone, device or serial…")
        stage = combo([("All stages", "")] + [(x.replace("_", " ").title(), x) for x in STAGES])
        route = combo([("All routes", "")] + [(x.replace("_", " ").title(), x) for x in ROUTES])
        bar.addWidget(search, 2)
        bar.addWidget(stage)
        bar.addWidget(route)
        self.layout.addLayout(bar)
        grid = self.table(self.q.jobs(), ["id", "number", "customer", "device", "stage", "custody", "responsible", "collection_due", "balance"])
        offset = [0]
        def reload():
            grid.fill(self.q.jobs(search.text(), stage.currentData(), route.currentData(), offset=offset[0]), ["id", "number", "customer", "device", "stage", "custody", "responsible", "collection_due", "balance"])
        search.textChanged.connect(lambda: (offset.__setitem__(0, 0), reload()))
        stage.currentIndexChanged.connect(lambda: (offset.__setitem__(0, 0), reload()))
        route.currentIndexChanged.connect(lambda: (offset.__setitem__(0, 0), reload()))
        self.toolbar([("← Previous", lambda: (offset.__setitem__(0, max(0, offset[0]-50)), reload()), False), ("Next 50 →", lambda: (offset.__setitem__(0, offset[0]+50), reload()), False)])
        grid.cellDoubleClicked.connect(lambda *_: self.job_detail(self.selected(grid)["id"]))

    def intake(self, sale=None, parent=None, draft=None, customer_id=None, device_id=None):
        if self.db.readonly:
            raise RuleError("Archive viewing is read-only.")
        self.s.require_permission('intake')
        if draft:
            saved = json.loads(draft['payload'])
            parent = saved.get('parent_id')
            sale = self.db.one('SELECT * FROM sales WHERE id=?', (saved.get('sale_id'),))
        source = self.s.job(parent) if parent else sale or {}
        if customer_id:
            source = dict(source, customer_id=customer_id, device_id=device_id)
        d = IntakeForm("New repair intake", self, "Select the customer and product, record the problem, then review. Receive several products in one visit. Your progress is saved as a draft.")
        d.resize(700, 850)
        d.section('Customer & authorization')
        def register_customer(search):
            initial={'phone':search} if search and search.replace('+','').replace(' ','').isdigit() else {'name':search}
            return self.customer_form(parent=d,initial=initial,refresh=False)
        d.add("customer_id", "Device owner", CustomerSelector(self.s, source.get("customer_id"),create=register_customer))
        d.text("submitter", "Submitted by (if different)")
        d.text("relationship", "Relationship to owner")
        d.add("update_contact_id", "Additional authorized updates to", CustomerSelector(self.s))
        d.section('Product & reported fault')
        category = MasterSelector(self.s, "category")
        d.add("category_id", "Product category", category)
        service_selector=MasterSelector(self.s,'service')
        d.add('service_id','Repair / service',service_selector)
        category.box.currentIndexChanged.connect(lambda:service_selector.set_category(category.value()))
        d.text("device", "Brand / model / device", source.get("device", ""))
        from .intake_fields import MasterNameField
        d.add('brand','Device brand',MasterNameField(self.s,'brand',source.get('brand','')))
        d.add('model','Device model',MasterNameField(self.s,'model',source.get('model','')))
        d.text("serial", "Serial (unknown is allowed)", source.get("serial", ""))
        d.select("origin", "Originally purchased", [("This shop", "shop"), ("Elsewhere", "elsewhere")], "shop" if sale else "elsewhere")
        d.text("complaint", "Reported fault", multiline=True)
        d.text("damage", "Visible condition / damage", multiline=True)
        d.text("customer_requirement", "Additional customer requirement", multiline=True)
        accessory_box = QWidget()
        accessories_layout = QVBoxLayout(accessory_box)
        accessories_layout.setContentsMargins(0, 0, 0, 0)
        checks = []
        def load_accessories():
            while accessories_layout.count():
                child = accessories_layout.takeAt(0).widget()
                if child:
                    child.deleteLater()
            checks.clear()
            rows = self.db.rows("SELECT m.* FROM masters m JOIN category_accessories ca ON ca.accessory_id=m.id WHERE ca.category_id=? AND m.active=1 ORDER BY m.name", (category.value(),))
            for row in rows:
                line = QWidget()
                controls = QHBoxLayout(line)
                controls.setContentsMargins(0,0,0,0)
                check = QCheckBox(row["name"])
                check.setChecked(False)
                quantity = QSpinBox()
                quantity.setRange(1,999)
                quantity.setValue(1)
                quantity.setMaximumWidth(105)
                quantity.setStyleSheet('QSpinBox QLineEdit {padding:0;border:0;background:transparent;}')
                quantity.lineEdit().setStyleSheet('padding:0;border:0;min-height:0;background:transparent;')
                quantity.setEnabled(False)
                quantity.setVisible(False)
                check.toggled.connect(quantity.setEnabled)
                check.toggled.connect(quantity.setVisible)
                check.quantity_control = quantity
                serial = QLineEdit()
                serial.setPlaceholderText('Serial / identifying mark (optional)')
                serial.setEnabled(False)
                serial.setVisible(False)
                check.toggled.connect(serial.setEnabled)
                check.toggled.connect(serial.setVisible)
                check.serial_control=serial
                # Intake condition per accessory. "Not tested" is a real answer at the
                # counter, so it is offered alongside working/not working/damaged.
                from .services import ITEM_CONDITIONS
                condition=combo([(name,name) for name in ITEM_CONDITIONS],'Not Tested')
                condition.setEnabled(False);condition.setVisible(False)
                check.toggled.connect(condition.setEnabled);check.toggled.connect(condition.setVisible)
                check.condition_control=condition
                notes=QLineEdit();notes.setPlaceholderText('Accessory notes (optional)')
                notes.setEnabled(False);notes.setVisible(False)
                check.toggled.connect(notes.setEnabled);check.toggled.connect(notes.setVisible)
                check.notes_control=notes
                check.photo_id=None
                photo=button('Photo',lambda checked=False,box=check:self.safe(lambda:self.accessory_photo(support,box)))
                photo.setEnabled(False);photo.setVisible(False)
                check.toggled.connect(photo.setEnabled);check.toggled.connect(photo.setVisible)
                check.photo_control=photo
                controls.addWidget(check,1)
                quantity_label=QLabel('Qty');quantity_label.hide();check.toggled.connect(quantity_label.setVisible)
                controls.addWidget(quantity_label)
                controls.addWidget(quantity)
                controls.addWidget(serial,1)
                controls.addWidget(condition)
                controls.addWidget(notes,1)
                controls.addWidget(photo)
                accessories_layout.addWidget(line)
                checks.append(check)
            if hasattr(d, 'intake_support'):
                d.intake_support.watch_accessories()
            if hasattr(d, 'wizard'):
                d.wizard.category_changed()
        category.box.currentIndexChanged.connect(load_accessories)
        d.section('Accessories')
        d.layout.addRow("Accessories actually received", accessory_box)
        def add_accessory():
            extra = Form("Add reusable accessory", d)
            extra.text("name", "Accessory name")
            def save(v):
                if not category.value():
                    raise RuleError("Choose the product category first.")
                selected_names = {x.text() for x in checks if x.isChecked()}
                selected_names.add(v['name'].strip())
                self.s.save_master("accessory", v["name"], category_id=category.value())
                load_accessories()
                for check in checks:
                    check.setChecked(check.text() in selected_names)
            extra.submit(save)
        d.layout.addRow("", button("+ Add new accessory choice", add_accessory))
        d.section('Dates, consent & payments')
        # Route is selected after inspection and warranty verification in the guided workspace.
        d.date("repair_due", "Estimated repair completion")
        d.date("collection_due", "Estimated customer collection")
        d.select("policy", "Agreed decline / return policy", [("No customer charge", "NO_CUSTOMER_CHARGE"), ("Agreed transport only", "AGREED_TRANSPORT_ONLY")], self.db.setting("decline_policy"))
        d.text("transport_agreed", "Agreed transport charge (INR)", "0")
        d.text("assessment_agreed", "Explicit agreed assessment (INR)", "0")
        d.check("assessment_consent", "Assessment / transport consent recorded")
        d.text("initial_estimate", "Initial estimated cost (INR)", "0")
        d.text("deposit", "Deposit required to start repair (INR)", "0")
        d.text("advance", "Advance received now (INR)", "0")
        d.text("intake_ref", "Visit reference (groups these products)")
        support = IntakePhotos(self, d, checks, source, sale, parent, draft)
        from .visit_intake import VisitIntake
        visit=VisitIntake(self,d,support,checks,draft)
        from .intake_wizard import IntakeWizard
        IntakeWizard(self,d,support,visit,checks,draft)
        result = []
        def save(v):
            result.extend(visit.save())
        if d.submit(save):
            # The business records are already committed. Document generation and any
            # optional WhatsApp/email or printing happen afterwards and can fail without
            # affecting the visit or its jobs.
            d.keep_draft = None
            self.refresh()
            def receipts():
                documents=[]
                for ident in result:
                    documents.append(('Job Card '+self.s.job(ident)['number'],self.docs.generate('intake_receipt',ident),ident))
                documents.append(('Visit intake receipt',self.docs.visit_receipt(result),result[0]))
                return documents
            self.run(receipts,'Creating receiving receipts…',refresh=False,
                     callback=lambda documents:self.post_intake(result,documents),
                     failure=lambda exc:self.post_intake(result,[],str(exc)))

    def post_intake(self,jobs,documents,document_error=''):
        """Confirmation, then optional delivery. Messaging never rolls back the intake."""
        from .post_intake import PostIntakeDialog
        PostIntakeDialog(self,jobs,documents,document_error).exec()
        self.refresh()
        if len(jobs)==1:self.job_detail(jobs[0])
        else:self.visit_summary(jobs)

    def accessory_photo(self, support, box):
        """Camera or upload evidence for one received accessory, using the existing photo store."""
        customer_id = support.form.fields['customer_id'].text()
        if not customer_id:
            raise RuleError('Select or register the device owner before photographing accessories.')
        from .camera import CameraDialog
        from .customer_records import CustomerRecords
        choice = QMessageBox(self)
        choice.setWindowTitle('Accessory photo')
        choice.setText('Add a photo of ' + box.text() + '.')
        camera = choice.addButton('Camera', QMessageBox.ButtonRole.AcceptRole)
        upload = choice.addButton('Upload', QMessageBox.ButtonRole.AcceptRole)
        choice.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
        choice.exec()
        records = CustomerRecords(self.s)
        if choice.clickedButton() is camera:
            dialog = CameraDialog(lambda image, captured: (image.copy(), captured), self)
            if not dialog.exec() or not dialog.photo_id:
                return
            image, captured = dialog.photo_id
            box.photo_id = records.save_photo(image, customer_id, 'accessory', box.text(), captured=captured)
        elif choice.clickedButton() is upload:
            path, _ = QFileDialog.getOpenFileName(self, 'Choose accessory photo', '', 'Photos (*.jpg *.jpeg *.png *.bmp *.webp)')
            if not path:
                return
            from PyQt6.QtGui import QImageReader
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            box.photo_id = records.save_photo(reader.read(), customer_id, 'accessory', box.text())
        else:
            return
        box.photo_control.setText('Photo ✓')
        support.changed()

    def visit_summary(self,identifiers):
        from .visits import Visits
        rows=[self.s.job(ident) for ident in identifiers]
        visit=Visits(self.s).for_job(identifiers[0]) or {'number':rows[0]['intake_ref'],'status':'Open'}
        d=QDialog(self);d.setWindowTitle('Products received · '+visit['number']);d.resize(1000,600)
        layout=QVBoxLayout(d);layout.addWidget(QLabel(f"{len(rows)} products received for {rows[0]['customer']} · Visit {visit['number']} · {visit['status']}"))
        grid=Grid();grid.fill(rows,['number','device','serial','complaint','stage']);layout.addWidget(grid)
        layout.addWidget(button('Open selected repair',lambda:self.safe(lambda:self.job_detail(self.selected(grid)['id']))))
        layout.addWidget(button('Print visit receipt',lambda:self.run(lambda:self.docs.visit_receipt(identifiers),'Creating visit receipt…',callback=lambda p:QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))),refresh=False)))
        layout.addWidget(button('Close',d.accept));d.exec()

    def visit_jobs(self,ident):
        from .visits import Visits
        visit=Visits(self.s).for_job(ident)
        if visit:
            return self.visit_summary([r['id'] for r in visit['jobs']])
        job=self.s.job(ident)
        self.visit_summary([r['id'] for r in self.db.rows('SELECT id FROM jobs WHERE intake_ref=? AND customer_id=? ORDER BY id',(job['intake_ref'],job['customer_id']))])

    def job_detail(self, ident):
        JobWorkspace(self, ident).exec()
        self.refresh()

    def job_records(self, ident):
        j = self.s.job(ident)
        d = QDialog(self)
        d.setWindowTitle(j["number"] + " · " + j["device"])
        d.resize(1200, 800)
        layout = QVBoxLayout(d)
        title = QLabel(j["number"] + "  /  " + j["device"])
        title.setObjectName("title")
        layout.addWidget(title)
        info = QLabel(f"{j['customer']} · {j['phone']}   |   {j['stage'].replace('_',' ').title()}   |   {j['route'].replace('_',' ').title()}")
        layout.addWidget(info)
        actions = FlowLayout()
        commands = [("Update stage / test", lambda: self.stage_form(ident)), ("Assign / change route", lambda: self.assign_form(ident)), ("Record work", lambda: self.work_form(ident)), ("Warranty decision", lambda: self.warranty_form(ident)), ("Issue quotation", lambda: self.quote_form(ident)), ("Move / collect items", lambda: self.move_form(ident)), ("Revise dates", lambda: self.date_form(ident)), ("Add photo / evidence", lambda: self.attach(job_id=ident)), ("Create document", lambda: self.document_form(ident)), ("Replacement item", lambda: self.replacement_form(ident)), ("Hold / cancellation reason", lambda: self.hold_form(ident)), ("Agreed decline charges", lambda: self.decline_form(ident))]
        for index, (text, fn) in enumerate(commands):
            b = button(text, lambda checked=False, call=fn: self.safe(lambda: (call(), reload())))
            b.setEnabled(not self.db.readonly)
            if self.s.user["role"] == "technician" and text not in ("Record work", "Update stage / test"):
                b.setEnabled(False)
            actions.addWidget(b)
        layout.addLayout(actions)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        if j.get('device_id'):
            tabs.addTab(DevicePhotos(self, j['device_id'], ident), 'Product photos')
        if j.get('photo_id'):
            from .customer_ui import show_photo
            photo_label = QLabel()
            photo = self.db.one('SELECT * FROM attachments WHERE id=?', (j['photo_id'],))
            show_photo(photo_label, self.db, photo, 220)
            photo_page = QWidget()
            photo_layout = QVBoxLayout(photo_page)
            photo_layout.addWidget(photo_label)
            description = QLabel(f"{photo['title']} — Captured {photo['captured']}" if photo else 'Intake photo missing')
            description.setTextFormat(Qt.TextFormat.PlainText)
            photo_layout.addWidget(description)
            tabs.addTab(photo_page, 'Intake person')
        grids = {}
        definitions = [("holdings", "Items & custody"), ("work", "Repair work"), ("assignments", "Assignments"), ("warranty", "Warranty"), ("quotes", "Quotations"), ("entries", "Accounts"), ("expenses", "Transport & expenses"), ("movements", "Handovers"), ("attachments", "Documents"), ("outbox", "Messages"), ("audit", "Audit")]
        for key, label in definitions:
            grid = Grid()
            grids[key] = grid
            tabs.addTab(grid, label)
        overview = QLabel()
        overview.setWordWrap(True)
        layout.addWidget(overview)
        def reload():
            current = self.s.job(ident)
            info.setText(f"{current['customer']} · {current['phone']}   |   {current['stage'].replace('_',' ').title()}   |   {current['route'].replace('_',' ').title()}")
            history = self.q.history(ident)
            for key, grid in grids.items():
                grid.fill(history.get(key, []))
            overview.setText(f"Reported: {current['complaint']}\nCondition: {current['damage'] or 'Not recorded'}\nRepair due: {current['repair_due'] or 'Not set'} · Collection due: {current['collection_due'] or 'Not set'} · Hold: {current['hold_reason'] or 'None'}")
        grids["attachments"].cellDoubleClicked.connect(lambda *_: self.open_attachment(self.selected(grids["attachments"])["path"]))
        grids["quotes"].cellDoubleClicked.connect(lambda *_: self.safe(lambda: (self.decision_form(self.selected(grids["quotes"])), reload())))
        reload()
        d.exec()
        self.refresh()

    def stage_form(self, ident):
        self.job_detail(ident)

    def assign_form(self, ident):
        d = Form("Repair assignment", self, "Responsibility and custody are separate. This assignment does not move any item.")
        d.select("route", "Route", ROUTES, self.s.job(ident)["route"])
        options = [("No external repairer", None)] + [(r["name"] + " · " + r["kind"], r["id"]) for r in self.db.rows("SELECT * FROM masters WHERE kind IN ('vendor','centre') AND active=1 ORDER BY name")]
        d.select("contact_id", "Vendor / service centre", options)
        d.select("technician_master_id", "Internal technician", [("Unassigned", None)] + [(r["name"], r["id"]) for r in self.db.rows("SELECT id,name FROM masters WHERE kind='technician' AND active=1 ORDER BY name")])
        d.text("reference", "External work reference")
        d.text("estimate", "Vendor estimate (INR; not a bill)", "0")
        d.submit(lambda v: self.s.assign(ident, **{**v, "estimate": money(v["estimate"])}))

    def work_form(self, ident):
        d = Form("Record repair work", self)
        d.select("kind", "Record type", ["diagnosis", "assessment", "repair", "installed_part", "test", "vendor_update"])
        d.text("notes", "Findings / actions / work performed", multiline=True)
        d.text("parts", "Installed or replacement parts", multiline=True)
        d.text("cost", "Recorded part cost (INR; post expense separately)", "0")
        d.text("started", "Actual start time (optional)")
        d.text("completed", "Actual completion time (optional)")
        d.text("service_warranty", "Service warranty supplied", multiline=True)
        def save(v):
            kind = v.pop("kind")
            v["cost"] = money(v["cost"])
            self.s.record_work(ident, kind, v)
        d.submit(save)

    def warranty_form(self, ident):
        d = Form("Centre warranty assessment", self, "Date eligibility is calculated separately from the centre's actual decision.")
        d.select("decision", "Centre decision", ["pending", "accepted", "rejected", "partial"])
        for key, label in (("rma", "Claim / RMA reference"), ("findings", "Findings / customer-facing reason"), ("covered", "Covered work"), ("excluded", "Excluded work"), ("terms", "Actual warranty terms / evidence reference")):
            d.text(key, label, multiline=key != "rma")
        d.submit(lambda v: self.s.record_warranty(ident, **v))

    def date_form(self, ident):
        j = self.s.job(ident)
        d = Form("Revise estimated dates", self, "Dates use calendar days. Each revision preserves the previous values and its reason.")
        for key, label in (("repair_due", "Repair completion"), ("collection_due", "Customer collection"), ("return_due", "External return")):
            d.date(key, label, j[key])
        d.text('duration_days','Or estimated repair duration (calendar days)')
        d.date('reference_date','Duration reference date')
        d.text("reason", "Reason for estimate / revision", multiline=True)
        d.submit(lambda v: self.s.dates(ident, **{**v, 'duration_days': int(v['duration_days']) if v['duration_days'] else None}, version=j["version"]))

    def hold_form(self, ident):
        d = Form("On hold / cancelled / unrepairable", self, "Record the outcome reason. Custody and account obligations remain visible. Clear the reason to release a hold.")
        d.text("reason", "Reason / outcome", self.s.job(ident)["hold_reason"], multiline=True)
        d.submit(lambda v: self.s.hold(ident, v["reason"]))

    def decline_form(self, ident):
        v = self.s.decline_balance(ident)
        d = Form("Agreed return charges", self, f"Agreed charges: {rupees(v['agreed_charges'])}\nMoney retained: {rupees(v['money_retained'])}\nBalance due (negative means refund due): {rupees(v['balance_due'])}\nSaving issues the agreed charge. Actual refund payments are recorded separately in Customer accounts.")
        d.submit(lambda _: self.s.bill_decline(ident, "decline-" + str(ident)))

    def replacement_form(self, ident):
        d = Form("Centre replacement", self, "Record where the replacement was actually received. Resolve the original item separately with an owner-authorized movement.")
        d.select("item_id", "Original item", [(r["description"] + " · " + r["serial"], r["id"]) for r in self.db.rows("SELECT * FROM items WHERE job_id=?", (ident,))])
        d.text("description", "Replacement device / item")
        d.text("serial", "Replacement serial")
        from .domain import staff_custody
        d.layout.addRow("Actual holder", QLabel(self.s.user["name"] + " (you)"))
        d.values["location"] = lambda: staff_custody(self.s.user["id"])
        d.text("terms", "Warranty terms actually supplied", multiline=True)
        d.text("evidence", "Evidence / replacement reference", multiline=True)
        d.submit(lambda v: self.s.replacement(**v))

    def attach(self, job_id=None, sale_id=None):
        path, _ = QFileDialog.getOpenFileName(self, "Attach condition photo, purchase proof or evidence", "", "Evidence (*.pdf *.jpg *.jpeg *.png)")
        if path:
            self.run(lambda: self.docs.attach(path, Path(path).name, job_id, sale_id), "Saving managed attachment…")

    def open_attachment(self, relative):
        path = managed_path(self.db.root, relative)
        if not path.is_file():
            raise RuleError('This file is missing. Its history is retained. Recover the original photo through the photo history, or restore a verified backup.\n' + relative)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def document_form(self, ident):
        d = Form("Create printable PDF", self)
        d.select("kind", "Document", ["job_card", "intake_receipt", "dispatch_manifest", "return_manifest", "quotation", "bill", "payment_receipt", "refund_acknowledgment", "collection_receipt", "final_invoice", "warranty_summary"])
        d.text("source_id", "Quote / financial entry ID (when needed)")
        d.submit(lambda v: self.run(lambda: self.docs.generate(v["kind"], ident, int(v["source_id"]) if v["source_id"] else None), "Generating document…", callback=lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))))

    def custody(self):
        self.toolbar([("Record handover / receipt", self.move_form, True), ("Open selected job", lambda: self.job_detail(self.selected(grid)["job_id"]), False)])
        grid = self.table(self.db.rows("SELECT i.id,i.job_id,j.number,i.description,i.type,i.serial,h.location,h.quantity FROM holdings h JOIN items i ON h.item_id=i.id JOIN jobs j ON j.id=i.job_id WHERE h.quantity>0 AND j.stage NOT IN ('collected','closed') AND h.location!='customer' ORDER BY i.id DESC LIMIT 300"))

    def move_form(self, ident=None):
        d = Form("Dispatch, receive or collect", self, "Record an actual handover. Departure goes to transit; receipt acknowledgment goes to the destination. Partial quantities remain at their original holder.")
        rows = self.db.rows("SELECT i.*,h.location,h.quantity AS available,j.number FROM holdings h JOIN items i ON h.item_id=i.id JOIN jobs j ON j.id=i.job_id WHERE h.quantity>0 AND j.stage NOT IN ('collected','closed')" + (" AND i.job_id=?" if ident else "") + " ORDER BY i.id DESC LIMIT 500", (ident,) if ident else ())
        choice = d.select("item", "Item / current holder", [(f"{r['number']} · {r['description']} · {r['location']} · {r['available']} available", n) for n, r in enumerate(rows)])
        from .domain import staff_custody
        locations = [("Customer collection", "customer")]
        locations += [(r["name"] + " · " + r["role"].title(), staff_custody(r["id"]))
                      for r in self.db.rows("SELECT id,name,role FROM users WHERE active=1 ORDER BY name")]
        for kind in ("vendor", "centre", "technician", "transporter"):
            prefix = "transit" if kind == "transporter" else kind
            locations += [(kind.title() + ": " + r["name"], prefix + ":" + r["name"]) for r in self.s.masters(kind)]
        locations += [("In transit (record carrier below)", "transit:Unspecified"), ("Documented exception (owner)", "exception:Resolved")]
        d.select("destination", "Actual destination", locations)
        d.text("quantity", "Units handed over", "1")
        for key, label in (("counterparty", "Person / carrier receiving items"), ("reference", "Tracking / ticket / handover reference"), ("condition", "Condition at handover"), ("notes", "Notes / exception reason"), ("acknowledgment", "Acknowledgment (required for collection)")):
            d.text(key, label, multiline=key in ("notes", "acknowledgment"))
        op = uuid.uuid4().hex
        def save(v):
            selected = v.pop("item")
            if selected is None:
                raise RuleError("No available item selected.")
            r = rows[selected]
            v["quantity"] = int(v["quantity"])
            self.s.move(r["id"], source=r["location"], operation_id=op, **v)
        if d.submit(save):
            self.refresh()

    def party_photo(self, dialog, state, preview):
        from .camera import CameraDialog
        from .documents import Documents
        path, _ = QFileDialog.getOpenFileName(dialog, 'Choose a photo for this directory record', '',
                                              'Photos (*.jpg *.jpeg *.png)')
        if not path:
            camera = CameraDialog(lambda image, captured: (image.copy(), captured), dialog)
            if not camera.exec() or not camera.photo_id:
                return
            from PyQt6.QtCore import QBuffer, QIODevice
            import tempfile, os
            image = camera.photo_id[0]
            handle, path = tempfile.mkstemp(suffix='.jpg')
            os.close(handle)
            image.save(path, 'JPEG', 90)
        attachment = Documents(self.s).attach(path, 'Directory photo', kind='directory_photo')
        state['id'] = self.db.one('SELECT id FROM attachments ORDER BY id DESC LIMIT 1')['id']
        preview.setText('Photo saved: ' + attachment.name)

    def directories(self):
        kind = combo([(DIRECTORY_LABELS.get(k, k.replace('_', ' ').title()), k) for k in MASTER_KINDS])
        self.layout.addWidget(kind)
        self.toolbar([("+ Add option", lambda: self.master_form(kind.currentData()), True), ("Edit / deactivate", lambda: self.master_form(kind.currentData(), self.selected(grid)), False)])
        grid = self.table(self.db.rows("SELECT * FROM masters WHERE kind=? ORDER BY name", (kind.currentData(),)))
        kind.currentIndexChanged.connect(lambda: grid.fill(self.db.rows("SELECT * FROM masters WHERE kind=? ORDER BY name", (kind.currentData(),))))

    def master_form(self, kind, row=None):
        row = row or {}
        d = Form(DIRECTORY_LABELS.get(kind, kind.title()) + " directory", self)
        party = kind in self.s.PARTY_KINDS
        d.text("name", "Name *" if party else "Name", row.get("name"))
        d.text("contact", "Mobile *" if party else "Phone / contact", row.get("contact"))
        address_widgets = {}
        if party:
            try:
                profile=json.loads(row.get('details') or '{}')
                if not isinstance(profile,dict):profile={'notes':row.get('details','')}
            except ValueError:
                profile={'notes':row.get('details','')}
            from . import addresses
            d.text('address_line1', 'Address Line 1 *', row.get('address_line1') or profile.get('address',''))
            d.text('address_line2', 'Address Line 2', row.get('address_line2',''))
            d.text('pincode', 'PIN Code *', row.get('pincode',''))
            state = combo([(name, name) for name in addresses.STATES], row.get('state') or None)
            state.setEditable(True); state.setInsertPolicy(state.InsertPolicy.NoInsert)
            if row.get('state'): state.setCurrentText(row['state'])
            d.add('state', 'State *', state)
            district = combo([(name, name) for name in addresses.districts(self.db, row.get('state'))])
            district.setEditable(True); district.setInsertPolicy(district.InsertPolicy.NoInsert)
            if row.get('district'): district.setCurrentText(row['district'])
            d.add('district', 'District *', district)
            address_widgets = {'state': state, 'district': district}
            d.text('specialization', 'Specialization', row.get('specialization') or profile.get('specialization',''))
            for key,title in [('company','Company / brand / OEM'),('contact_person','Contact person'),('email','Email'),('notes','Notes')]:
                d.text(key,title,profile.get(key,''),multiline=key=='notes')
            photo_state = {'id': row.get('photo_id')}
            preview = QLabel('No photo' if not photo_state['id'] else 'Photo saved')
            d.layout.addRow('Photo (optional)', preview)
            d.layout.addRow('', button('Camera / Upload', lambda: self.safe(lambda: self.party_photo(d, photo_state, preview))))
        else:
            d.text("details", "Details", row.get("details"), multiline=True)
        d.check("active", "Available for new work", row.get("active", True))
        if kind == "accessory":
            d.add("category_id", "Suggest for category", MasterSelector(self.s, "category"))
        service_categories=[]
        if kind=='service':
            selected={r['category_id'] for r in self.db.rows('SELECT category_id FROM category_services WHERE service_id=?',(row.get('id'),))}
            d.layout.addRow(QLabel('Applicable categories (leave all unchecked for a general service)'))
            for category in self.s.masters('category'):
                check=QCheckBox(category['name']);check.setChecked(category['id'] in selected)
                d.layout.addRow('',check);service_categories.append((category['id'],check))
        def save(v):
            if party:
                for key, widget in address_widgets.items():
                    v[key] = widget.currentText().strip()
                v['photo_id'] = photo_state['id']
                v['details']=json.dumps({k:v.pop(k) for k in ('company','contact_person','email','notes')},ensure_ascii=False)
            if kind=='service':v['category_ids']=[ident for ident,check in service_categories if check.isChecked()]
            self.s.save_master(kind, **v, ident=row.get('id'))
        if d.submit(save):
            self.refresh()

    def quotes(self):
        self.toolbar([("+ Issue quotation", lambda: self.quote_form(), True), ("Record customer decision", lambda: self.decision_form(self.selected(grid)), False), ("Issue customer bill", lambda: (self.s.invoice(self.selected(grid)["id"], uuid.uuid4().hex), self.refresh()), False), ("Print quotation", lambda: self.run(lambda: self.docs.generate("quotation", self.selected(grid)["job_id"], self.selected(grid)["id"]), "Generating quotation…", callback=lambda p: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))), False)])
        grid = self.table(self.db.rows("SELECT q.*,j.number,c.name AS customer FROM quotes q JOIN jobs j ON j.id=q.job_id JOIN customers c ON c.id=j.customer_id ORDER BY q.id DESC LIMIT 300"), ["id", "number", "customer", "version", "state", "scope", "total", "valid_until"])

    def quote_form(self, ident=None, source=None):
        d = Form("Issue versioned quotation", self, "Parts from the Parts tab are included automatically. Enter labour, vendor service, transport and other charges as Description | amount in INR. Discounts use a negative amount. Changes require a new approved version.")
        if not ident:
            d.select("job_id", "Job", [(r["number"] + " · " + r["device"], r["id"]) for r in self.q.jobs()])
        source=source or {}
        d.text("scope", "Work scope", source.get('scope',''), multiline=True)
        old_lines=json.loads(source['lines']) if source else []
        lines_text='\n'.join(line['description']+' | '+amount_text(line['amount']) for line in old_lines if 'part_id' not in line)
        d.text("lines", "Itemized customer charges", lines_text if source else "Repair labour | 0.00", multiline=True)
        preview=QLabel();preview.setWordWrap(True);d.layout.addRow('Quotation review',preview)
        def update_preview():
            from .parts import Parts
            job=ident or d.fields['job_id'].currentData()
            if not job:return
            approved=self.db.one("SELECT q.* FROM quotes q JOIN decisions d ON d.quote_id=q.id WHERE q.job_id=? AND d.decision='approved' ORDER BY q.version DESC LIMIT 1",(job,))
            current=Parts(self.s).quote_lines(job)
            previous={line['part_id'] for line in json.loads(approved['lines']) if 'part_id' in line} if approved else set()
            added=[line for line in current if line['part_id'] not in previous]
            try:
                charges=sum(money(line.rsplit('|',1)[1].strip()) for line in d.fields['lines'].toPlainText().splitlines() if line.strip())
                total=charges+sum(line['amount'] for line in current)
                before=approved['total'] if approved else 0
                preview.setText(('Previous approved amount: '+rupees(before)+'\n' if approved else '')+'Additional / newly quoted parts: '+('; '.join(line['description']+' · '+rupees(line['amount']) for line in added) or 'None')+'\nRevised total: '+rupees(total)+('\nChange from previous approval: '+rupees(total-before) if approved else '')+'\nThis quotation requires the customer’s explicit decision.')
            except (ValueError,IndexError,RuleError):preview.setText('Enter each customer charge as Description | amount to preview the total.')
        d.fields['lines'].textChanged.connect(update_preview)
        if not ident:d.fields['job_id'].currentIndexChanged.connect(update_preview)
        update_preview()
        d.text("terms", "Terms / explicitly configured taxes", source.get('terms',"Paid work starts after this version is approved and the required deposit is received."), multiline=True)
        has_expiry=d.check('has_expiry','Set a quotation expiry date',bool(source.get('valid_until')))
        expiry=d.date("valid_until", "Valid through (end of day)",(date.fromisoformat(today())+timedelta(days=7)).isoformat())
        expiry.setMinimumDate(QDate.currentDate());expiry.setSpecialValueText('')
        expiry.setEnabled(has_expiry.isChecked());has_expiry.toggled.connect(expiry.setEnabled)
        expiry.setToolTip('Expiry is optional. Enable it to choose today or a future date.')
        def save(v):
            job = ident or v.pop("job_id")
            if not v.pop('has_expiry'):v['valid_until']=None
            else:v['valid_until']=expiry.date().toString('yyyy-MM-dd')
            lines = []
            for line in v.pop("lines").splitlines():
                if line.strip():
                    description, amount = line.rsplit("|", 1)
                    lines.append(dict(description=description.strip(), amount=money(amount.strip())))
            self.s.issue_quote(job, lines=lines, **v)
        if d.submit(save):
            self.refresh()

    def decision_form(self, row):
        row=self.s.quote_decision_details(row['id'])
        validity=('EXPIRED on ' if row['expired'] else 'Valid through ')+date.fromisoformat(row['valid_until']).strftime('%d %b %Y') if row['valid_until'] else 'No expiry date'
        description=f"Quotation #{row['id']} · version {row['version']} · {rupees(row['total'])}\n{validity}\nSending or reading a message is not approval. Record the authorized person's explicit decision."
        if row['expired']:description+='\nYou can record a decline. For approval, issue a revised quotation with a valid expiry date or no expiry.'
        d = Form("Record customer decision", self, description)
        d.resize(720, 760)
        # Show exactly what the customer is being asked to approve, split the way they
        # were quoted, and tie the decision to this quotation version.
        from .billing import Billing, CATEGORIES
        billing = Billing(self.s)
        summary = billing.summary(row['job_id'])
        grouped = billing.breakdown(billing.quote_lines(row))
        block = [f"REPAIR QUOTATION · version {row['version']}"]
        for key in CATEGORIES:
            lines = grouped['lines'][key]
            if not lines:
                continue
            block.append('')
            block.append(key.upper())
            block.append('-' * 40)
            for line in lines:
                block.append(f"{str(line.get('description',''))[:30]:<32}{rupees(line.get('amount',0)):>12}")
            block.append(f"{key.title() + ' total':<32}{rupees(grouped['totals'][key]):>12}")
        block += ['', '-' * 44,
                  f"{'TOTAL APPROVAL VALUE':<32}{rupees(row['total']):>12}",
                  '-' * 44,
                  f"{'Advance already paid':<32}{rupees(summary['advance']):>12}",
                  f"{'Other payments received':<32}{rupees(summary['other_payments']):>12}",
                  f"{'Expected balance':<32}{rupees(row['total'] - summary['received']):>12}",
                  '', 'Initial estimate given at intake: ' + rupees(summary['initial_estimate'])]
        breakdown = QLabel('\n'.join(block))
        breakdown.setTextFormat(Qt.TextFormat.PlainText)
        breakdown.setWordWrap(True)
        breakdown.setStyleSheet('font-family:Consolas,monospace;padding:12px;background:white;border:1px solid #dce5ee;border-radius:8px;')
        d.layout.addRow(breakdown)
        decision=d.select("decision", "Decision", ["declined"] if row['expired'] else ["approved", "declined"])
        decision.setEditable(False)
        d.text("person", "Customer / authorized representative")
        d.select("channel", "Received via", ["call", "in_person", "whatsapp", "email"])
        d.text("evidence", "Evidence / conversation reference", multiline=True)
        if row['expired']:
            def revise():
                d.reject()
                self.safe(lambda:self.quote_form(row['job_id'],source=row))
            d.layout.addRow(button('Issue revised quotation',revise))
        if d.submit(lambda v: self.s.decide_quote(row["id"], **v)):
            self.refresh()

    def accounts(self, account_type):
        self.toolbar([("+ Record entry", lambda: self.entry_form(account_type), True), ("Monthly ledger", lambda: self.ledger_form(account_type), False), ("Reverse selected entry", lambda: self.reverse_form(self.selected(grid)["id"]), False), ("+ Shared transport / expense", self.expense_form, False)])
        self.layout.addWidget(QLabel("Positive = amount owed to shop / vendor. Negative = credit or advance. Recording payments never transfers money."))
        if self.s.user["role"] == "owner":
            balances = Grid()
            balances.fill(self.q.account_balances(account_type))
            balances.setMaximumHeight(200)
            self.layout.addWidget(balances)
        grid = self.table(self.db.rows("SELECT e.id,e.account_id,e.job_id,e.posted,e.kind,e.amount,e.method,e.reference,e.notes FROM entries e WHERE e.account_type=? ORDER BY e.id DESC LIMIT 300", (account_type,)))

    def entry_form(self, account_type):
        d = Form("Record " + account_type + " account entry", self, "Amounts in INR. For adjustments, use a signed amount; reductions are negative. Entries cannot be edited after posting.")
        if account_type == "customer":
            d.add("account_id", "Customer", CustomerSelector(self.s))
        else:
            d.select("account_id", "Vendor / service centre", [(r["name"], r["id"]) for r in self.db.rows("SELECT * FROM masters WHERE kind IN ('vendor','centre') AND active=1 ORDER BY name")])
        kinds = ["receipt"] if self.s.user["role"] == "counter" else (["receipt", "refund", "credit", "opening", "adjustment"] if account_type == "customer" else ["charge", "payment", "credit", "refund", "opening", "adjustment"])
        d.select("kind", "Entry type", kinds)
        d.text("amount", "Amount (INR)")
        d.text("job_id", "Job ID (optional)")
        d.date("posted", "Posting date", today())
        method = MasterSelector(self.s, "payment_method")
        d.add("method_id", "Payment method", method)
        d.text("reference", "Receipt / bank / UPI / bill reference")
        d.text("notes", "Reason / notes / provenance", multiline=True)
        d.text("allocations", "Allocate payment: charge ID | INR per line", multiline=True)
        op = uuid.uuid4().hex
        def save(v):
            v.pop("method_id")
            v["method"] = method.text()
            allocations = []
            for line in v.pop("allocations").splitlines():
                if line.strip():
                    key, amount = line.split("|")
                    allocations.append((int(key.strip()), money(amount.strip())))
            v["job_id"] = int(v["job_id"]) if v["job_id"] else None
            v["amount"] = money(v["amount"])
            self.s.post(account_type, **v, operation_id=op, allocations=allocations)
        if d.submit(save):
            self.refresh()

    def reverse_form(self, entry_id):
        d = Form("Reverse financial entry", self, "The original stays in history. This posts an equal and opposite correcting entry.")
        d.text("reason", "Correction reason", multiline=True)
        if d.submit(lambda v: self.s.reverse(entry_id, v["reason"], uuid.uuid4().hex)):
            self.refresh()

    def ledger_form(self, account_type):
        d = Form("Monthly " + account_type + " ledger", self)
        if account_type == "customer":
            d.add("account_id", "Customer", CustomerSelector(self.s))
        else:
            d.select("account_id", "Vendor / centre", [(r["name"], r["id"]) for r in self.db.rows("SELECT * FROM masters WHERE kind IN ('vendor','centre') ORDER BY name")])
        d.date("start", "From posting date", today()[:8] + "01")
        d.date("end", "Through posting date", today())
        chosen = []
        if not d.submit(lambda v: chosen.append(v)):
            return
        v = chosen[0]
        data = self.q.ledger(account_type, **v)
        dialog = QDialog(self)
        dialog.setWindowTitle("Account statement")
        dialog.resize(1100, 720)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Opening {rupees(data['opening'])}     →     Closing {rupees(data['closing'])}     |     {v['start']} to {v['end']}"))
        g = Grid()
        g.fill(data["rows"])
        layout.addWidget(g)
        if account_type == "vendor":
            estimates = self.db.rows("SELECT a.reference,a.estimate,j.number,j.device,j.stage FROM assignments a JOIN jobs j ON j.id=a.job_id WHERE a.contact_id=? AND j.stage NOT IN ('collected','closed') ORDER BY a.id DESC LIMIT 100", (v["account_id"],))
            layout.addWidget(QLabel("Unconfirmed estimates / unfinished work — excluded from payable totals"))
            e = Grid()
            e.fill(estimates)
            e.setMaximumHeight(180)
            layout.addWidget(e)
        row = QHBoxLayout()
        row.addWidget(button("Export PDF / Excel / CSV", lambda: self.export_rows("Account statement", data["rows"])))
        def snapshot():
            formatted = [{"Date": r["posted"], "Job": r["number"] or "—", "Type": r["kind"], "Amount": rupees(r["amount"]), "Balance": rupees(r["running_balance"]), "Reference": r["reference"]} for r in data["rows"]]
            self.run(lambda: self.docs.snapshot(f"{account_type.title()} statement · account {v['account_id']} · {v['start']} to {v['end']}", [("Opening balance", rupees(data["opening"])), ("Posted entries", formatted), ("Closing balance", rupees(data["closing"]))]), "Preserving statement PDF…", callback=lambda p: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
        row.addWidget(button("Issue dated statement snapshot", snapshot))
        layout.addLayout(row)
        dialog.exec()

    def expense_form(self):
        d = Form("Shared transport / direct expense", self, "Allocate the actual total once across jobs. Customer selling charges belong in a quotation. Recording the transport record does not move items.")
        d.select("kind", "Expense type", ["outbound_transport", "return_transport", "part", "handling", "additional_vendor_charge"])
        d.text("amount", "Actual total cost (INR)")
        d.text("payer", "Paid / payable by")
        d.text("reference", "Receipt / tracking reference")
        d.text("allocations", "Job ID | allocated INR, one per line", multiline=True)
        d.text("included_entry_id", "Already included in vendor bill entry ID")
        for key, label in (("method", "Bus / train / courier / other method"), ("carrier", "Carrier / contact"), ("destination", "Destination"), ("departure", "Actual departure"), ("expected_arrival", "Expected arrival"), ("acknowledged", "Actual arrival acknowledgment"), ("items", "Item IDs / quantities on this leg"), ("reason", "Reason / evidence"), ("acceptance", "Additional charge acceptance status")):
            d.text(key, label)
        op = uuid.uuid4().hex
        def save(v):
            allocations = {}
            for line in v.pop("allocations").splitlines():
                job, amount = line.split("|")
                if int(job) in allocations:
                    raise RuleError("Each job must appear once.")
                allocations[int(job)] = money(amount.strip())
            payload = {k: v.pop(k) for k in ("method", "carrier", "destination", "departure", "expected_arrival", "acknowledged", "items", "reason", "acceptance")}
            v["amount"] = money(v["amount"])
            v["included_entry_id"] = int(v["included_entry_id"]) if v["included_entry_id"] else None
            self.s.expense(**v, allocations=allocations, payload=payload, operation_id=op)
        if d.submit(save):
            self.refresh()
