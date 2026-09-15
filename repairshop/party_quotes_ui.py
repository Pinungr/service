"""Owner-only panel for the third party's own quotation versions.

Everything shown here is what the external repairer charges the shop. The customer
price is decided separately in the customer quotation, so the shop margin is never
exposed by this screen or by anything it generates.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSpinBox, QLineEdit
from .ui_widgets import Form, Grid, button, FlowLayout
from .party_quotes import PartyQuotes, LINE_KINDS
from .domain import rupees, money, RuleError


class PartyQuotePanel(QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace, self.window = workspace, workspace.window
        self.service = PartyQuotes(self.window.s)
        layout = QVBoxLayout(self)
        note = QLabel('Third-party cost is internal. It is not shown to the customer and is never '
                      'billed directly: charge the customer through the customer quotation.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        layout.addWidget(note)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        controls = FlowLayout()
        layout.addLayout(controls)
        self.new_quote = button('Record third-party quotation', lambda: self.window.safe(self.issue))
        self.new_quote.setEnabled(not self.window.db.readonly)
        controls.addWidget(self.new_quote)
        layout.addWidget(QLabel('Versions'))
        self.versions = Grid()
        self.versions.set_empty_text('No third-party quotation has been recorded for this repair.')
        layout.addWidget(self.versions)
        layout.addWidget(QLabel('Lines on the selected version'))
        self.lines = Grid()
        layout.addWidget(self.lines)
        self.versions.cellClicked.connect(lambda *_: self.show_lines())
        layout.addStretch()
        self.reload()

    def reload(self):
        history = self.service.history(self.workspace.ident)
        current = next((r for r in history if r['state'] == 'current'), None)
        self.summary.setText('No third-party quotation recorded.' if not current else '\n'.join([
            'Current version: V' + str(current['version']),
            'Parts: ' + rupees(current['parts_total']),
            'Labour: ' + rupees(current['labour']),
            'Transport: ' + rupees(current['transport']),
            'Other: ' + rupees(current['other']),
            'Total third-party cost: ' + rupees(current['total']),
            'Reference: ' + (current['reference'] or 'Not recorded'),
        ]))
        self.history = history
        self.versions.fill([dict(version=r['version'], state=r['state'], parts=rupees(r['parts_total']),
                                 labour=rupees(r['labour']), transport=rupees(r['transport']),
                                 other=rupees(r['other']), total=rupees(r['total']),
                                 reason=r['revision_reason'], created=r['created'])
                            for r in history],
                           ['version', 'state', 'parts', 'labour', 'transport', 'other', 'total', 'reason', 'created'])
        self.show_lines(current)

    def show_lines(self, quote=None):
        if quote is None:
            row = self.versions.currentRow()
            quote = self.history[row] if 0 <= row < len(self.history) else None
        self.lines.fill([dict(kind=l['kind'], name=l['name'], quantity=l['quantity'],
                              third_party_cost=rupees(l['unit_cost']), customer_charge=rupees(l['customer_charge']),
                              warranty=l['warranty'], notes=l['notes'])
                         for l in (quote or {}).get('lines', [])],
                        ['kind', 'name', 'quantity', 'third_party_cost', 'customer_charge', 'warranty', 'notes'])

    def issue(self):
        current = self.service.current(self.workspace.ident)
        d = Form('Third-party quotation' + (' · new version' if current else ''), self,
                 'Third-party supplied parts are recorded here only. They are not added to shop '
                 'inventory, because the shop never took them into stock.')
        d.resize(820, 780)
        rows = []
        for index in range(6):
            name = QLineEdit()
            quantity = QSpinBox(); quantity.setRange(1, 999); quantity.setValue(1)
            cost = QLineEdit(); cost.setPlaceholderText('Third-party cost (INR)')
            charge = QLineEdit(); charge.setPlaceholderText('Customer charge (INR, blank = not charged on)')
            warranty = QLineEdit(); warranty.setPlaceholderText('Warranty offered (optional)')
            line = QWidget(); box = QVBoxLayout(line); box.setContentsMargins(0, 0, 0, 0)
            for widget in (name, quantity, cost, charge, warranty):
                box.addWidget(widget)
            existing = (current or {}).get('lines', [])
            if index < len(existing):
                part = existing[index]
                name.setText(part['name']); quantity.setValue(part['quantity'])
                cost.setText(f"{part['unit_cost'] / 100:.2f}")
                charge.setText(f"{part['customer_charge'] / 100:.2f}" if part['customer_charge'] else '')
                warranty.setText(part['warranty'])
            d.layout.addRow(f'Part {index + 1}', line)
            rows.append((name, quantity, cost, charge, warranty))
        for key, title, value in [('labour', 'Third-party labour (INR)', (current or {}).get('labour', 0)),
                                  ('transport', 'Transport charged by third party (INR)', (current or {}).get('transport', 0)),
                                  ('other', 'Other third-party charge (INR)', (current or {}).get('other', 0))]:
            d.text(key, title, f'{value / 100:.2f}')
        d.text('reference', 'Third-party quotation reference', (current or {}).get('reference', ''))
        d.text('notes', 'Notes', (current or {}).get('notes', ''), multiline=True)
        if current:
            d.text('reason', 'Why is the quotation being revised?', multiline=True)
        def save(p):
            lines = []
            for name, quantity, cost, charge, warranty in rows:
                if not name.text().strip():
                    continue
                lines.append(dict(kind='part', name=name.text().strip(), quantity=quantity.value(),
                                  unit_cost=money(cost.text() or '0'),
                                  customer_charge=money(charge.text() or '0'),
                                  warranty=warranty.text().strip()))
            self.service.issue(self.workspace.ident, lines,
                               labour=money(p.get('labour') or '0'), transport=money(p.get('transport') or '0'),
                               other=money(p.get('other') or '0'), reference=p.get('reference', ''),
                               notes=p.get('notes', ''), reason=p.get('reason', ''))
        if d.submit(save):
            self.workspace.reload()
