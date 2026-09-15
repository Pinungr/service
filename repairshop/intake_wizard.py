"""Four-page intake presentation over the existing form, draft and visit services."""
import json
from datetime import date

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QScrollArea, QStackedWidget, QLabel, QDialogButtonBox, QCheckBox,
    QRadioButton, QButtonGroup, QComboBox, QLineEdit)

from .domain import RuleError, money, rupees
from .ui_widgets import button, combo, FlowLayout
from .warranties import sale_warranty
from .intake_fields import INTAKE_STYLE


class IntakeWizard:
    EXTRA_FIELDS = ('warranty_status', 'warranty_expiry', 'warranty_provider',
                    'warranty_notes', 'identity_unknown', 'no_accessories')
    STEPS = ('Customer', 'Product', 'Repair', 'Confirm')

    def __init__(self, window, form, support, visit, checks, draft=None):
        self.w, self.form, self.support, self.visit, self.checks = window, form, support, visit, checks
        self.restoring = True
        self.step = 0
        self.inline_errors = {}
        self.rows = {}
        self.sale_rows = {}
        form.wizard = self
        form.setStyleSheet(INTAKE_STYLE)
        form.select('warranty_status', 'Reported warranty', [
            ('Warranty unknown', 'UNKNOWN'), ('Valid warranty', 'VALID'),
            ('Expired warranty', 'EXPIRED'), ('No warranty', 'NONE')], 'UNKNOWN')
        form.date('warranty_expiry', 'Warranty expiry (optional)')
        form.text('warranty_provider', 'Provider / seller (optional)')
        form.text('warranty_notes', 'Warranty notes (optional)', multiline=True)
        form.check('identity_unknown', 'Brand / model unavailable or not applicable')
        form.check('no_accessories', 'No accessories received')
        for key in self.EXTRA_FIELDS:
            widget = form.fields[key]
            signal = (widget.currentIndexChanged if isinstance(widget, QComboBox) else
                      widget.toggled if isinstance(widget, QCheckBox) else
                      widget.dateChanged if key == 'warranty_expiry' else widget.textChanged)
            signal.connect(support.changed)
        for key in ('transport_agreed', 'advance', 'deposit', 'assessment_agreed', 'initial_estimate'):
            field = form.fields[key]
            validator = QDoubleValidator(0, 999999999, 2, field)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            # Plain decimal input matches the existing money parser on every Windows locale.
            from PyQt6.QtCore import QLocale
            validator.setLocale(QLocale.c())
            field.setValidator(validator)
            field.setPlaceholderText('0.00')
            field.editingFinished.connect(lambda k=key: self.format_amount(k))
        form.fields['complaint'].setPlaceholderText('Describe the problem reported by the customer.')
        form.fields['damage'].setPlaceholderText('Scratches, dents, cracks, broken parts or liquid damage.')

        self.build_pages()
        self.sales = combo([('Select a purchased product…', None)])
        self.sales.setEditable(False)
        self.pages[0].insertRow(3, 'Purchased product', self.sales)
        self.sale_summary = QLabel(); self.sale_summary.setWordWrap(True)
        self.sale_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.pages[0].insertRow(4, self.sale_summary)
        self.warranty_badge = QLabel(); self.warranty_badge.setWordWrap(True)
        self.warranty_badge.setTextFormat(Qt.TextFormat.PlainText)
        self.pages[1].insertRow(0, self.warranty_badge)
        self.summary = QLabel(); self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setStyleSheet('padding:14px;background:white;border:1px solid #dce5ee;border-radius:8px;')
        self.pages[3].addRow('Review before receiving', self.summary)
        QWidget.layout(form).removeWidget(visit.box)
        self.pages[3].addRow(visit.box)
        visit.add.setText('+ Add product and receive another')
        self.review_visit = button('Review products in this visit', lambda: self.go(3))
        self.pages[0].addRow(self.review_visit)

        quick = FlowLayout()
        for text, days in [('Today', 0), ('Tomorrow', 1), ('+2 days', 2), ('+3 days', 3), ('+7 days', 7)]:
            quick.addWidget(button(text, lambda checked=False, n=days: form.fields['repair_due'].setDate(QDate.currentDate().addDays(n))))
        quick.addWidget(button('Clear date', lambda: form.fields['repair_due'].setDate(QDate(1900, 1, 1))))
        due_row = self.pages[2].getWidgetPosition(self.rows['repair_due'][1])[0]
        self.pages[2].insertRow(due_row + 1, quick)

        self.sales.currentIndexChanged.connect(self.select_sale)
        form.fields['customer_id'].box.currentIndexChanged.connect(self.customer_changed)
        form.fields['origin'].currentIndexChanged.connect(self.source_changed)
        form.fields['warranty_status'].currentIndexChanged.connect(self.warranty_changed)
        form.fields['identity_unknown'].toggled.connect(self.identity_changed)
        form.fields['no_accessories'].toggled.connect(self.no_accessories_changed)
        form.fields['category_id'].box.currentIndexChanged.connect(self.category_changed)
        # Programmatic device selection (existing-device and linked-return entry points).
        support.device_choice.currentIndexChanged.connect(self.device_changed)
        self.restoring = False
        self.load_sales(support.sale['id'] if support.sale else None)
        if draft:
            self.restore(json.loads(draft['payload']))
        else:
            self.source_changed()
        self.category_changed()
        self.go(0)

    def build_pages(self):
        form = self.form
        outer = QWidget.layout(form)
        old_scroll = form.findChild(QScrollArea)
        self.stack = QStackedWidget()
        self.pages = []
        self.stepper = QHBoxLayout()
        self.step_labels = []
        for index, name in enumerate(self.STEPS):
            label = QLabel(f'{index + 1}  {name}')
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(42)
            self.step_labels.append(label); self.stepper.addWidget(label)
        outer.insertLayout(2, self.stepper)
        outer.replaceWidget(old_scroll, self.stack)
        old_scroll.hide()
        for title in ('Customer & product source', 'Product details', 'Repair assessment', 'Charges & confirmation'):
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            body = QWidget(); layout = QFormLayout(body)
            layout.setContentsMargins(8, 12, 16, 12)
            layout.setHorizontalSpacing(20); layout.setVerticalSpacing(12)
            layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            heading = QLabel(title); heading.setObjectName('sectionTitle'); layout.addRow(heading)
            scroll.setWidget(body); self.stack.addWidget(scroll); self.pages.append(layout)

        groups = [
            ['customer_id', 'origin', 'submitter', 'relationship', 'update_contact_id'],
            ['device_id', 'category_id', 'device', 'brand', 'model', 'identity_unknown', 'serial',
             'warranty_status', 'warranty_expiry', 'warranty_provider', 'warranty_notes'],
            ['complaint', 'damage', 'customer_requirement', 'no_accessories', 'service_id', 'repair_due'],
            ['initial_estimate', 'transport_agreed', 'advance', 'policy', 'assessment_agreed', 'assessment_consent',
             'deposit', 'collection_due', 'intake_ref']]
        by_widget = {widget: key for key, widget in form.fields.items()}
        leftovers = []
        while form.layout.rowCount():
            row = form.layout.takeRow(0)
            field = row.fieldItem.widget() if row.fieldItem else None
            label = row.labelItem.widget() if row.labelItem else None
            if field is None:
                continue
            key = by_widget.get(field)
            if key:
                self.rows[key] = (label, field)
            elif field.objectName() == 'sectionTitle':
                field.deleteLater()
            else:
                leftovers.append((label, field))
        for index, keys in enumerate(groups):
            for key in keys:
                label, field = self.rows[key]
                wrapper = QWidget(); line = QVBoxLayout(wrapper); line.setContentsMargins(0, 0, 0, 0); line.setSpacing(3)
                line.addWidget(field)
                error = QLabel(); error.setWordWrap(True); error.setStyleSheet('color:#b42318;'); error.hide()
                line.addWidget(error); self.inline_errors[key] = error
                self.rows[key] = (label, wrapper)
                labels = {'customer_id': 'Device owner *', 'category_id': 'Product category *',
                          'device': 'Product description *', 'brand': 'Brand *', 'model': 'Model *',
                          'complaint': 'Reported issue *', 'damage': 'Visible condition / damage',
                          'advance': 'Advance received now (INR)', 'initial_estimate': 'Initial estimated cost (INR) *',
                          'customer_requirement': 'Additional customer requirement', 'transport_agreed': 'Transportation charge (INR)',
                          'origin': 'Where did this product come from?'}
                if key in labels: label.setText(labels[key])
                self.pages[index].addRow(label, wrapper)
        for label, field in leftovers:
            text = label.text() if label else ''
            if text in ('Person to photograph', 'Customer photo'):
                self.pages[0].addRow(label, field)
            elif text == 'Existing warranty':
                self.pages[1].addRow(label, field)
            elif text == 'Accessories actually received' or (hasattr(field, 'text') and field.text().startswith('+ Add new accessory')):
                self.pages[2].insertRow(4, label or '', field)
            else:
                if label: label.deleteLater()
                field.deleteLater()  # Old Save draft action is replaced in the persistent footer.

        # Keep the original source combo for draft/business bindings, present two explicit choices.
        form.fields['origin'].hide()
        source_wrapper = self.rows['origin'][1]
        self.source_buttons = QButtonGroup(form)
        for text, value in [('Purchased from our shop', 'shop'), ('External / other product', 'elsewhere')]:
            radio = QRadioButton(text); self.source_buttons.addButton(radio)
            radio.setStyleSheet('QRadioButton {padding:5px;spacing:8px;} QRadioButton::indicator {width:16px;height:16px;border:1px solid #8193a5;border-radius:8px;background:white;} QRadioButton::indicator:checked {border:4px solid #0f766e;background:#e0f2ef;}')
            radio.setProperty('origin', value)
            QWidget.layout(source_wrapper).insertWidget(0 if value == 'shop' else 1, radio)
            radio.toggled.connect(lambda checked, v=value: checked and form.fields['origin'].setCurrentIndex(form.fields['origin'].findData(v)))
        self.disclosure(0, 'Submitting person or additional authorized contact', ['submitter', 'relationship', 'update_contact_id'])
        self.disclosure(3, 'Additional charges, consent & collection details', ['policy', 'assessment_agreed', 'assessment_consent', 'deposit', 'collection_due', 'intake_ref'])
        self.back = form.buttons.addButton('Back', QDialogButtonBox.ButtonRole.ActionRole)
        self.back.clicked.connect(lambda: self.go(self.step - 1))
        self.next = form.buttons.addButton('Next', QDialogButtonBox.ButtonRole.ActionRole)
        self.next.setObjectName('primary'); self.next.clicked.connect(self.next_step)
        self.draft = form.buttons.addButton('Save as Draft', QDialogButtonBox.ButtonRole.ActionRole)
        self.draft.clicked.connect(self.save_draft)
        old_scroll.deleteLater()
        form.resize(940, 880)

    def disclosure(self, index, title, keys):
        toggle = QCheckBox(title)
        self.pages[index].addRow(toggle)
        for key in keys:
            label, field = self.rows[key]
            self.pages[index].removeWidget(label); self.pages[index].removeWidget(field)
            self.pages[index].addRow(label, field)
            label.hide(); field.hide()
        toggle.toggled.connect(lambda visible: [self.set_row(key, visible) for key in keys])

    def set_row(self, key, visible):
        for widget in self.rows[key]:
            if widget: widget.setVisible(visible)

    def format_amount(self, key):
        field = self.form.fields[key]
        try:
            value = money(field.text() or '0')
            if value < 0: raise RuleError('Amount cannot be negative.')
            field.setText(f'{value / 100:.2f}')
            self.inline_errors[key].hide()
        except (RuleError, ValueError) as exc:
            self.inline_errors[key].setText(str(exc)); self.inline_errors[key].show()
        if self.step == 3: self.update_summary()

    def fail(self, key, message):
        if key in self.inline_errors:
            self.inline_errors[key].setText(message); self.inline_errors[key].show()
        self.form.fields[key].setFocus()
        raise RuleError(message)

    def validate(self, step):
        values = self.form.values()
        if step == 0:
            if not values['customer_id']: self.fail('customer_id', 'Select or register the device owner.')
            if not self.support.photo_id: self.fail('customer_id', 'Capture or upload the required customer photo before continuing.')
            if values['origin'] == 'shop' and not self.support.sale:
                self.fail('origin', 'Select a product from this customer’s purchase history.')
        if step == 1:
            if not values['category_id']: self.fail('category_id', 'Choose a product category.')
            if not values['device']:
                description = ' '.join(filter(None, [values['brand'], values['model']]))
                if description: self.form.fields['device'].setText(description)
                else: self.fail('device', 'Enter a product description.')
            if not values['identity_unknown']:
                for key in ('brand', 'model'):
                    if not values[key]: self.fail(key, f'Enter the {key}, or mark brand / model unavailable.')
            if values['origin'] != 'shop' and values['warranty_status'] == 'VALID' and values['warranty_expiry'] and values['warranty_expiry'] < date.today().isoformat():
                self.fail('warranty_expiry', 'This expiry date has passed. Select Expired warranty or correct the date.')
        if step == 2:
            if not values['complaint']: self.fail('complaint', 'Describe the problem reported by the customer.')
            if not values['service_id']: self.fail('service_id', 'Choose a repair / service type.')
        if step == 3:
            for key in ('transport_agreed', 'advance', 'deposit', 'assessment_agreed', 'initial_estimate'):
                try:
                    if values[key] and not self.form.fields[key].hasAcceptableInput(): raise RuleError('Invalid amount.')
                    if money(values[key] or '0') < 0: raise RuleError('Amount cannot be negative.')
                except (RuleError, ValueError): self.fail(key, 'Enter an amount of zero or more, with at most two decimal places.')

    def validate_all(self):
        # An empty editor alongside a saved basket is not an extra product.
        if self.visit.products and not self.visit.entered(): return
        for step in range(4):
            try: self.validate(step)
            except RuleError:
                self.go(step); raise

    def next_step(self):
        self.form.error.hide()
        for error in self.inline_errors.values(): error.hide()
        try:
            self.validate(self.step)
            self.go(self.step + 1)
        except RuleError as exc:
            self.form.error.setText(str(exc)); self.form.error.show()

    def go(self, step):
        self.step = max(0, min(3, step))
        self.stack.setCurrentIndex(self.step)
        for index, label in enumerate(self.step_labels):
            label.setStyleSheet('background:#0f766e;color:white;border-radius:8px;font-weight:600;' if index == self.step else 'background:#e7edf5;color:#39516a;border-radius:8px;')
        self.back.setVisible(self.step > 0); self.next.setVisible(self.step < 3)
        save = self.form.buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setVisible(self.step == 3)
        save.setDefault(self.step == 3)
        self.next.setDefault(self.step < 3)
        save.setText('Create Repair Job' if len(self.visit.products) < 2 else 'Create Repair Jobs')
        self.review_visit.setVisible(bool(self.visit.products))
        if self.step == 3: self.update_summary()
        self.stack.currentWidget().verticalScrollBar().setValue(0)

    def save_draft(self):
        try:
            self.support.save_draft()
            self.form.error.setText('Draft saved on this computer. You can resume it from Intake drafts.')
            self.form.error.show()
        except Exception as exc:
            self.form.error.setText('Could not save draft: ' + str(exc)); self.form.error.show()

    def load_sales(self, selected=None):
        owner = self.form.fields['customer_id'].text()
        self.sale_rows = {r['id']: r for r in self.w.db.rows(
            'SELECT * FROM sales WHERE customer_id=? ORDER BY sale_date DESC,id DESC', (owner,))}
        self.sales.blockSignals(True); self.sales.clear()
        self.sales.addItem('Select a purchased product…' if self.sale_rows else 'No purchases recorded for this customer', None)
        for row in self.sale_rows.values():
            status = sale_warranty(row)['status']
            self.sales.addItem(f"{row['device']} · {row['serial'] or 'Serial unknown'} · {row['sale_date'] or 'Date not recorded'} · {status.title()}", row['id'])
        self.sales.setCurrentIndex(max(0, self.sales.findData(selected)))
        self.sales.blockSignals(False)

    def customer_changed(self):
        if self.restoring: return
        had_sale = bool(self.support.sale)
        self.support.sale = None
        self.support.parent = None
        self.load_sales()
        if had_sale: self.clear_sale_fields()
        self.source_changed()

    def clear_sale_fields(self):
        for key in ('device', 'brand', 'model', 'serial'):
            self.form.fields[key].clear()
        self.form.fields['category_id'].box.setCurrentIndex(0)
        self.support.device_choice.setCurrentIndex(0)
        self.form.fields['identity_unknown'].setChecked(False)

    def source_changed(self):
        if self.restoring: return
        shop = self.form.fields['origin'].currentData() == 'shop'
        for radio in self.source_buttons.buttons():
            radio.blockSignals(True); radio.setChecked(radio.property('origin') == ('shop' if shop else 'elsewhere')); radio.blockSignals(False)
        self.sales.setVisible(shop)
        self.pages[0].labelForField(self.sales).setVisible(shop)
        self.sale_summary.setVisible(shop)
        self.set_row('device_id', not shop)
        if shop:
            self.select_sale()
        elif self.support.sale:
            self.support.sale = None
            self.sales.setCurrentIndex(0)
            self.clear_sale_fields()
        self.warranty_changed()

    def select_sale(self):
        if self.restoring or self.form.fields['origin'].currentData() != 'shop': return
        previous = self.support.sale
        sale = self.sale_rows.get(self.sales.currentData())
        self.support.sale = sale
        if not sale:
            if previous: self.clear_sale_fields()
            self.sale_summary.setText('Select a purchase to load product details and warranty dates.' if self.sale_rows else 'No sales history for this customer. Register the sale in Products sold, or choose External / other product.')
            self.warranty_changed(); return
        self.support.parent = None
        self.restoring = True
        self.support.device_choice.setCurrentIndex(self.support.device_choice.findData(sale['device_id']))
        device = self.w.db.one('SELECT * FROM devices WHERE id=?', (sale['device_id'],)) or {}
        for key in ('brand', 'model'): self.form.fields[key].setText(device.get(key, ''))
        for key in ('device', 'serial'): self.form.fields[key].setText(sale.get(key, ''))
        category = self.form.fields['category_id'].box
        category.setCurrentIndex(category.findData(sale['category_id']))
        self.form.fields['identity_unknown'].setChecked(not device.get('brand') or not device.get('model'))
        self.restoring = False
        warranty = sale_warranty(sale)
        self.sale_summary.setText(f"{sale['device']}\nPurchased: {sale['sale_date'] or 'Not recorded'}  ·  Serial: {sale['serial'] or 'Not recorded'}\n{self.warranty_text(warranty)}")
        self.warranty_changed(); self.support.changed()

    def device_changed(self):
        if self.restoring: return
        # For external previously repaired devices, preserve their existing identity and warranty history.
        if self.support.device_choice.currentData():
            self.form.fields['identity_unknown'].setChecked(not self.form.fields['brand'].text() or not self.form.fields['model'].text())

    @staticmethod
    def warranty_text(warranty):
        names = {'VALID': 'Warranty Active', 'EXPIRED': 'Warranty Expired', 'NONE': 'No warranty', 'UNKNOWN': 'Warranty Unknown', 'NOT_STARTED': 'Warranty not started'}
        text = names.get(warranty['status'], 'Warranty Unknown')
        if warranty.get('expiry'): text += f" · Expiry: {warranty['expiry']}"
        if warranty.get('duration_days') is not None: text += f" · {warranty['duration_days']} days"
        return text

    def warranty_changed(self):
        shop = self.form.fields['origin'].currentData() == 'shop'
        status = self.form.fields['warranty_status'].currentData()
        self.set_row('warranty_status', not shop)
        for key in ('warranty_expiry', 'warranty_provider', 'warranty_notes'): self.set_row(key, not shop and status == 'VALID')
        warranty = sale_warranty(self.support.sale) if shop and self.support.sale else {'status': 'UNKNOWN' if shop else status}
        self.warranty_badge.setText(self.warranty_text(warranty) + ('\nSales dates checked automatically; coverage is verified during assessment.' if shop else '\nReported at intake. Warranty coverage still needs verification.'))
        self.warranty_badge.setStyleSheet('padding:12px;border-radius:8px;background:' + ('#dcfce7;color:#166534;' if warranty['status']=='VALID' else '#fff3dd;color:#805414;'))
        self.suggest_service(warranty['status'])

    def suggest_service(self, status):
        if self.restoring or status != 'VALID': return
        box = self.form.fields['service_id'].box
        if box.currentData(): return  # Preserve an explicit technician choice.
        recommended = next((r['id'] for r in self.w.s.services_for_category(self.form.fields['category_id'].value()) if r['name'].casefold() == 'warranty assessment'), None)
        index = box.findData(recommended) if recommended else -1
        if index >= 0: box.setCurrentIndex(index)

    def category_changed(self):
        for check in self.checks:
            if not getattr(check, 'wizard_watched', False):
                check.wizard_watched = True
                check.toggled.connect(lambda selected: selected and self.form.fields['no_accessories'].setChecked(False))
        self.warranty_changed()

    def no_accessories_changed(self, checked):
        if checked:
            for accessory in self.checks: accessory.setChecked(False)

    def identity_changed(self, checked):
        for key in ('brand', 'model'):
            self.rows[key][0].setText(key.title() + (' (if known)' if checked else ' *'))

    def restore(self, payload):
        self.restoring = True
        for key in self.EXTRA_FIELDS:
            if key not in payload: continue
            field = self.form.fields[key]; value = payload[key]
            if isinstance(field, QCheckBox): field.setChecked(bool(value))
            elif isinstance(field, QComboBox): field.setCurrentIndex(field.findData(value))
            elif key == 'warranty_expiry': field.setDate(QDate.fromString(value, 'yyyy-MM-dd') if value else QDate(1900, 1, 1))
            elif key == 'warranty_notes': field.setPlainText(value or '')
            else: field.setText(value or '')
        self.load_sales(payload.get('sale_id'))
        self.support.sale = self.sale_rows.get(payload.get('sale_id'))
        self.restoring = False
        # Sync visibility without overwriting the editor restored from its draft.
        shop = self.form.fields['origin'].currentData() == 'shop'
        for radio in self.source_buttons.buttons():
            radio.blockSignals(True); radio.setChecked(radio.property('origin') == ('shop' if shop else 'elsewhere')); radio.blockSignals(False)
        self.sales.setVisible(shop); self.pages[0].labelForField(self.sales).setVisible(shop); self.sale_summary.setVisible(shop)
        self.set_row('device_id', not shop)
        if self.support.sale:
            self.sale_summary.setText(self.support.sale['device'] + '\n' + self.warranty_text(sale_warranty(self.support.sale)))
        self.warranty_changed()

    def reset_product(self):
        self.restoring = True
        for key in ('warranty_provider', 'warranty_notes'): self.form.fields[key].clear()
        self.form.fields['warranty_status'].setCurrentIndex(0)
        self.form.fields['warranty_expiry'].setDate(QDate(1900, 1, 1))
        self.form.fields['identity_unknown'].setChecked(False)
        self.form.fields['no_accessories'].setChecked(False)
        self.sales.setCurrentIndex(0)
        self.restoring = False
        self.source_changed(); self.go(0)

    def update_summary(self):
        products = list(self.visit.products)
        if self.visit.entered() or not products: products.append(self.support.payload())
        customer = self.w.db.one('SELECT * FROM customers WHERE id=?', (self.form.fields['customer_id'].text(),)) or {}
        lines = [f"CUSTOMER  ·  {customer.get('name', 'Select customer')}  ·  {customer.get('phone', '')}"]
        for index, product in enumerate(products, 1):
            category = self.w.db.one('SELECT name FROM masters WHERE id=?', (product.get('category_id'),)) or {}
            service = self.w.db.one('SELECT name FROM masters WHERE id=?', (product.get('service_id'),)) or {}
            sale = self.w.db.one('SELECT * FROM sales WHERE id=?', (product.get('sale_id'),))
            warranty = sale_warranty(sale) if sale else {'status': product.get('warranty_status', 'UNKNOWN'), 'expiry': product.get('warranty_expiry') if product.get('warranty_status') == 'VALID' else None}
            accessories = ', '.join(f"{a['description']} × {a['quantity']}" + (f" ({a['serial']})" if a.get('serial') else '') for a in product.get('accessories', []) if a.get('checked'))
            lines.extend(['', f"PRODUCT {index}  ·  {category.get('name', 'Category not selected')} · {product.get('device', '')}",
                          f"Brand / model: {product.get('brand') or 'Not recorded'} / {product.get('model') or 'Not recorded'} · Serial: {product.get('serial') or 'Not recorded'}",
                          self.warranty_text(warranty), f"Issue: {product.get('complaint', '')}",
                          f"Condition: {product.get('damage') or 'Not recorded'}", f"Accessories: {accessories or 'None received'}",
                          f"Service: {service.get('name', 'Not selected')} · Due: {product.get('repair_due') or 'Not set'}"])
            if product.get('customer_requirement'):
                lines.append('Additional customer requirement: ' + str(product['customer_requirement']))
            for key, title in [('initial_estimate', 'Initial estimated cost'), ('transport_agreed', 'Transport'), ('advance', 'Advance received now'), ('deposit', 'Required deposit'), ('assessment_agreed', 'Assessment charge')]:
                try: amount = rupees(money(product.get(key) or '0'))
                except (RuleError, ValueError): amount = 'Correct this amount'
                lines.append(f'{title}: {amount}')
        # The visit total is always calculated from the product estimates; it is never typed.
        totals = {}
        for key in ('initial_estimate', 'advance'):
            total = 0
            for product in products:
                try: total += money(product.get(key) or '0')
                except (RuleError, ValueError): pass
            totals[key] = total
        lines += ['', '-' * 46,
                  f"TOTAL INITIAL ESTIMATE  ·  {rupees(totals['initial_estimate'])}",
                  f"ADVANCE RECEIVED        ·  {rupees(totals['advance'])}",
                  f"ESTIMATED BALANCE       ·  {rupees(totals['initial_estimate'] - totals['advance'])}",
                  '-' * 46,
                  'The initial estimate is the figure given at collection. It is not the final repair',
                  'quotation: chargeable repair is quoted after diagnosis and needs recorded approval.']
        self.summary.setText('\n'.join(lines))
        self.estimated_total = totals['initial_estimate']
