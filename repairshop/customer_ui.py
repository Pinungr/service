"""Photo-aware intake and consolidated customer views using existing Qt widgets."""
import json
import uuid
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QDate, QSize, QUrl
from PyQt6.QtGui import QPixmap, QIcon, QDesktopServices, QImageReader
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QFileDialog, QComboBox, QCheckBox, QDateEdit, QTextEdit, QLineEdit)
from .ui_widgets import Form, Grid, CustomerSelector, MasterSelector, button, combo, FlowLayout
from .customer_records import CustomerRecords
from .camera import CameraDialog
from .local_files import managed_path
from .domain import RuleError


def show_photo(label, db, photo, width=120):
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setMinimumSize(width, 90)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setPixmap(QPixmap())
    if not photo:
        label.setText('No photo yet')
        return
    path = managed_path(db.root, photo['path'])
    pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
    if pixmap.isNull():
        label.setText('Photo missing\nRecover from backup')
    else:
        label.setPixmap(pixmap.scaled(width, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    label.setToolTip(f"{photo.get('title', '')}\nCaptured: {photo.get('captured', '')}")


class IntakeForm(Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keep_draft = None

    def reject(self):
        try:
            if self.keep_draft:
                self.keep_draft()
            super().reject()
        except Exception as exc:
            self.error.setText('Draft could not be saved. Keep this window open and check the data folder. ' + str(exc))


class IntakePhotos:
    """Owns draft state but leaves existing intake business fields and validation intact."""
    def __init__(self, window, form, checks, source, sale, parent, draft=None):
        self.window, self.form, self.checks = window, form, checks
        self.records = CustomerRecords(window.s)
        self.draft_id = draft['id'] if draft else uuid.uuid4().hex
        self.sale, self.parent = sale, parent
        self.photo_id = None
        self.ready = False
        self.device_choice = combo([('New physical device', None)])
        form.fields['device_id'] = self.device_choice
        product_row = form.layout.getWidgetPosition(form.fields['category_id'])[0]
        form.layout.insertRow(product_row, 'Physical product', self.device_choice)
        self.warranty_hint=QLabel();self.warranty_hint.setWordWrap(True)
        form.layout.insertRow(product_row + 1,'Existing warranty',self.warranty_hint)
        self.device_choice.currentIndexChanged.connect(self.select_device)
        self.preview = QLabel()
        self.photo_label = QLabel('Required intake photo')
        self.photo_label.setWordWrap(True)
        self.role = combo([('Device owner', 'owner'), ('Submitting person', 'submitter')])
        customer_row = form.layout.getWidgetPosition(form.fields['customer_id'])[0]
        form.layout.insertRow(customer_row + 1, 'Person to photograph', self.role)
        controls = QWidget()
        line = QHBoxLayout(controls)
        line.addWidget(self.preview)
        column = QVBoxLayout()
        column.addWidget(self.photo_label)
        self.capture_button=button('Capture customer photo', lambda: window.safe(self.capture))
        column.addWidget(self.capture_button)
        self.upload_button=button('Upload customer photo', lambda: window.safe(self.upload))
        column.addWidget(self.upload_button)
        line.addLayout(column, 1)
        form.layout.insertRow(customer_row + 2, 'Customer photo', controls)
        form.fields['customer_id'].box.currentIndexChanged.connect(self.customer_changed)
        form.layout.addRow('', button('Save draft', lambda: window.safe(self.save_draft)))
        self.timer = QTimer(form)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.autosave)
        for widget in form.fields.values():
            signal = widget.box.currentIndexChanged if isinstance(widget, (MasterSelector, CustomerSelector)) else widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.toggled if isinstance(widget, QCheckBox) else widget.dateChanged if isinstance(widget, QDateEdit) else widget.textChanged
            signal.connect(self.changed)
        self.customer_changed()
        if source.get('device_id'):
            self.device_choice.setCurrentIndex(self.device_choice.findData(source['device_id']))
        if draft:
            self.restore(json.loads(draft['payload']))
        self.ready = True
        form.intake_support = self
        self.watch_accessories()
        form.keep_draft = self.save_draft
        form.finished.connect(lambda *_: self.timer.stop())

    def watch_accessories(self):
        for check in self.checks:
            if not getattr(check, 'draft_watched', False):
                check.draft_watched = True
                check.toggled.connect(self.changed)
                check.quantity_control.valueChanged.connect(self.changed)
                check.serial_control.textChanged.connect(self.changed)
                if hasattr(check, 'condition_control'):
                    check.condition_control.currentIndexChanged.connect(self.changed)
                    check.notes_control.textChanged.connect(self.changed)

    def changed(self, *_):
        if self.ready:
            self.timer.start(700)

    def autosave(self):
        try:
            self.save_draft()
        except Exception as exc:
            self.form.error.setText('Draft has not been saved: ' + str(exc))

    def payload(self):
        result = self.form.values()
        result.update(photo_id=self.photo_id, photo_role=self.role.currentData(), parent_id=self.parent,
            sale_id=self.sale['id'] if self.sale else None,
            accessories=[dict(description=c.text(), quantity=c.quantity_control.value(), serial=c.serial_control.text(),
                condition=c.condition_control.currentData() if hasattr(c, 'condition_control') else '',
                notes=c.notes_control.text() if hasattr(c, 'notes_control') else '',
                photo_id=getattr(c, 'photo_id', None), checked=c.isChecked()) for c in self.checks])
        if hasattr(self.form,'visit_intake'):
            result['visit_products']=self.form.visit_intake.products
        return result

    def save_draft(self):
        self.timer.stop()
        self.records.save_draft(self.draft_id, self.payload())
        self.photo_label.setToolTip('Intake draft saved on this computer. Resume it from Jobs → Intake drafts.')

    def restore(self, payload):
        wizard = getattr(self.form, 'wizard', None)
        if wizard: wizard.restoring = True
        try:
            self._restore_payload(payload)
        finally:
            if wizard: wizard.restoring = False
        if wizard: wizard.restore(payload)

    def _restore_payload(self, payload):
        # Load device defaults before restoring the draft's edited category/identity.
        first = ('customer_id', 'device_id', 'category_id')
        keys = list(first) + [k for k in self.form.fields if k not in first]
        for key in keys:
            if key not in payload:
                continue
            widget, value = self.form.fields[key], payload[key]
            if isinstance(widget, CustomerSelector):
                if value:
                    row = self.window.db.one('SELECT * FROM customers WHERE id=?', (value,))
                    if row:
                        widget.box.addItem(row['name'] + ' · ' + row['phone'], value)
                        widget.box.setCurrentIndex(widget.box.count()-1)
            elif isinstance(widget, MasterSelector):
                widget.box.setCurrentIndex(widget.box.findData(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QDateEdit):
                widget.setDate(QDate.fromString(value, 'yyyy-MM-dd') if value else widget.minimumDate())
            elif isinstance(widget, QTextEdit):
                widget.setPlainText(value or '')
            else:
                widget.setText(value or '')
        for saved in payload.get('accessories', []):
            for check in self.checks:
                if check.text() == saved['description']:
                    check.setChecked(saved['checked'])
                    check.quantity_control.setValue(saved['quantity'])
                    check.serial_control.setText(saved['serial'])
                    if hasattr(check, 'condition_control'):
                        index = check.condition_control.findData(saved.get('condition'))
                        if index >= 0:
                            check.condition_control.setCurrentIndex(index)
                        check.notes_control.setText(saved.get('notes', ''))
                        check.photo_id = saved.get('photo_id')
                        if check.photo_id:
                            check.photo_control.setText('Photo ✓')
        self.photo_id = payload.get('photo_id')
        self.role.setCurrentIndex(self.role.findData(payload.get('photo_role', 'owner')))
        self.update_photo()

    def customer_changed(self, *_):
        customer = self.form.fields['customer_id'].text()
        row = self.window.db.one('SELECT current_photo_id FROM customers WHERE id=?', (customer,))
        self.photo_id = row['current_photo_id'] if row else None
        self.device_choice.blockSignals(True)
        self.device_choice.clear()
        self.device_choice.addItem('New physical device (even if same model)', None)
        for device in self.window.db.rows('SELECT * FROM devices WHERE customer_id=? ORDER BY id', (customer,)):
            self.device_choice.addItem(f"{device['name']} · DEV-{device['id']:06d} · {device['serial'] or 'Serial unknown'}", device['id'])
        self.device_choice.blockSignals(False)
        self.warranty_hint.setText('Select an existing device to check its repair and part warranties.')
        self.update_photo()

    def select_device(self, *_):
        device = self.window.db.one('SELECT * FROM devices WHERE id=?', (self.device_choice.currentData(),))
        if device:
            self.form.fields['device'].setText(device['name'])
            self.form.fields['serial'].setText(device['serial'])
            for key in ('brand','model'):
                if key in self.form.fields:self.form.fields[key].setText(device[key])
            category = self.form.fields['category_id'].box
            category.setCurrentIndex(category.findData(device['category_id']))
            from .warranties import Warranties
            warranties=Warranties(self.window.s).rows(device['id'])
            active=[r for r in warranties if r['effective_status']=='ACTIVE']
            self.warranty_hint.setText('\n'.join(f"ACTIVE: {r['name']} · through {r['expiry']} · {r['original_job']}" for r in active)+'\nAfter saving this new intake, open Warranty to create a linked claim.' if active else 'No active repair or part warranty found. Warranty history remains available on the job.')
        else:
            self.warranty_hint.setText('New physical device · no previous repair warranty linked.')

    def update_photo(self):
        photo = self.window.db.one('SELECT * FROM attachments WHERE id=?', (self.photo_id,))
        show_photo(self.preview, self.window.db, photo)
        self.photo_label.setText(f"Saved {photo['person_role']} photo: {photo['person_name']}\nCaptured: {photo['captured']}" if photo else 'Capture and save the required photo before finalizing this intake.')
        selected=bool(self.form.fields['customer_id'].text())
        self.capture_button.setEnabled(selected and not self.window.db.readonly)
        if not selected:
            self.photo_label.setText('Select a saved customer or use New customer above. Then capture their photo.')

    def capture(self):
        self.save_draft()  # Durable before camera startup; cancel/failure leaves all fields intact.
        customer = self.form.fields['customer_id'].text()
        role = self.role.currentData()
        name = self.form.fields['submitter'].text().strip()
        if not customer:
            raise RuleError('Select the device owner before taking a photo.')
        if role == 'submitter' and not name:
            raise RuleError('Enter Submitted by before photographing the submitting person.')
        owner = self.window.db.one('SELECT name FROM customers WHERE id=?', (customer,))['name']
        dialog = CameraDialog(lambda image, captured: self.records.save_photo(image, customer, role, name, captured=captured), self.form,
            label=f"{role.title()}: {owner if role == 'owner' else name}")
        if dialog.exec():
            self.photo_id = dialog.photo_id
            self.update_photo()
            self.save_draft()

    def upload(self):
        customer = self.form.fields['customer_id'].text()
        role, name = self.role.currentData(), self.form.fields['submitter'].text().strip()
        if not customer: raise RuleError('Select the device owner before uploading a photo.')
        if role == 'submitter' and not name: raise RuleError('Enter Submitted by before uploading their photo.')
        path, _ = QFileDialog.getOpenFileName(self.form, 'Choose customer photo', '', 'Photos (*.jpg *.jpeg *.png *.bmp *.webp)')
        if not path: return
        source = Path(path)
        if not source.is_file() or source.stat().st_size > 50 * 1024**2:
            raise RuleError('Choose a local photo smaller than 50 MB.')
        reader = QImageReader(str(source)); reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 80_000_000:
            raise RuleError('Choose a supported photo with at most 80 million pixels.')
        self.photo_id = self.records.save_photo(reader.read(), customer, role, name)
        self.update_photo(); self.save_draft()


class DevicePhotos(QWidget):
    def __init__(self, window, device_id, job_id=None):
        super().__init__()
        self.window, self.device_id, self.job_id = window, device_id, job_id
        self.records = CustomerRecords(window.s)
        self.device = window.db.one('SELECT * FROM devices WHERE id=?', (device_id,))
        layout = QVBoxLayout(self)
        self.preview = QLabel()
        layout.addWidget(self.preview)
        row = FlowLayout()
        for title, action in [('Capture product photo', self.capture), ('Attach local product photo', self.attach), ('Recover missing photo', self.recover)]:
            control = button(title, lambda checked=False, action=action: window.safe(action))
            control.setEnabled(not window.db.readonly and window.s.user['role'] in ('owner', 'counter'))
            row.addWidget(control)
        layout.addLayout(row)
        self.grid = Grid()
        layout.addWidget(self.grid)
        self.grid.itemSelectionChanged.connect(self.selected)
        self.grid.cellDoubleClicked.connect(lambda *_: window.safe(lambda: window.open_attachment(window.selected(self.grid)['path'])))
        self.reload()

    def reload(self):
        self.grid.fill(self.window.db.rows("SELECT * FROM attachments WHERE device_id=? AND kind='product_photo' ORDER BY id DESC", (self.device_id,)), ['id', 'title', 'captured', 'job_id', 'path'])
        self.selected()

    def selected(self):
        index = self.grid.currentRow()
        show_photo(self.preview, self.window.db, self.grid.rows[index] if index >= 0 else None, 200)

    def capture(self):
        dialog = CameraDialog(lambda image, captured: self.records.save_photo(image, self.device['customer_id'], 'product', device_id=self.device_id, job_id=self.job_id, captured=captured), self,
            label=f"Product: {self.device['name']} · DEV-{self.device_id:06d}")
        if dialog.exec():
            self.reload()

    def attach(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a product photo', '', 'Images (*.jpg *.jpeg *.png *.bmp *.webp)')
        if path:
            self.window.run(lambda: self.records.import_product_photo(path, self.device['customer_id'], self.device_id, self.job_id), 'Saving product photo…', callback=lambda _: self.reload(), refresh=False)

    def recover(self):
        row = self.window.selected(self.grid)
        path, _ = QFileDialog.getOpenFileName(self, 'Select the original photo from an extracted backup')
        if path:
            self.window.run(lambda: self.records.recover_photo(row['id'], path), 'Recovering original photo…', callback=lambda _: self.reload(), refresh=False)


class CustomerOverview(QDialog):
    def __init__(self, window, customer_id):
        super().__init__(window)
        self.window, self.customer_id = window, customer_id
        self.records = CustomerRecords(window.s)
        self.setWindowTitle('Customer repair overview')
        self.resize(1320, 820)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.photo = QLabel()
        header.addWidget(self.photo)
        self.contact = QLabel('Loading customer…')
        self.contact.setTextFormat(Qt.TextFormat.PlainText)
        self.contact.setWordWrap(True)
        header.addWidget(self.contact, 1)
        layout.addLayout(header)
        actions = FlowLayout()
        for title, fn in [('New intake', lambda: self.new_intake()), ('Open customer folder / Retry folders', self.open_folder), ('Refresh', self.reload), ('Recover selected customer photo', self.recover)]:
            control = button(title, lambda checked=False, fn=fn: window.safe(fn))
            allowed = title == 'Refresh' or not window.db.readonly
            if title == 'Open customer folder / Retry folders':
                allowed = allowed and window.s.may('customer_export')
            control.setEnabled(allowed)
            actions.addWidget(control)
        layout.addLayout(actions)
        self.counts = QLabel()
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)
        self.readiness = QLabel()
        self.readiness.setStyleSheet('font-weight:600;color:#28704e;padding:8px')
        layout.addWidget(self.readiness)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.grids = {}
        tabs = [('visits', 'Visits'), ('outstanding', 'Outstanding work'), ('history', 'Historical work'),
                ('devices', 'All physical devices'), ('photos', 'Customer photo history')]
        if window.s.may('register_sale'):
            tabs.append(('sales', 'Products sold'))
        # Quotes are customer-facing, but remain scoped to the jobs this user may open.
        tabs.append(('quotes', 'Quotations'))
        if window.s.may('collect_payment'):
            tabs.append(('payments', 'Payments & refunds'))
        if window.s.may('messaging'):
            tabs.append(('messages', 'Communications'))
        for key, title in tabs:
            grid = Grid()
            self.grids[key] = grid
            self.tabs.addTab(grid, title)
        for key in ('outstanding', 'history'):
            self.grids[key].cellDoubleClicked.connect(lambda *_, key=key: window.safe(lambda: (window.job_detail(window.selected(self.grids[key])['id']), self.reload())))
        self.grids['visits'].cellDoubleClicked.connect(lambda *_: window.safe(lambda: (window.visit_summary([p['job_id'] for p in window.selected(self.grids['visits'])['product_list']]), self.reload())))
        self.grids['devices'].cellDoubleClicked.connect(lambda *_: window.safe(self.device_details))
        self.grids['photos'].cellDoubleClicked.connect(lambda *_: window.safe(lambda: window.open_attachment(window.selected(self.grids['photos'])['path'])))
        self.reload()

    def reload(self):
        self.render(self.records.overview(self.customer_id))

    def render(self, data):
        c = data['customer']
        self.contact.setText(f"{c['name']} · CUST-{c['id']:06d}\n{c['phone']}  {c['email']}\n{c['address']}")
        show_photo(self.photo, self.window.db, next((p for p in data['photos'] if p['id'] == c['current_photo_id']), None))
        labels = dict(outstanding='Outstanding products', under_repair_in_shop='Under repair in shop', vendors='With third-party repairers', service_centres='With service centres', in_transit='In transit', ready='Ready for collection', collected='Already collected')
        self.counts.setText('  ·  '.join(f"{labels[k]}: {v}" for k, v in data['counts'].items()) + '\nLocation and repair progress overlap; do not add these counts. Balances are independent of collection.')
        self.readiness.setText('All outstanding items ready for collection' if data['all_ready'] else 'Some outstanding items still need repair, return, checks or accessory handover.' if data['outstanding'] else 'No outstanding repair items.')
        self.grids['visits'].fill([dict(v, received=v['created'][:10], repairs='\n'.join(
            f"{p['product']} — {p['number']} — {p['status']}" for p in v['product_list']) or 'No products recorded')
            for v in data['visits']], ['number', 'received', 'status', 'products', 'repairs'])
        for key in ('outstanding', 'history'):
            grid = self.grids[key]
            grid.fill(data[key], ['photo', 'product', 'number', 'route_label', 'current_card', 'warranty_indicator', 'current_status', 'current_location', 'responsible', 'next_action', 'last_update', 'tentative_collection', 'balance', 'collection_status'])
            grid.setIconSize(QSize(52, 40))
            for index, row in enumerate(data[key]):
                item = grid.item(index, 0)
                item.setText('No photo')
                if row['thumbnail']:
                    path = managed_path(self.window.db.root, row['thumbnail'])
                    if path.is_file():
                        item.setIcon(QIcon(str(path)))
                        item.setText('')
                    else:
                        item.setText('Missing photo')
        self.grids['devices'].fill(data['devices'], ['id', 'name', 'brand', 'model', 'serial', 'created'])
        self.grids['photos'].fill(data['photos'], ['id', 'person_role', 'person_name', 'captured', 'path'])
        from .queries import Queries
        q = Queries(self.window.s)
        if 'sales' in self.grids:
            self.grids['sales'].fill(q.customer_sales(self.customer_id))
        self.grids['quotes'].fill(q.customer_quotes(self.customer_id))
        if 'payments' in self.grids:
            self.grids['payments'].fill(q.customer_payments(self.customer_id))
        if 'messages' in self.grids:
            self.grids['messages'].fill(q.customer_messages(self.customer_id))

    def open_folder(self):
        self.window.s.require_permission('customer_export')
        self.window.run(lambda: self.records.sync_customer(self.customer_id), 'Updating customer folders…', callback=lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))), refresh=False)

    def new_intake(self, device_id=None):
        self.window.intake(customer_id=self.customer_id, device_id=device_id)
        self.reload()

    def device_details(self):
        row = self.window.selected(self.grids['devices'])
        d = QDialog(self)
        d.setWindowTitle(f"{row['name']} · DEV-{row['id']:06d}")
        d.resize(1000, 650)
        layout = QVBoxLayout(d)
        layout.addWidget(DevicePhotos(self.window, row['id']))
        def edit():
            form = Form('Physical product details', d, 'These details identify the device. Earlier repair records and the permanent folder are preserved.')
            current = self.window.db.one('SELECT * FROM devices WHERE id=?', (row['id'],))
            for key, label in [('name', 'Product name'), ('brand', 'Brand'), ('model', 'Model'), ('serial', 'Serial number')]:
                form.text(key, label, current[key])
            form.submit(lambda values: self.records.update_device(row['id'], **values))
        edit_button = button('Edit product details', lambda: self.window.safe(edit))
        edit_button.setEnabled(not self.window.db.readonly)
        layout.addWidget(edit_button)
        control = button('New repair visit for this physical device', lambda: self.window.safe(lambda: self.new_intake(row['id'])))
        control.setEnabled(not self.window.db.readonly)
        layout.addWidget(control)
        d.exec()
        self.reload()

    def recover(self):
        if self.tabs.currentWidget() != self.grids['photos']:
            raise RuleError('Open Customer photo history and select the missing photo first.')
        row = self.window.selected(self.grids['photos'])
        path, _ = QFileDialog.getOpenFileName(self, 'Select the original photo from an extracted backup')
        if path:
            self.window.run(lambda: self.records.recover_photo(row['id'], path), 'Recovering original photo…', callback=lambda _: self.reload(), refresh=False)
