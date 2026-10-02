"""Contacts & Services: configure once, select many times.

`ContactSelector` is the one picker for reusable business contacts inside a workflow: it
searches as you type, lists the contacts relevant to the product first, shows a read-only
summary of the selected contact and creates a missing one without leaving the repair.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QTabWidget,
                             QMessageBox, QListWidget, QListWidgetItem, QCompleter, QDialogButtonBox, QSpinBox)
from .ui_widgets import MasterSelector, Form, Grid, button, combo, FlowLayout, Cancelled
from .contacts import (Contacts, DuplicateContact, CONTACT_KINDS, SETUP_KINDS, PARTNER_KINDS, PROFILE_FIELDS,
                       label as kind_label, summary)
from .domain import rupees

RECOMMENDED = 'Recommended for this product'
OTHERS = 'Other '


def summary_card():
    card = QLabel()
    card.setObjectName('contactSummary')
    card.setTextFormat(Qt.TextFormat.PlainText)
    card.setWordWrap(True)
    card.setStyleSheet('QLabel#contactSummary{background:#f8fafc;border:1px solid #dce5ee;border-radius:8px;'
                       'padding:9px 12px;color:#102a43;}')
    card.hide()
    return card


class ContactSelector(MasterSelector):
    """Search / select one active contact, with "+ Add new" and a summary of the selection.

    It is a `MasterSelector`, so every form that already reads a selector's value keeps
    working. Recommended contacts are listed first; nothing relevant is ever hidden.
    """

    def __init__(self, service, kind, job_id=None, selected=None, on_change=None):
        QWidget.__init__(self)
        self.s, self.kind, self.category, self.job_id = service, kind, None, job_id
        self.on_change = on_change
        self.options = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.box = combo([], editable=True)
        self.box.lineEdit().setPlaceholderText('Search ' + kind_label(kind).lower() + ' by name, place or phone…')
        self.box.setAccessibleName(kind_label(kind))
        row.addWidget(self.box, 1)
        self.add_button = button('+ Add new', lambda: self.add())
        self.add_button.setEnabled(not service.db.readonly and service.may('directories'))
        row.addWidget(self.add_button)
        outer.addLayout(row)
        self.card = summary_card()
        outer.addWidget(self.card)
        self.box.currentIndexChanged.connect(self._changed)
        self.reload(selected)

    def reload(self, selected=None):
        self.box.blockSignals(True)
        self.box.clear()
        self.box.addItem('Select ' + kind_label(self.kind).lower() + '…', None)
        rows = Contacts(self.s).options(self.kind, self.job_id)
        self.options = {r['id']: r for r in rows}
        recommended = [r for r in rows if r['recommended']]
        others = [r for r in rows if not r['recommended']]
        model = self.box.model()
        def header(text):
            self.box.addItem(text, None)
            item = model.item(self.box.count() - 1) if isinstance(model, QStandardItemModel) else None
            if item is not None:
                item.setEnabled(False)
        if recommended:
            header('— ' + RECOMMENDED + ' —')
        for group in (recommended, others):
            if group is others and recommended and others:
                header('— ' + OTHERS + kind_label(self.kind).lower() + 's —')
            for r in group:
                text = r['name'] + (' — ' + r['secondary'] if r['secondary'] else '')
                self.box.addItem(text, r['id'])
                self.box.setItemData(self.box.count() - 1, r['summary'], Qt.ItemDataRole.ToolTipRole)
        self.box.blockSignals(False)
        index = self.box.findData(selected) if selected else 0
        self.box.setCurrentIndex(index if index >= 0 else 0)
        self._changed()

    def value(self):
        ident = self.box.currentData()
        return ident if ident in self.options and self.box.findText(self.box.currentText()) >= 0 else None

    def text(self):
        ident = self.value()
        return self.options[ident]['name'] if ident else ''

    def selected_option(self):
        return self.options.get(self.value())

    def _changed(self, *_):
        option = self.selected_option()
        if option:
            text = option['summary']
            if option['recommended'] and option['reasons']:
                text += '\nRecommended: works on ' + ', '.join(dict.fromkeys(option['reasons']))
            self.card.setText(text)
        self.card.setVisible(bool(option))
        if self.on_change:
            self.on_change(option)

    def add(self):
        # A name typed into the search that matched nothing becomes the new contact's name.
        typed = self.box.currentText().strip()
        ident = quick_create(self.s, self.kind, self, job_id=self.job_id,
                             initial=typed if self.box.findText(typed) < 0 else '')
        if ident:
            self.reload(ident)
        return ident


def choose_duplicate(parent, matches, can_create=True):
    """Possible existing contact: use it, or knowingly create another. Returns 'use', 'create' or None."""
    first = matches[0]
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle('Possible existing contact')
    lines = [m['name'] + (' · ' + m['secondary'] if m.get('secondary') else '')
             + ('' if m['active'] else ' · inactive') + '  (' + ', '.join(m['reasons']) + ')' for m in matches[:4]]
    box.setText('This looks like a contact you already have:\n\n' + '\n'.join(lines))
    use = box.addButton('Use existing', QMessageBox.ButtonRole.AcceptRole)
    create = box.addButton('Create anyway', QMessageBox.ButtonRole.DestructiveRole) if can_create and not first['exact'] else None
    box.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(use)
    box.exec()
    clicked = box.clickedButton()
    return 'use' if clicked is use else 'create' if create is not None and clicked is create else None


#: The few details asked for when a contact is created from inside a repair.
QUICK_FIELDS = {
    'vendor': [('specialization', 'Specialization (e.g. Laptop, motherboard, chip-level)')],
    'centre': [('brands', 'Brand / OEM (e.g. Samsung)'), ('city', 'City')],
    'supplier': [('specialization', 'What they supply')],
    'transporter': [('route_from', 'Route from'), ('route_to', 'Route to'), ('vehicle_number', 'Usual bus number')],
}


def quick_create(service, kind, parent=None, job_id=None, initial=''):
    """Lightweight add-and-select dialog. Returns the new (or reused) contact id, or None."""
    form = Form('Add ' + kind_label(kind), parent,
                'Saved once in Contacts & Services and selected for this repair. '
                'Complete the address and other details later from Contacts & Services.')
    form.resize(540, 470)
    form.text('name', 'Name *', initial)
    form.text('mobile', 'Mobile *')
    for key, title in QUICK_FIELDS[kind]:
        form.text(key, title)
    form.buttons.button(QDialogButtonBox.StandardButton.Save).setText('Save && Select')
    contacts, result = Contacts(service), {}

    def save(values):
        name, mobile = values.pop('name'), values.pop('mobile')
        extra = {k: v for k, v in values.items() if v}
        try:
            result['id'] = contacts.quick_create(kind, name, mobile, job_id=job_id, **extra)
        except DuplicateContact as found:
            choice = choose_duplicate(form, found.matches)
            if choice == 'use':
                match = found.matches[0]
                if not match['active']:
                    contacts.set_active(match['id'], True)
                result['id'] = match['id']
            elif choice == 'create':
                result['id'] = contacts.quick_create(kind, name, mobile, allow_duplicate=True, job_id=job_id, **extra)
            else:
                raise Cancelled()
    form.submit(save)
    return result.get('id')


class ContactForm:
    """The full record, completed whenever convenient from Contacts & Services."""

    def __init__(self, window, kind, row=None):
        self.window, self.kind, self.row = window, kind, dict(row or {})
        self.s = window.s

    def open(self):
        kind, row, s = self.kind, self.row, self.s
        record = Contacts(s).get(row['id']) if row.get('id') else {}
        record = record or {}
        d = Form(('Edit ' if record else 'Add ') + kind_label(kind), self.window,
                 'Only name and mobile are required. Everything here is shown to staff when they select this contact.')
        d.resize(700, 760)
        d.text('name', 'Name *', record.get('name', ''))
        d.text('mobile', 'Mobile *', record.get('contact', ''))
        d.text('alternate', 'Alternate mobile', record.get('alternate', ''))
        d.text('contact_person', 'Contact person', record.get('contact_person', ''))
        if 'email' in PROFILE_FIELDS[kind]:
            d.text('email', 'Email', record.get('email', ''))
        widgets = {}
        if kind == 'transporter':
            d.section('Route')
            for key, title in (('route_from', 'From'), ('route_to', 'To'), ('pickup_point', 'Pickup point'),
                               ('drop_point', 'Drop point'), ('vehicle_number', 'Usual bus number')):
                d.text(key, title, record.get(key, ''))
        else:
            from . import addresses
            d.section('Address')
            d.text('address_line1', 'Address line 1', record.get('address_line1', ''))
            d.text('address_line2', 'Address line 2', record.get('address_line2', ''))
            d.text('city', 'City', record.get('city', ''))
            state = combo([(name, name) for name in addresses.STATES], record.get('state') or None, editable=True)
            state.setCurrentText(record.get('state', ''))
            d.add('state', 'State', state)
            district = combo([(name, name) for name in addresses.districts(s.db, record.get('state'))], editable=True)
            district.setCurrentText(record.get('district', ''))
            d.add('district', 'District', district)
            d.text('pincode', 'PIN code', record.get('pincode', ''))
            widgets.update(state=state, district=district)
            d.section('Work')
            d.text('specialization', 'Specialization' if kind != 'supplier' else 'What they supply', record.get('specialization', ''))
        checks = {}
        if kind in PARTNER_KINDS:
            chosen = set(record.get('supports', []))
            for support, title in (('category', 'Product categories'), ('service', 'Repairs / services')):
                items = s.masters(support)
                if not items:
                    continue
                listing = QListWidget()
                listing.setMaximumHeight(120)
                for item in items:
                    entry = QListWidgetItem(item['name'])
                    entry.setData(Qt.ItemDataRole.UserRole, item['id'])
                    entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    entry.setCheckState(Qt.CheckState.Checked if item['id'] in chosen else Qt.CheckState.Unchecked)
                    listing.addItem(entry)
                d.layout.addRow(title, listing)
                checks[support] = listing
            brands = [m['name'] for m in s.masters('brand') if m['id'] in chosen]
            brand_field = d.text('brands', 'Brands (comma separated)', ', '.join(brands))
            completer = QCompleter([m['name'] for m in s.masters('brand')], brand_field)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            brand_field.setCompleter(completer)
        if kind == 'centre':
            d.check('warranty_service', 'Accepts warranty jobs', record.get('warranty_service'))
            d.check('pickup', 'Offers pickup', record.get('pickup'))
            days = QSpinBox()
            days.setRange(0, 365)
            days.setValue(int(record.get('turnaround_days') or 0))
            days.setSuffix(' days')
            d.add('turnaround_days', 'Usual turnaround', days)
            widgets['turnaround_days'] = days
        d.text('notes', 'Notes', record.get('notes', ''), multiline=True)
        photo = {'id': record.get('photo_id')}
        if kind != 'transporter':
            preview = QLabel('No photo' if not photo['id'] else 'Photo saved')
            d.layout.addRow('Photo (optional)', preview)
            d.layout.addRow('', button('Camera / Upload', lambda: self.window.safe(
                lambda: self.window.party_photo(d, photo, preview))))
        d.check('active', 'Available for new work', record.get('active', True))
        contacts = Contacts(s)

        def save(v):
            for key, widget in widgets.items():
                v[key] = widget.value() if key == 'turnaround_days' else widget.currentText().strip()
            if checks:
                v['supports'] = [listing.item(i).data(Qt.ItemDataRole.UserRole)
                                 for listing in checks.values() for i in range(listing.count())
                                 if listing.item(i).checkState() == Qt.CheckState.Checked]
            if photo['id'] and photo['id'] != record.get('photo_id'):
                v['photo_id'] = photo['id']
            if not record:
                found = contacts.duplicates(kind, v.get('name', ''), v.get('mobile', ''), v.get('city', ''))
                if found:
                    choice = choose_duplicate(d, found)
                    if choice == 'use':
                        self.row = found[0]
                        return
                    if choice != 'create':
                        raise Cancelled()
            self.saved = contacts.save(kind, v, ident=record.get('id'))
        return d.submit(save)


class ContactList(QWidget):
    """One kind of contact: search, add, edit, deactivate and a read-only summary."""

    COLUMNS = {
        'transporter': ['name', 'works_on', 'pickup_point', 'drop_point', 'contact_person', 'mobile', 'vehicle_number', 'status'],
    }
    DEFAULT = ['name', 'mobile', 'contact_person', 'location', 'works_on', 'status']

    def __init__(self, window, kind):
        super().__init__()
        self.window, self.kind, self.s = window, kind, window.s
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search by name, mobile, person, place or work…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        top.addWidget(self.search, 1)
        self.inactive = QCheckBox('Show inactive')
        self.inactive.toggled.connect(self.reload)
        top.addWidget(self.inactive)
        layout.addLayout(top)
        bar = FlowLayout()
        writable = not window.db.readonly and self.s.may('directories')
        for text, handler, primary in (('+ Add ' + kind_label(kind), self.add, True), ('Edit', self.edit, False),
                                       ('Deactivate / activate', self.toggle, False)):
            b = button(text, lambda checked=False, h=handler: self.window.safe(h), primary)
            b.setEnabled(writable)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.grid = Grid()
        self.grid.set_empty_text('No ' + kind_label(kind).lower() + 's yet.\nAdd one here, or with "+ Add new" '
                                 'while choosing one during a repair.')
        self.grid.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.grid, 1)
        self.card = summary_card()
        layout.addWidget(self.card)
        self.reload()

    def reload(self, *_):
        rows = Contacts(self.s).directory(self.kind, self.search.text(), self.inactive.isChecked())
        self.grid.fill(rows, self.COLUMNS.get(self.kind, self.DEFAULT))
        self.show_selected()

    def show_selected(self):
        row = self.grid.selected()
        if not row:
            self.card.hide()
            return
        contacts = Contacts(self.s)
        lines = [summary(contacts.snapshot(row['id']))]
        stats = contacts.activity(row['id'])
        if self.kind == 'transporter':
            text = f"Dispatches: {stats['dispatches']}"
            if self.s.may('financial_reports'):
                text += ' · Transport charges: ' + rupees(stats['transport_total'])
            lines.append(text)
        elif self.kind in PARTNER_KINDS:
            text = (f"Repairs: {stats['jobs']} · Open: {stats['open']} · Completed: {stats['completed']}"
                    f" · Unable / returned unrepaired: {stats['unable']}")
            if stats['turnaround_days'] is not None:
                text += f" · Average turnaround: {stats['turnaround_days']} days"
            if self.kind == 'centre':
                text += f" · Warranty jobs: {stats['warranty_jobs']}"
            lines.append(text)
        if row.get('notes'):
            lines.append(row['notes'])
        self.card.setText('\n'.join(x for x in lines if x))
        self.card.show()

    def add(self):
        form = ContactForm(self.window, self.kind)
        if form.open():
            self.reload()

    def edit(self):
        row = self.grid.selected()
        if not row:
            raise_select()
        if ContactForm(self.window, self.kind, row).open():
            self.reload()

    def toggle(self):
        row = self.grid.selected()
        if not row:
            raise_select()
        Contacts(self.s).set_active(row['id'], not row['active'])
        self.reload()


class SetupList(QWidget):
    """Shop configuration lists (categories, services, technicians…) using the existing master form."""

    def __init__(self, window, kind):
        super().__init__()
        self.window, self.kind = window, kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        bar = FlowLayout()
        for text, handler, primary in (('+ Add', lambda: self.window.master_form(kind), True),
                                       ('Edit / deactivate', lambda: self.window.master_form(kind, self.selected()), False)):
            b = button(text, lambda checked=False, h=handler: self.window.safe(h), primary)
            b.setEnabled(not window.db.readonly and window.s.may('directories'))
            bar.addWidget(b)
        layout.addLayout(bar)
        self.grid = Grid()
        layout.addWidget(self.grid, 1)
        self.grid.fill(window.db.rows('SELECT id,name,contact,details,active FROM masters WHERE kind=? ORDER BY active DESC,name', (kind,)),
                       ['name', 'contact', 'details', 'active'])

    def selected(self):
        row = self.grid.selected()
        if not row:
            raise_select()
        return self.window.db.one('SELECT * FROM masters WHERE id=?', (row['id'],))


def raise_select():
    from .domain import RuleError
    raise RuleError('Select a record first.')


#: Contacts & Services layout: what a shopkeeper looks for, in the words they use.
SECTIONS = [
    ('Repair Partners', [('vendor', 'Third-Party Repairers'), ('centre', 'Authorized Service Centres')]),
    ('Suppliers', [('supplier', 'Suppliers')]),
    ('Transport', [('transporter', 'Bus / Transport Services')]),
    ('Shop Setup', [(k, v) for k, v in SETUP_KINDS.items()]),
]


class ContactsPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        state = window.__dict__.setdefault('contacts_tabs', {})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel('Configure partners, suppliers and bus services once. During a repair staff only select them '
                      'and type what is unique to that job.')
        hint.setObjectName('subtitle')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tabs = QTabWidget()
        self.lists = {}
        for section, kinds in SECTIONS:
            inner = QTabWidget() if len(kinds) > 1 else None
            for kind, title in kinds:
                widget = ContactList(window, kind) if kind in CONTACT_KINDS else SetupList(window, kind)
                self.lists[kind] = widget
                if inner is not None:
                    inner.addTab(widget, title)
            page = inner or self.lists[kinds[0][0]]
            self.tabs.addTab(page, section)
            if inner is not None:
                inner.setCurrentIndex(state.get(section, 0))
                inner.currentChanged.connect(lambda index, s=section: state.__setitem__(s, index))
        self.tabs.setCurrentIndex(state.get('_section', 0))
        self.tabs.currentChanged.connect(lambda index: state.__setitem__('_section', index))
        layout.addWidget(self.tabs, 1)

    def show_kind(self, kind):
        for index, (section, kinds) in enumerate(SECTIONS):
            keys = [k for k, _ in kinds]
            if kind in keys:
                self.tabs.setCurrentIndex(index)
                page = self.tabs.widget(index)
                if isinstance(page, QTabWidget):
                    page.setCurrentIndex(keys.index(kind))
                return self.lists[kind]
