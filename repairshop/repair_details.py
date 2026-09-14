"""Read-only, responsive repair details from the existing lifecycle snapshot."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QSizePolicy

from .domain import rupees
from .inventory import PRIVATE_FIELDS, public_values
from .lifecycle import local_time, ROUTE_LABELS
from .ui_widgets import CardGrid, panel


class _DetailsGrid(CardGrid):
    def __init__(self, cards):
        super().__init__(cards)
        self.reflow(2)

    def resizeEvent(self, event):
        QWidget.resizeEvent(self, event)
        self.reflow(max(1, min(3, (event.size().width() + 12) // 330)))

    def minimumSizeHint(self):
        return QSize(240, self.grid.minimumSize().height())


# The stored codes the state machine writes, shown in the words staff already
# see in the warranty dialogs. Nothing here changes what is stored.
WARRANTY_WORDS = {'under_warranty': 'Under manufacturer warranty', 'out_of_warranty': 'Out of warranty',
                  'shop_warranty': 'Under shop repair warranty', 'unknown': 'Unknown / requires verification'}


def _text(value):
    if value is None or value == '':
        return 'Not recorded'
    if isinstance(value, dict):
        return '\n'.join(f"{key.replace('_', ' ').title()}: {_text(item)}" for key, item in value.items()) or 'Not recorded'
    if isinstance(value, (list, tuple)):
        return '\n'.join(_text(item) for item in value) or 'Not recorded'
    return str(value)


def _label(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class RepairDetails(QWidget):
    """Render only supplied snapshot values; never query or change a repair."""
    GROUPS = ('Responsibility', 'Diagnosis', 'Repair', 'Dates', 'Financial', 'Quality / closure')

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.forms = {}
        self.values = {}
        cards = []
        for title in self.GROUPS:
            card, layout = panel(title)
            card.setAccessibleName(title + ' details')
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(8)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            layout.addLayout(form)
            layout.addStretch()
            self.forms[title] = form
            cards.append(card)
        self.grid = _DetailsGrid(cards)
        outer.addWidget(self.grid)

    def set_snapshot(self, v):
        # Counter snapshots are already filtered by Lifecycle. Apply the same
        # recursive rules here so even nested route details stay public.
        v = public_values(v)
        d, a, quote = v.get('data', {}), v.get('assignment', {}), v.get('quote', {})
        groups = {
            'Responsibility': [
                ('Responsible for work', v.get('responsible')),
                ('Current custodian', v.get('current_custodian')),
                ('Physical location', v.get('current_location')),
                ('Warranty route', WARRANTY_WORDS.get(v.get('warranty_status'), v.get('warranty_status'))),
                ('Assigned technician', a.get('technician')),
                ('Repairer', a.get('party')),
                ('Repairer contact', a.get('contact')),
                ('Repairer details', a.get('details'))],
            'Diagnosis': [
                ('Reported fault', v.get('complaint')),
                ('Intake condition', v.get('damage')),
                ('Confirmed diagnosis', d.get('diagnosis'))],
            'Repair': [
                ('Repair performed', d.get('repair_summary')),
                ('Parts required', d.get('parts_required')),
                ('Parts availability', 'Available' if d.get('parts_available') else 'Pending' if 'parts_available' in d else 'Not recorded'),
                ('Parts used', d.get('parts_used'))],
            'Dates': [
                ('Pending since', v.get('pending_since')),
                ('Dispatch date', local_time(d.get('dispatched'))),
                ('Expected return', v.get('return_due')),
                ('Expected collection', v.get('collection_due')),
                ('Returned to shop', local_time(d.get('returned'))),
                ('Repair started', local_time(d.get('repair_started'))),
                ('Repair completed', local_time(d.get('repair_completed')))],
            'Financial': [
                ('Customer estimate', rupees(quote.get('total')) if quote else 'Not issued'),
                ('Approval', quote.get('state', 'Not recorded')),
                ('Advance / payments retained', rupees(v.get('paid'))),
                ('Balance due', rupees(v.get('balance')))],
            'Quality / closure': [
                ('QC result', d.get('qc', {}).get('result', 'Pending')),
                ('Repair warranty', d.get('repair_warranty')),
                ('Warranty until', d.get('warranty_until')),
                ('Unrepaired outcome', d.get('unrepaired'))],
        }
        groups['Repair'].extend(
            (key.replace('_', ' ').title(), value)
            for key, value in d.get('route_details', {}).items()
            if key not in PRIVATE_FIELDS | {'customer_price'})
        self.values = {}
        for title, rows in groups.items():
            form = self.forms[title]
            while form.rowCount():
                form.removeRow(0)
            for name, value in rows:
                caption = _label(name, 'subtitle')
                caption.setFixedWidth(112)
                caption.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
                field = _label(_text(value), 'repairDetailValue')
                field.setMinimumWidth(96)
                field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                field.setAccessibleName(name)
                self.values[name] = field
                form.addRow(caption, field)
        self.grid.updateGeometry()
        self.updateGeometry()
