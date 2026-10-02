"""Input forms for the guided repair actions, and how their answers become a command.

A presentation layer asks `describe(service, job_id, action)` what to collect for an
action the lifecycle currently allows, renders it, and sends the answers back through
`submit(...)`. Nothing here decides whether an action is allowed or what it does:
`Lifecycle.snapshot` lists the allowed actions and `Lifecycle.execute` enforces every
rule. This module only states which facts each step needs, prefilled from what the
repair already records so staff are not asked twice.

Field types: text, textarea, date, time, money (whole paise as an integer, never a float), number,
select, check, contact (a Contacts & Services selector), transport (method + its
fields), items (physical items to include), return_items (per-item received check) and
info (read-only text). `show_if` makes a field depend on another field's value.
"""
from .domain import RuleError, InvalidAction, paise, in_shop, rupees
from .lifecycle import Lifecycle, ACTIONS, ROUTE_LABELS, route_choices

#: Steps that ask nothing: pressing the button is the whole action.
ZERO_INPUT = frozenset(('inspect', 'start_repair', 'notify'))
#: Steps that open another part of the repair rather than a form of their own.
NAVIGATE = {'quote': 'quotes', 'decision': 'quotes', 'payment': 'payments', 'parts': 'parts',
            'manual_warranty': 'warranty', 'costing': 'costing', 'claim': 'warranty'}
#: Steps that replace or end something and are confirmed before they are sent.
CONFIRM = {'change_route': 'This replaces the current repair assignment. Continue?',
           'close': 'Close this delivered job? It stays available in Repair History.'}
COST_KEYS = ('vendor_parts', 'vendor_labour', 'transport_cost', 'other_cost', 'customer_price')
QC_CHECKS = (('functional', 'Functional test'), ('power', 'Power test'), ('charging', 'Charging test'),
             ('display', 'Display test'), ('connectivity', 'Connectivity test'),
             ('complaint', 'Original customer complaint resolved'))
RETURN_RESULTS = ('REPAIRED', 'PARTIALLY REPAIRED', 'NOT REPAIRABLE', 'REPAIR DECLINED', 'RETURNED WITHOUT REPAIR', 'REPLACED')
OUTCOMES = ('Customer declined repair', 'Not repairable', 'Repair failed', 'Cancelled')


def field(key, label, type='text', **extra):
    return dict(key=key, label=label, type=type, **{k: v for k, v in extra.items() if v is not None})


def options(pairs):
    return [dict(value=value, label=label) for label, value in pairs]


def info(key, label, text):
    return field(key, label, 'info', default=text)


class ActionForms:
    def __init__(self, service):
        self.s, self.db = service, service.db
        self.life = Lifecycle(service)

    # ---- describe -------------------------------------------------------
    def describe(self, job_id, action):
        v = self.life.snapshot(job_id)
        if action not in v['actions']:
            raise InvalidAction('That action is not available now. Refresh the job and follow the next required step.')
        form = dict(action=action, title=ACTIONS.get(action, action.replace('_', ' ').title()),
                    description=v['next_action'] if action == v['primary'] else '', fields=[],
                    submit_label=ACTIONS.get(action, 'Save'), confirm=CONFIRM.get(action),
                    navigate=NAVIGATE.get(action), version=v['version'])
        if action in NAVIGATE or action in ZERO_INPUT or action == 'close':
            return form
        builder = getattr(self, '_' + action, None) or self._notes_only
        form['fields'] = builder(v, action)
        return form

    def _notes_only(self, v, action):
        return [field('notes', 'Findings / notes', 'textarea', required=True)]

    def _adopt(self, v, action):
        return [field('confirmed', 'I reviewed the saved status, location, quotation and history', 'check', required=True),
                field('notes', 'Review findings / reason', 'textarea', required=True)]

    def _inspection_done(self, v, action):
        return [field('notes', 'Inspection findings', 'textarea', required=True)]

    def _verify_warranty(self, v, action):
        return [field('warranty_status', 'Warranty status', 'select', required=True, options=options([
                    ('Under manufacturer warranty', 'under_warranty'), ('Out of warranty', 'out_of_warranty'),
                    ('Unknown / requires verification', 'unknown')])),
                field('notes', 'Purchase proof / warranty dates / verification notes', 'textarea', required=True)]

    def _select_route(self, v, action):
        choices = route_choices(v)
        technicians = self.db.rows("SELECT id,name FROM masters WHERE kind='technician' AND active=1 ORDER BY name")
        external = ['third_party', 'warranty_centre']
        return [
            field('route', 'How will this device be repaired?', 'route', required=True,
                  options=[dict(value=c['route'], label=c['label'], disabled=not c['available'], reason=c['reason']) for c in choices]),
            field('vendor_id', 'Third-party repairer', 'contact', kind='vendor', job_id=v['id'], required=True,
                  show_if=dict(field='route', equals=['third_party'])),
            field('centre_id', 'Service centre', 'contact', kind='centre', job_id=v['id'], required=True,
                  show_if=dict(field='route', equals=['warranty_centre'])),
            field('technician_master_id', 'Assigned technician', 'select', required=True,
                  options=options([(t['name'], t['id']) for t in technicians]), show_if=dict(field='route', equals=['in_house'])),
            field('handed_over', 'Device physically handed to this technician now', 'check', show_if=dict(field='route', equals=['in_house'])),
            field('bench', 'Technician work area / bench', show_if=dict(field='handed_over', equals=[True])),
            field('condition', 'Condition at handover', default=v['damage'], show_if=dict(field='handed_over', equals=[True])),
            field('acknowledgment', 'Physical handover acknowledgment', show_if=dict(field='handed_over', equals=[True])),
            info('job_reference', 'Internal job reference',
                 f"{v['number']} | {v['device']} | " + ('SN-' + v['serial'] if v['serial'] else 'No serial recorded')),
            field('reference', 'External job / ticket no. (service centre: ticket / RMA)', show_if=dict(field='route', equals=external)),
            field('expected_return', 'Expected return', 'date', default=v['return_due'], show_if=dict(field='route', equals=external)),
            field('instructions', 'Special instructions / notes', 'textarea', show_if=dict(field='route', equals=external)),
        ]

    _change_route = _select_route

    def _prepare_dispatch(self, v, action):
        partner = v['assignment']
        usual = 'BUS' if self.s.masters('transporter') else 'COURIER'
        return [
            info('partner', 'Sending to', partner.get('summary') or partner.get('party') or 'External repairer'),
            field('transport', 'Transport', 'transport', default=dict(mode=usual), required=True),
            field('transport_amount', 'Transport charge (INR)', 'money', default=0),
            field('paid_by', 'Transport paid by', 'select', default='shop', options=options(_payers())),
            field('condition', 'Device condition at dispatch', 'textarea', default=v['damage'], required=True),
            field('expected_return', 'Expected return date', 'date', default=v['return_due']),
            field('reference', 'Service centre ticket / external job number', default=partner.get('reference', '')),
            field('items', 'Items being sent', 'items', required=True, options=[
                dict(value=h['id'], label=f"{h['description']} · {h['quantity']} unit(s)", type=h['type'])
                for h in v['holdings'] if in_shop(h['location'])],
                default=[h['id'] for h in v['holdings'] if in_shop(h['location']) and h['type'] == 'device']),
            field('consent', 'Customer consent to dispatch and assessment recorded', 'check',
                  default=bool(v['assessment_consent']), required=True),
            field('notes', 'Dispatch notes', 'textarea'),
        ]

    def _hand_over(self, v, action):
        holders = ' / '.join(dict.fromkeys(h['name'] + ' (' + h['role'] + ')' for h in v['custodians'])) or 'Not recorded'
        people = self.db.rows('SELECT id,name,role FROM users WHERE active=1 AND id!=? ORDER BY name', (self.s.user['id'],))
        if not people:
            raise RuleError('There is no other active staff member to hand this product to.')
        return [info('holder', 'Currently with', holders + '\nHanding the product over does not change who the repair is assigned to.'),
                field('to_user_id', 'Hand over to', 'select', required=True,
                      options=options([(f"{p['name']} · {p['role'].title()}", p['id']) for p in people])),
                field('condition', 'Condition at handover', 'textarea', default=v['damage'], required=True),
                field('acknowledgment', 'Handover acknowledgment', required=True),
                field('notes', 'Reason / notes', 'textarea')]

    def _hand_technician(self, v, action):
        rows = [field('condition', 'Device condition', 'textarea', default=v['damage'], required=True),
                field('acknowledgment', 'Physical handover acknowledgment', required=True)]
        if action == 'hand_technician':
            rows.append(field('bench', 'Technician work area / bench', default=v['data'].get('technician_bench', ''), required=True))
        else:
            rows.append(info('receiver', 'Taken back by', self.s.user['name'] + ' (you)'))
        return rows + [field('notes', 'Handover notes', 'textarea')]

    _return_technician = _hand_technician

    def _external(self, v, action):
        from .dispatch import carrier, tracking
        manifest = v['data'].get('dispatch', {})
        record = (v.get('dispatch') or {}) if action == 'dispatch' else {}
        transport = record.get('transport') or {}
        sender = (transport.get('person_name') or (record.get('transporter_snapshot') or {}).get('contact_person')
                  or transport.get('courier_name') or '')
        rows = [info('custody', 'Custody', 'Current custodian: ' + v['current_custodian'] + '\nDestination: '
                     + (v['final_destination'] or v['assignment'].get('party') or 'Shop')),
                field('counterparty', 'Person receiving the items', default=sender, required=True),
                field('condition', 'Condition at handover', 'textarea', default=manifest.get('condition', ''), required=True),
                field('reference', 'Tracking / external job reference', default=tracking(record) if record else manifest.get('reference', '')),
                field('acknowledgment', 'Acknowledgment / receipt reference', 'textarea', required=True)]
        if action in ('dispatch', 'return_dispatch'):
            rows.append(field('carrier', 'Carrier (blank = direct handover)' if action == 'dispatch' else 'Courier receiving the return',
                              default=carrier(record) if action == 'dispatch' else '', required=action == 'return_dispatch'))
        return rows + [field('notes', 'Notes', 'textarea')]

    _dispatch = _arrive = _return_dispatch = _external

    def _receive(self, v, action):
        from .returns import Returns, DISCREPANCIES
        expected = Returns(self.s).expected(v['id'])
        party = expected['party'] or v['assignment'].get('party') or 'External repairer'
        data = v['data']
        return [info('source', 'Receiving from', ('SERVICE CENTER' if v['route'] == 'warranty_centre' else 'THIRD PARTY')
                     + f" · {party}\nJob {v['number']} · {v['device']}"),
                field('counterparty', 'Person handing the items back', required=True),
                field('condition', 'Condition at receipt', 'textarea', required=True),
                field('reference', 'Tracking / external job reference'),
                field('acknowledgment', 'Acknowledgment / receipt reference', 'textarea', required=True),
                field('work_performed', 'Work performed', 'textarea', default=data.get('repair_summary', '')),
                field('parts_reported', 'Parts / replacements reported by repairer', 'textarea', default=data.get('parts_used', '')),
                field('vendor_invoice', 'Third-party / service centre invoice', default=data.get('route_details', {}).get('vendor_invoice', '')),
                field('repair_result', 'Repair result', 'select', default='',
                      options=options([('Use recorded repair outcome', '')] + [(x.title(), x) for x in RETURN_RESULTS])),
                info('receiver', 'Received by', self.s.user['name'] + ' (you)'),
                field('return_items', 'Items actually received now', 'return_items', required=True,
                      options=[dict(value=r['item_id'], label=r['description'], expected=r['expected'])
                               for r in expected['items'] if r['available']],
                      discrepancies=options([(k.replace('_', ' ').title(), k) for k in DISCREPANCIES])),
                field('verified', 'I physically checked the returned product and accessories against the dispatch manifest', 'check', required=True),
                field('notes', 'Return notes', 'textarea')]

    def _diagnose(self, v, action):
        return [field('notes', 'Confirmed fault / diagnosis', 'textarea', required=True),
                field('repairable', 'Device is repairable', 'check', default=True),
                field('parts', 'Required parts', 'textarea'),
                field('parts_available', 'Required parts available', 'check', default=True)]

    def _warranty_result(self, v, action):
        return [field('decision', 'Service center decision', 'select', required=True,
                      options=options([(x.title(), x) for x in ('pending', 'accepted', 'rejected', 'partial')])),
                field('rma', 'Claim / RMA number'),
                field('notes', 'Findings / rejection reason', 'textarea', required=True),
                field('covered', 'Covered work', 'textarea'), field('excluded', 'Excluded work', 'textarea'),
                field('terms', 'Warranty evidence / terms', 'textarea')]

    def _complete_repair(self, v, action):
        rows = [field('notes', 'Repair performed / replacement evidence', 'textarea', required=True),
                field('parts', 'Parts used', 'textarea')]
        if action == 'replacement':
            rows += [field('description', 'Replacement device', required=True), field('serial', 'New serial number'),
                     field('terms', 'Replacement warranty', 'textarea')]
        return rows

    _replacement = _complete_repair

    def _test(self, v, action):
        return [field('result', 'Technician test result', 'select', required=True,
                      options=options([('Passed', 'passed'), ('Failed — re-diagnose', 'failed')])),
                field('notes', 'Test observations', 'textarea', required=True)]

    def _decline(self, v, action):
        return [field('reason', 'Outcome', 'select', required=True, options=options([(x, x) for x in OUTCOMES])),
                field('notes', 'Reason and customer conversation', 'textarea', required=True)]

    _repair_failed = _decline

    def _details(self, v, action):
        details = v['data'].get('route_details', {})
        rows = []
        if v['data'].get('legacy_review'):
            rows.append(field('warranty_status', 'Verified legacy warranty status', 'select', default=v['warranty_status'],
                              options=options([('Unknown', 'unknown'), ('Under warranty', 'under_warranty'), ('Out of warranty', 'out_of_warranty')])))
        if v['route'] != 'in_house':
            rows.append(info('partner', 'Repair partner', (v['assignment'].get('summary') or v['assignment'].get('party') or 'Not selected')
                             + '\nContact details are kept in Contacts & Services.'))
            rows += [field('external_reference', 'Service centre ticket / external job number',
                           default=details.get('external_reference') or v['assignment'].get('reference', '')),
                     field('claim_number', 'Warranty claim number', default=details.get('claim_number', '')),
                     field('vendor_status', 'External repair status', default=details.get('vendor_status', '')),
                     field('expected_return', 'Expected return', 'date', default=v['return_due'])]
            if self.s.may('view_internal_cost'):
                rows += [field(k, title + ' (INR)', 'money', default=int(details.get(k, 0) or 0))
                         for k, title in (('vendor_parts', 'Vendor parts cost'), ('vendor_labour', 'Vendor labour cost'),
                                          ('transport_cost', 'Transport cost'), ('other_cost', 'Other cost'),
                                          ('customer_price', 'Proposed customer price'))]
        elif self.s.may('view_internal_cost'):
            rows += [field('estimated_parts', 'Estimated parts cost (INR)', default=details.get('estimated_parts', '')),
                     field('estimated_labour', 'Estimated labour cost (INR)', default=details.get('estimated_labour', ''))]
        return rows + [field('notes', 'Progress notes', 'textarea', default=details.get('notes', ''))]

    def _resolve_item(self, v, action):
        rows = [h for h in v['holdings'] if h['location'] != 'customer' and not h['location'].startswith('exception:')]
        return [field('item', 'Outstanding item', 'select', required=True,
                      options=[dict(value=f"{h['id']}|{h['location']}", label=h['description'] + ' · ' + h['location']) for h in rows]),
                field('quantity', 'Units to resolve', 'number', default=1, required=True),
                field('counterparty', 'Responsible party / person authorizing resolution', required=True),
                field('reference', 'Evidence reference'),
                field('notes', 'Owner explanation (lost, retained, replacement or other resolution)', 'textarea', required=True)]

    def _qc(self, v, action):
        rows = [info('context', 'Repair', _context(v))]
        if v['data'].get('unrepaired'):
            rows.append(field('condition_checked', 'Device condition checked against intake; unrepaired outcome explained', 'check', required=True))
        else:
            for key, title in QC_CHECKS:
                choices = [('Not checked', ''), ('Passed', 'passed'), ('Failed', 'failed')]
                if key in ('charging', 'display', 'connectivity'):
                    choices.append(('Not applicable', 'not_applicable'))
                rows.append(field('check_' + key, title, 'select', default='', options=options(choices)))
            rows.append(field('result', 'QC result', 'select', required=True,
                              options=options([('PASS QC', 'passed'), ('FAIL QC — return to diagnosis', 'failed')])))
        return rows + [field('notes', 'QC findings / return condition', 'textarea', required=True),
                       field('repair_warranty', 'Repair warranty terms', 'textarea'),
                       field('warranty_until', 'Repair warranty valid until', 'date')]

    def _bill(self, v, action):
        from .billing import Billing, CATEGORIES
        s = Billing(self.s).summary(v['id'])
        lines = [('Initial estimate', rupees(s['initial_estimate'])),
                 ('Approved quote' + (' v' + str(s['approved_version']) if s['approved_version'] else ''),
                  rupees(s['approved_total']) if s['approved_total'] is not None else 'Not approved'),
                 ('Final bill', rupees(s['final_bill']) if s['final_bill'] else 'Not billed yet'),
                 ('Advance paid', rupees(s['advance'])), ('Other payments', rupees(s['other_payments'])),
                 ('Balance due', rupees(s['balance_due']))]
        lines += [(key.title(), rupees(s['approved_breakdown']['totals'][key])) for key in CATEGORIES]
        outstanding = self.db.rows("""SELECT d.kind,d.notes,i.description FROM return_discrepancies d
            JOIN return_verifications rv ON rv.id=d.verification_id LEFT JOIN items i ON i.id=d.item_id
            WHERE rv.job_id=? AND d.resolved=''""", (v['id'],))
        rows = [info('summary', 'Billing review', '\n'.join(f'{a}: {b}' for a, b in lines)),
                info('qc', 'QC result', v['data'].get('qc', {}).get('result', 'Pending'))]
        if outstanding:
            rows.append(info('discrepancies', 'Unresolved return discrepancies', '\n'.join(
                f"{r['description'] or 'Item'} — {r['kind'].replace('_', ' ')}: {r['notes']}" for r in outstanding)))
        return rows + [field('confirmed', 'Charges and advances reviewed; issue the applicable bill and mark ready', 'check', required=True)]

    def _handover(self, v, action):
        items = self.db.rows("SELECT description,quantity FROM items WHERE job_id=? AND type='accessory'", (v['id'],))
        outstanding = '; '.join(f"{h['description']} × {h['quantity']}" for h in v['holdings']
                                if h['location'] != 'customer' and not h['location'].startswith('exception:'))
        rows = [info('context', 'Repair', _context(v)),
                info('accessories', 'Accessories originally received', '; '.join(f"{r['description']} × {r['quantity']}" for r in items) or 'None'),
                info('return_now', 'Items to return now', outstanding or 'None'),
                info('money', 'Payments', 'Payments retained: ' + rupees(v['paid']) + ' · Balance: ' + rupees(v['balance'])
                     + '\nRepair warranty: ' + (v['data'].get('repair_warranty') or 'None supplied'))]
        rows += [field(k, t, 'check', required=True) for k, t in (
            ('demonstrated', 'Device / unrepaired condition demonstrated to customer'), ('accepted', 'Customer accepted the device'),
            ('accessories_returned', 'All listed accessories returned'), ('payment_checked', 'Payment completed or owner-approved credit reviewed'))]
        rows += [field('received_by', 'Received by', default=v['customer'], required=True),
                 field('acknowledgment', 'Customer confirmation / signed receipt reference', 'textarea', required=True)]
        if self.s.may('release_with_balance'):
            rows.append(field('credit_reason', 'Owner-approved credit reason (only if balance remains)', 'textarea'))
        return rows + [field('notes', 'Final notes', 'textarea')]

    # ---- submit ---------------------------------------------------------
    def submit(self, job_id, action, values, version=None, operation_id=None):
        """Shape the answers into the lifecycle payload and run the step."""
        p = self.payload(job_id, action, dict(values or {}), operation_id)
        return self.life.execute(job_id, action, p, version, operation_id=operation_id)

    def payload(self, job_id, action, p, operation_id=None):
        if action in ('select_route', 'change_route'):
            route = p.get('route')
            contact = p.pop('vendor_id', None) if route == 'third_party' else p.pop('centre_id', None) if route == 'warranty_centre' else None
            p.pop('vendor_id', None), p.pop('centre_id', None)
            if route in ('third_party', 'warranty_centre'):
                p['contact_id'] = contact
            p['confirmed'] = True
        elif action == 'prepare_dispatch':
            transport = p.pop('transport', None) or {}
            p['transport_mode'] = transport.get('mode')
            p['transport'] = {k: v for k, v in (transport.get('fields') or {}).items() if str(v or '').strip()}
            p['transporter_id'] = transport.get('service_id') if transport.get('mode') == 'BUS' else None
            p['amount'] = paise(p.pop('transport_amount', 0))
            p['items'] = [int(i) for i in p.get('items') or []]
        elif action == 'receive':
            if not p.pop('verified', False):
                raise RuleError('Confirm that you physically checked the returned items against the dispatch manifest.')
            received = p.pop('return_items', None) or []
            p['items'] = [int(r['item_id']) for r in received if int(r.get('received') or 0)]
            p['quantities'] = {str(r['item_id']): int(r.get('received') or 0) for r in received}
            p['discrepancies'] = [dict(item_id=int(r['item_id']), kind=r['discrepancy'], expected=int(r.get('expected') or 0),
                                       received=int(r.get('received') or 0), notes=r.get('notes', ''))
                                  for r in received if r.get('discrepancy')]
            p['operation_id'] = operation_id or p.get('operation_id')
            p['received_by'] = p.get('counterparty', '')
            if not p.get('repair_result'):
                p['repair_result'] = None
        elif action == 'qc':
            p['checks'] = {key: p.pop('check_' + key) for key, _ in QC_CHECKS if 'check_' + key in p}
        elif action == 'resolve_item':
            item, _, source = str(p.pop('item', '') or '').partition('|')
            if not item:
                raise RuleError('Select an outstanding item.')
            p.update(item_id=int(item), source=source, quantity=int(p.get('quantity') or 1))
        elif action == 'details':
            for key in COST_KEYS:
                if key in p:
                    p[key] = paise(p[key])
        elif action == 'hand_over' and p.get('to_user_id') is not None:
            p['to_user_id'] = int(p['to_user_id'])
        return p


def _payers():
    from .dispatch import TRANSPORT_PAYERS
    return [(label, key) for key, label in TRANSPORT_PAYERS.items()]


def _context(v):
    return (f"{v['customer']} · {v['phone']}\n{v['number']} · {v['device']}\nComplaint: {v['complaint']}"
            f"\nDiagnosis: {v['data'].get('diagnosis', 'See saved repair records')}"
            f"\nRepair: {v['data'].get('repair_summary', v['data'].get('unrepaired', 'Not recorded'))}"
            f"\nRoute: {ROUTE_LABELS.get(v['route'], v['route'])} · "
            f"{v['assignment'].get('party') or v['assignment'].get('technician') or 'Shop'}")
