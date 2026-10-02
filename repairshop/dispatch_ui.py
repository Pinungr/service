"""Owner-facing dispatch panel: current record, safe editing, audited amendment.

Before the physical handover the same record is edited. Afterwards the panel only
offers Amend, which supersedes the record with a mandatory correction reason and
never touches the custody movement that recorded the actual handover.
"""
import uuid
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox
from .ui_widgets import Form, Grid, button, FlowLayout
from .dispatch import Dispatches, TRANSPORT_MODES, TRANSPORT_PAYERS, TRANSPORT_DATES, TRANSPORT_LABELS
from .domain import rupees, money, RuleError, in_shop

MODE_LABELS = [('Courier', 'COURIER'), ('Bus', 'BUS'), ('In hand', 'IN_HAND')]
PAYER_LABELS = [(label, key) for key, label in TRANSPORT_PAYERS.items()]
# One label map, shared with the workspace's prepare-dispatch form, so the same field is
# never called two different things on the two screens that write it.
FIELD_LABELS = TRANSPORT_LABELS


def transport_fields(form, mode_selector, current=None):
    """Build every mode's fields once and show only the selected mode's.

    Switching mode clears the fields of the mode being left, so a value typed under
    Courier can never be saved against a Bus dispatch.
    """
    modes, state = {}, {'mode': mode_selector.currentData()}
    for mode, keys in TRANSPORT_MODES.items():
        rows = []
        for key in keys:
            name = 'transport_' + mode + '_' + key
            saved = (current or {}).get(key, '') if current is not None and state['mode'] == mode else ''
            widget = (form.date(name, TRANSPORT_LABELS[key], saved or None) if key in TRANSPORT_DATES
                      else form.text(name, TRANSPORT_LABELS[key], saved))
            rows.append((key, widget))
        modes[mode] = rows

    def show(*_):
        chosen = mode_selector.currentData()
        if chosen != state['mode']:
            for key, widget in modes.get(state['mode'], []):
                if key in TRANSPORT_DATES:
                    widget.setDate(widget.minimumDate())
                else:
                    widget.clear()
            state['mode'] = chosen
        for mode, rows in modes.items():
            for _, widget in rows:
                widget.setVisible(mode == chosen)
                field_label = form.layout.labelForField(widget)
                if field_label:
                    field_label.setVisible(mode == chosen)
    mode_selector.currentIndexChanged.connect(show)
    show()

    def collect(values):
        """Take every mode's keys out of the payload, keep only the chosen mode's."""
        chosen = values.pop('transport_mode')
        transport = {}
        for mode, rows in modes.items():
            for key, _ in rows:
                value = values.pop('transport_' + mode + '_' + key, '')
                if mode == chosen and str(value or '').strip():
                    transport[key] = str(value).strip()
        return chosen, transport
    return collect


def describe(d):
    if not d:
        return 'No dispatch record for this repair yet.'
    return '\n'.join(filter(None, [
        'Third party: ' + (d['party'] or d['contact_name'] or 'Not selected'),
        'Status: ' + d['status'] + ' · version ' + str(d['version']),
        'Transport: ' + d['transport_mode'].replace('_', ' ').title(),
        d['transport_summary'],
        'Transport amount: ' + rupees(d['amount']),
        'Transport paid by: ' + TRANSPORT_PAYERS.get(d.get('paid_by'), str(d.get('paid_by') or 'shop').replace('_', ' ').title()),
        'Reference: ' + (d['reference'] or 'Not recorded'),
        'Expected return: ' + (d['expected_return'] or 'Not set'),
        'Sent: ' + (d['actual_dispatch_at'] or 'Not yet physically dispatched'),
        'Condition at dispatch: ' + (d['condition'] or 'Not recorded'),
        'Notes: ' + (d['notes'] or 'None'),
        ('Correction reason: ' + d['amendment_reason']) if d['amendment_reason'] else '',
    ]))


class DispatchPanel(QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace, self.window = workspace, workspace.window
        self.service = Dispatches(self.window.s)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.controls = FlowLayout()
        layout.addLayout(self.controls)
        layout.addWidget(QLabel('Dispatch versions'))
        self.grid = Grid()
        self.grid.set_empty_text('No dispatch has been prepared for this repair.')
        layout.addWidget(self.grid)
        self.manifest = Grid()
        layout.addWidget(QLabel('Items recorded on the current dispatch'))
        layout.addWidget(self.manifest)
        layout.addStretch()
        self.reload()

    def reload(self):
        ident = self.workspace.ident
        current = self.service.current(ident)
        self.summary.setText(describe(current))
        while self.controls.count():
            item = self.controls.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if current:
            if current['editable']:
                self.controls.addWidget(self._action('Edit dispatch', self.edit))
                self.controls.addWidget(self._action('Cancel dispatch', self.cancel))
            else:
                self.controls.addWidget(self._action('Amend dispatch', self.amend))
        history = self.service.history(ident)
        for row in history:
            row['transport_details'] = row['transport_summary']
            row['transport_amount'] = rupees(row['amount'])
            row['transport_payer'] = TRANSPORT_PAYERS.get(row.get('paid_by'), str(row.get('paid_by') or 'shop').replace('_', ' ').title())
            row['state'] = 'Current' if row['current'] else 'Superseded'
        self.grid.fill(history, ['version', 'status', 'state', 'contact_name', 'reference',
                                 'transport_mode', 'transport_details', 'transport_amount', 'transport_payer',
                                 'actual_dispatch_at', 'amendment_reason', 'created'])
        held = {r['id']: r for r in self.window.db.rows(
            '''SELECT i.id,i.description,i.type,i.serial,h.location,h.quantity FROM items i
               JOIN holdings h ON h.item_id=i.id WHERE i.job_id=?''', (ident,))}
        self.manifest.fill([held.get(i, {'id': i, 'description': 'Item no longer listed'})
                            for i in (current['manifest'] if current else [])],
                           ['description', 'type', 'serial', 'location', 'quantity'])

    def _action(self, title, handler):
        b = button(title, lambda: self.window.safe(handler))
        b.setEnabled(not self.window.db.readonly)
        return b

    def _fields(self, form, current, mode_editable=True):
        selector = form.select('transport_mode', 'Transport mode', MODE_LABELS, current['transport_mode'])
        selector.setEnabled(mode_editable)
        gather = transport_fields(form, selector, current['transport'])
        form.text('amount', 'Amount (INR)', str(current['amount'] / 100))
        form.select('paid_by', 'Transport paid by', PAYER_LABELS, current.get('paid_by') or 'shop')
        form.text('reference', 'Service centre job / vendor ticket number', current['reference'])
        form.date('expected_return', 'Expected return date', current['expected_return'])
        form.text('notes', 'Dispatch notes', current['notes'], multiline=True)
        def collect(p):
            mode, transport = gather(p)
            return dict(transport_mode=mode, transport=transport, amount=money(p.pop('amount') or '0'),
                        paid_by=p.pop('paid_by', 'shop'), reference=p.pop('reference', ''), expected_return=p.pop('expected_return', None),
                        notes=p.pop('notes', ''))
        return collect

    def edit(self):
        current = self.service.current(self.workspace.ident)
        if not current or not current['editable']:
            raise RuleError('This dispatch has already been sent. Use Amend dispatch instead.')
        form = Form('Edit dispatch', self, 'Nothing has physically left the shop yet, so these details are corrected in place.')
        collect = self._fields(form, current)
        form.text('condition', 'Device condition at dispatch', current['condition'], multiline=True)
        checks = []
        for row in self.window.db.rows('''SELECT i.id,i.description,i.type,h.location,h.quantity FROM items i
            JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND h.quantity>0''', (self.workspace.ident,)):
            if not in_shop(row['location']):
                continue
            box = QCheckBox(f"{row['description']} · {row['quantity']} unit(s)")
            box.setChecked(row['id'] in current['manifest'] or row['type'] == 'device')
            form.layout.addRow('Send item', box)
            checks.append((row['id'], box))
        def save(p):
            values = collect(p)
            values.update(condition=p.get('condition', ''), consent=True,
                          manifest=[i for i, w in checks if w.isChecked()])
            self.service.edit(self.workspace.ident, values)
        if form.submit(save):
            self.refresh()

    def amend(self):
        current = self.service.current(self.workspace.ident)
        form = Form('Amend dispatch', self,
                    'The device has already been handed over. A correction creates a new dispatch version; '
                    'the original record and the physical custody movement are preserved unchanged.')
        collect = self._fields(form, current, mode_editable=True)
        form.select('reason_code', 'Correction reason', [
            ('Wrong docket / tracking number entered', 'Wrong docket number entered'),
            ('Wrong bus / vehicle number', 'Wrong bus number entered'),
            ('Incorrect courier amount', 'Incorrect courier amount'),
            ('Phone number correction', 'Phone number correction'),
            ('Spelling mistake', 'Spelling mistake'),
            ('Other (explain below)', 'Other'),
        ])
        form.text('reason', 'Correction / amendment explanation', multiline=True)
        def save(p):
            values = collect(p)
            explanation = (p.get('reason') or '').strip()
            code = p.get('reason_code') or ''
            if code == 'Other' and not explanation:
                raise RuleError('Explain the correction before amending a sent dispatch.')
            reason = (code + (': ' + explanation if explanation else '')).strip(': ')
            self.service.amend(self.workspace.ident, values, reason, operation_id=uuid.uuid4().hex)
        if form.submit(save):
            self.refresh()

    def cancel(self):
        form = Form('Cancel dispatch', self, 'Only a dispatch that has not physically left the shop can be cancelled.')
        form.text('reason', 'Reason for cancelling this dispatch', multiline=True)
        if form.submit(lambda p: self.service.cancel(self.workspace.ident, p.get('reason', ''))):
            self.refresh()

    def refresh(self):
        self.workspace.reload()
