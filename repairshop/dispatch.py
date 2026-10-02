"""Versioned third-party / service-centre dispatch records, owned by one repair job.

A dispatch is administrative information about sending one job's items to one
external repairer. It is never a substitute for the custody ledger: the physical
handover stays in movements/holdings and is not rewritten by a correction here.

Before the physical handover a draft may be edited in place. Afterwards a
correction creates a new version that supersedes the previous one, with a
mandatory reason, and both versions remain readable.
"""
import json
import re
from .domain import RuleError, now, money, in_shop, phone, day
from .persistence import insert

#: The single source of truth for how a product physically leaves the shop. Each method
#: asks only for what that journey needs. Reusable configuration (a bus operator's route
#: and contact) lives in the Bus / Transport Service directory, never in these fields.
#: Courier companies stay free text: a courier is chosen per parcel, not configured.
TRANSPORT_METHODS = {'BUS': 'Bus', 'COURIER': 'Courier', 'IN_HAND': 'In hand'}
TRANSPORT_MODES = {
    'COURIER': ('courier_name', 'docket_number', 'docket_date'),
    'BUS': ('bus_number', 'parcel_number', 'departure_date', 'departure_time', 'arrival_date', 'arrival_time'),
    'IN_HAND': ('person_name', 'mobile', 'role', 'departure_date', 'departure_time'),
}
#: Bus dispatches recorded before bus services became reusable typed the operator's
#: contact on every dispatch. Those keys stay valid only for a bus dispatch that names no
#: saved bus service, so old records can still be read and amended.
LEGACY_TRANSPORT = {'BUS': ('contact_name', 'contact_mobile')}
# Without these a dispatch record cannot be used to trace the product, which is the
# only reason it exists.
TRANSPORT_REQUIRED = {
    'COURIER': ('courier_name', 'docket_number'),
    'BUS': ('bus_number',),
    'IN_HAND': ('person_name', 'mobile'),
}
TRANSPORT_PHONES = ('contact_mobile', 'mobile')
TRANSPORT_DATES = ('docket_date', 'departure_date', 'arrival_date')
TRANSPORT_TIMES = ('departure_time', 'arrival_time')
TRANSPORT_LABELS = {
    'courier_name': 'Courier company', 'docket_number': 'Tracking / docket number', 'docket_date': 'Docket date',
    'bus_number': 'Bus number', 'parcel_number': 'Parcel / ticket number',
    'departure_date': 'Departure date', 'departure_time': 'Departure time',
    'arrival_date': 'Expected arrival date', 'arrival_time': 'Expected arrival time',
    'contact_name': 'Contact person name', 'contact_mobile': 'Contact person number',
    'person_name': 'Person name', 'mobile': 'Mobile', 'role': 'Role / relationship',
}
TRANSPORT_PAYERS = {
    'shop': 'Shop',
    'customer': 'Customer',
    'third_party': 'Third party',
    'service_center': 'Service center',
    'other': 'Other',
}
EDITABLE = ('reference', 'transport_mode', 'transport', 'amount', 'paid_by', 'expected_return',
            'condition', 'notes', 'manifest', 'consent', 'contact_id', 'transporter_id')
SENT = ('DISPATCHED', 'RETURNED')


def carrier(d):
    """Who physically carries a dispatch, read from what was already recorded on it.

    The send step offers this instead of asking the same question a second time.
    """
    if not d:
        return ''
    transport = d.get('transport') or {}
    mode = d.get('transport_mode')
    if mode == 'BUS':
        operator = (d.get('transporter_snapshot') or {}).get('name') or transport.get('contact_name', '')
        return ' · '.join(x for x in (operator, transport.get('bus_number')) if x)
    if mode == 'COURIER':
        return transport.get('courier_name', '')
    return transport.get('person_name', '')


def tracking(d):
    """The one number staff would quote to trace the parcel."""
    transport = (d or {}).get('transport') or {}
    return transport.get('docket_number') or transport.get('parcel_number') or (d or {}).get('reference', '')


class Dispatches:
    def __init__(self, service):
        self.s, self.db = service, service.db

    # ---- reads ----------------------------------------------------------
    def current(self, job_id):
        self.s.require_job_access(job_id)
        row = self.db.one('''SELECT d.*,m.name AS party FROM dispatches d LEFT JOIN masters m ON m.id=d.contact_id
            WHERE d.job_id=? AND d.current=1 ORDER BY d.cycle DESC LIMIT 1''', (job_id,))
        return self._readable(row) if row else None

    def history(self, job_id):
        self.s.require_job_access(job_id)
        return [self._readable(r) for r in self.db.rows('''SELECT d.*,m.name AS party
            FROM dispatches d LEFT JOIN masters m ON m.id=d.contact_id
            WHERE d.job_id=? ORDER BY d.cycle,d.version''', (job_id,))]

    def attempts(self, job_id):
        """Each external partner this repair was assigned to, in order, with what happened.

        A projection over the existing immutable records: an assignment is one attempt,
        its dispatches say when the product left and came back, and the guided receive
        step records the result. Nothing here is stored separately.
        """
        self.s.require_job_access(job_id)
        current = (self.db.one('SELECT assignment_id FROM jobs WHERE id=?', (job_id,)) or {}).get('assignment_id')
        rows = self.db.rows('''SELECT a.*,m.name AS live_name FROM assignments a LEFT JOIN masters m ON m.id=a.contact_id
            WHERE a.job_id=? AND a.contact_id IS NOT NULL ORDER BY a.id''', (job_id,))
        receipts = self.db.rows('''SELECT created,payload FROM audit WHERE entity='job' AND entity_id=? AND action='lifecycle'
            AND json_extract(payload,'$.action')='receive' ORDER BY id''', (job_id,))
        everything = self.db.rows('SELECT id FROM assignments WHERE job_id=? ORDER BY id', (job_id,))
        result = []
        for number, row in enumerate(rows, 1):
            later = [a['id'] for a in everything if a['id'] > row['id']]
            ends = self.db.one('SELECT created FROM assignments WHERE id=?', (later[0],))['created'] if later else None
            sent = self.db.rows('''SELECT d.cycle,max(d.actual_dispatch_at) AS sent,max(d.status) AS status,
                    (SELECT min(r.created) FROM return_verifications r JOIN dispatches x ON x.id=r.dispatch_id
                     WHERE x.job_id=d.job_id AND x.cycle=d.cycle) AS returned
                FROM dispatches d WHERE d.assignment_id=? GROUP BY d.cycle ORDER BY d.cycle''', (row['id'],))
            outcome = ''
            for event in receipts:
                if event['created'] >= row['created'] and (ends is None or event['created'] < ends):
                    outcome = (json.loads(event['payload']).get('evidence') or {}).get('repair_result') or outcome
            shot = json.loads(row['contact_snapshot'] or '{}')
            result.append(dict(attempt=number, assignment_id=row['id'], contact_id=row['contact_id'],
                               partner=shot.get('name') or row['live_name'], snapshot=shot, route=row['route'],
                               reference=row['reference'], expected_return=row.get('expected_return'),
                               instructions=row.get('instructions', ''), assigned=row['created'],
                               sent=next((d['sent'] for d in sent if d['sent']), None),
                               returned=next((d['returned'] for d in reversed(sent) if d['returned']), None),
                               result=outcome or ('In progress' if row['id'] == current else 'Reassigned'),
                               current=row['id'] == current))
        return result

    def courier_suggestions(self, limit=12):
        """Courier companies this shop has already used, most frequent first. Free text stays allowed."""
        self.s.require()
        return [r['name'] for r in self.db.rows("""SELECT trim(json_extract(transport,'$.courier_name')) AS name,count(*) AS n
            FROM dispatches WHERE transport_mode='COURIER' AND trim(COALESCE(json_extract(transport,'$.courier_name'),''))!=''
            GROUP BY lower(trim(json_extract(transport,'$.courier_name'))) ORDER BY n DESC,name LIMIT ?""", (limit,))]

    @staticmethod
    def _readable(row):
        row = dict(row)
        for key, empty in (('transport', {}), ('manifest', []), ('contact_snapshot', {}), ('transporter_snapshot', {})):
            try:
                row[key] = json.loads(row.get(key) or json.dumps(empty))
            except ValueError:
                row[key] = empty
        operator = row['transporter_snapshot']
        row['transporter'] = operator.get('name', '')
        details = []
        if operator:
            details.append('Bus service: ' + operator.get('name', ''))
            route = ' → '.join(x for x in (operator.get('route_from'), operator.get('route_to')) if x)
            if route:
                details.append('Route: ' + route)
        details += [TRANSPORT_LABELS.get(k, k.replace('_', ' ').title()) + ': ' + str(v)
                    for k, v in row['transport'].items() if v]
        row['transport_summary'] = ' · '.join(details)
        # History shows the partner as recorded on the dispatch, not as the directory reads today.
        row['party'] = row['contact_snapshot'].get('name') or row.get('party') or row.get('contact_name')
        row['carrier'] = carrier(row)
        row['label'] = f"Version {row['version']}" + ('' if row['current'] else ' · superseded')
        row['editable'] = row['status'] in ('DRAFT', 'READY')
        return row

    # ---- validation -----------------------------------------------------
    def _clean(self, c, job, values, existing=None, verify_manifest=True):
        p = dict(existing or {})
        for key in EDITABLE:
            if key in values:
                p[key] = values[key]
        mode = (p.get('transport_mode') or 'IN_HAND').upper()
        if mode not in TRANSPORT_MODES:
            raise RuleError('Choose a supported transport mode.')
        transport = p.get('transport') or {}
        if not isinstance(transport, dict):
            raise RuleError('Transport details must be recorded as named fields.')
        transport = {k: str(v).strip() for k, v in transport.items() if str(v).strip()}
        # A bus journey uses a saved bus service; its route and contact come from there.
        transporter_id = p.get('transporter_id') if mode == 'BUS' else None
        legacy = LEGACY_TRANSPORT.get(mode, ()) if not transporter_id else ()
        unknown = set(transport) - set(TRANSPORT_MODES[mode]) - set(legacy)
        if unknown:
            if transporter_id and unknown <= set(LEGACY_TRANSPORT.get(mode, ())):
                raise RuleError('The bus service contact comes from the selected bus service. Update it in Contacts & Services.')
            raise RuleError('Unsupported transport detail for ' + mode.replace('_', ' ').title() + ': ' + ', '.join(sorted(unknown)))
        # Both entry screens validate here rather than each on its own, so a dispatch
        # saved from the workspace and one corrected on the dispatch tab are held to the
        # same standard.
        required = TRANSPORT_REQUIRED[mode] + (legacy if any(transport.get(k) for k in legacy) else ())
        missing = [TRANSPORT_LABELS[k] for k in required if not transport.get(k)]
        if missing:
            raise RuleError('Enter ' + ', '.join(missing) + ' for a ' + mode.replace('_', ' ').lower() + ' dispatch.')
        operator, operator_shot = None, {}
        if mode == 'BUS':
            if transporter_id:
                operator = c.execute("SELECT id,active FROM masters WHERE id=? AND kind='transporter'", (transporter_id,)).fetchone()
                keep = existing and existing.get('transporter_id') == transporter_id and existing.get('transporter_snapshot')
                if not operator or (not operator['active'] and not keep):
                    raise RuleError('Select an active bus / transport service.')
                from .contacts import snapshot
                # A correction keeps the operator exactly as it was recorded when sent.
                operator_shot = existing['transporter_snapshot'] if keep and not verify_manifest else snapshot(c, transporter_id)
            elif not all(transport.get(k) for k in legacy):
                raise RuleError('Select the bus / transport service carrying this parcel.')
        for key in TRANSPORT_PHONES:
            if transport.get(key):
                try:
                    transport[key] = phone(transport[key])
                except RuleError:
                    raise RuleError('Enter a valid ' + TRANSPORT_LABELS[key].lower() + ', including the country code when needed.') from None
        for key in TRANSPORT_DATES:
            if transport.get(key):
                try:
                    transport[key] = day(transport[key][:10])
                except ValueError:
                    raise RuleError('Enter ' + TRANSPORT_LABELS[key].lower() + ' as a real calendar date.') from None
        for key in TRANSPORT_TIMES:
            if transport.get(key):
                match = re.fullmatch(r'([01]?\d|2[0-3]):([0-5]\d)', transport[key])
                if not match:
                    raise RuleError('Enter ' + TRANSPORT_LABELS[key].lower() + ' as HH:MM, for example 21:30.')
                transport[key] = f'{int(match.group(1)):02d}:{match.group(2)}'
        amount = p.get('amount', 0)
        if isinstance(amount, str):
            amount = money(amount or '0')
        if not isinstance(amount, int) or amount < 0:
            raise RuleError('Enter the transport amount as a nonnegative whole-paise value.')
        paid_by = str(p.get('paid_by') or 'shop').strip().lower()
        if paid_by not in TRANSPORT_PAYERS:
            raise RuleError('Choose who pays the transport charge.')
        manifest = sorted({int(i) for i in (p.get('manifest') or [])})
        if verify_manifest:
            # Only a not-yet-sent manifest is checked against live holdings: after the
            # handover the items are legitimately no longer in the shop.
            self._check_manifest(c, job, manifest)
        elif not manifest:
            raise RuleError('Select the physical items being sent.')
        contact_id = p.get('contact_id')
        if existing and not verify_manifest:
            # A sent dispatch is corrected, not re-addressed: keep the partner as recorded,
            # even if the directory record has since been edited or deactivated.
            party = dict(name=existing['contact_name'], kind=None)
            partner = existing.get('contact_snapshot') or {}
        else:
            party = c.execute('SELECT name,kind FROM masters WHERE id=? AND active=1', (contact_id,)).fetchone()
            if not party or party['kind'] != ('centre' if job['route'] == 'warranty_centre' else 'vendor'):
                raise RuleError('Select the active external repairer assigned to this job.')
            from .contacts import snapshot
            partner = snapshot(c, contact_id)
        return dict(contact_id=contact_id, contact_name=party['name'], route=job['route'],
                    assignment_id=existing.get('assignment_id') if existing and not verify_manifest else job.get('assignment_id'),
                    contact_snapshot=json.dumps(partner, ensure_ascii=False),
                    transporter_id=operator['id'] if operator else None,
                    transporter_snapshot=json.dumps(operator_shot, ensure_ascii=False),
                    reference=str(p.get('reference', '')).strip(), transport_mode=mode,
                    transport=json.dumps(transport), amount=amount, paid_by=paid_by,
                    expected_return=p.get('expected_return') or None,
                    condition=str(p.get('condition', '')).strip(), notes=str(p.get('notes', '')).strip(),
                    manifest=json.dumps(manifest), consent=int(bool(p.get('consent'))))

    @staticmethod
    def _check_manifest(c, job, manifest):
        if not manifest:
            raise RuleError('Select the physical items being sent.')
        held = {r['id']: r for r in (dict(x) for x in c.execute('''SELECT i.id,i.type,i.description,h.location,h.quantity
            FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND h.quantity>0''', (job['id'],)).fetchall())}
        for item in manifest:
            row = held.get(item)
            if not row or not in_shop(row['location']):
                raise RuleError('The shop does not currently hold every selected item. Refresh the dispatch manifest.')
        if not any(held[i]['type'] == 'device' for i in manifest):
            raise RuleError('Include the physical device in this dispatch.')

    # ---- writes ---------------------------------------------------------
    def prepare(self, c, job, values):
        """Create or update the editable dispatch for this job's current cycle."""
        active = c.execute('''SELECT * FROM dispatches WHERE job_id=? AND current=1
            ORDER BY cycle DESC LIMIT 1''', (job['id'],)).fetchone()
        if active and active['status'] in SENT:
            raise RuleError('This dispatch has already been sent. Use Amend dispatch to correct its details.')
        fields = self._clean(c, job, values, self._readable(active) if active else None)
        if active:
            c.execute('UPDATE dispatches SET ' + ','.join(k + '=?' for k in fields) + ",status='READY' WHERE id=?",
                      (*fields.values(), active['id']))
            self.s.audit(c, 'job', job['id'], 'dispatch_edited_before_send',
                         {'dispatch_id': active['id'], 'version': active['version'], **self._public(fields)})
            return active['id']
        cycle = (c.execute('SELECT COALESCE(max(cycle),0) FROM dispatches WHERE job_id=?', (job['id'],)).fetchone()[0] or 0) + 1
        ident = insert(c, 'dispatches', job_id=job['id'], cycle=cycle, version=1, current=1, status='READY',
                       created=now(), actor=self.s.user['id'], **fields)
        self.s.audit(c, 'job', job['id'], 'dispatch_created',
                     {'dispatch_id': ident, 'cycle': cycle, 'version': 1, **self._public(fields)})
        return ident

    def confirm(self, c, job, happened=None):
        """Mark the current dispatch physically sent. Called with the custody movement."""
        active = c.execute('''SELECT * FROM dispatches WHERE job_id=? AND current=1
            ORDER BY cycle DESC LIMIT 1''', (job['id'],)).fetchone()
        if not active:
            raise RuleError('Create the dispatch record first.')
        if active['status'] in SENT:
            return active['id']
        c.execute("UPDATE dispatches SET status='DISPATCHED',actual_dispatch_at=? WHERE id=?",
                  (happened or now(), active['id']))
        self.s.audit(c, 'job', job['id'], 'dispatch_confirmed',
                     {'dispatch_id': active['id'], 'version': active['version'], 'sent_at': happened or now()})
        return active['id']

    def close(self, c, job, status='RETURNED'):
        """End the current dispatch cycle once the items are back or the send is abandoned."""
        active = c.execute('''SELECT * FROM dispatches WHERE job_id=? AND current=1
            ORDER BY cycle DESC LIMIT 1''', (job['id'],)).fetchone()
        if not active or (status == 'CANCELLED' and active['status'] in SENT):
            return None
        c.execute('UPDATE dispatches SET status=?,current=0 WHERE id=?', (status, active['id']))
        self.s.audit(c, 'job', job['id'], 'dispatch_' + status.lower(), {'dispatch_id': active['id']})
        return active['id']

    def edit(self, job_id, values, version=None):
        """Normal editing, allowed only before the physical handover."""
        self.s.require_permission('handover')
        with self.db.transaction() as c:
            job = self.s._job(c, job_id, version)
            active = c.execute('SELECT * FROM dispatches WHERE job_id=? AND current=1 ORDER BY cycle DESC LIMIT 1', (job_id,)).fetchone()
            if not active:
                raise RuleError('There is no dispatch record to edit for this job.')
            if active['status'] in SENT:
                raise RuleError('This dispatch has already been sent. Use Amend dispatch to correct its details.')
            return self.prepare(c, dict(job), values)

    def amend(self, job_id, values, reason, operation_id=None):
        """Correct a sent dispatch by superseding it. The custody ledger is untouched."""
        self.s.require_permission('handover')
        if not reason or not reason.strip():
            raise RuleError('Record why this sent dispatch is being corrected.')
        with self.db.transaction() as c:
            if operation_id:
                done = c.execute("SELECT result_id FROM commands WHERE operation_id=? AND kind='dispatch_amend'", (operation_id,)).fetchone()
                if done:
                    return done[0]
            job = dict(self.s._job(c, job_id))
            active = c.execute('SELECT * FROM dispatches WHERE job_id=? AND current=1 ORDER BY cycle DESC LIMIT 1', (job_id,)).fetchone()
            if not active:
                raise RuleError('There is no dispatch record to amend for this job.')
            if active['status'] not in SENT:
                raise RuleError('This dispatch has not been sent yet. Edit it directly instead.')
            previous = self._readable(active)
            requested = values.get('contact_id', active['contact_id'])
            if requested != active['contact_id']:
                raise RuleError(
                    'The device is physically recorded with ' + (active['contact_name'] or 'the current repairer') +
                    '. Changing the responsible repairer is a physical movement: receive the device back and '
                    'dispatch it again, or ask the owner to record a custody exception.')
            fields = self._clean(c, job, dict(values, contact_id=active['contact_id']), previous, verify_manifest=False)
            if json.loads(fields['manifest']) != previous['manifest']:
                raise RuleError('The items actually sent are physical history. Record a further handover instead of editing the manifest.')
            c.execute('UPDATE dispatches SET current=0 WHERE id=?', (active['id'],))
            c.execute("UPDATE dispatches SET status='SUPERSEDED' WHERE id=?", (active['id'],))
            ident = insert(c, 'dispatches', job_id=job_id, cycle=active['cycle'], version=active['version'] + 1,
                           current=1, status=active['status'], created=now(), actor=self.s.user['id'],
                           supersedes_id=active['id'], amendment_reason=reason.strip(),
                           actual_dispatch_at=active['actual_dispatch_at'], **fields)
            changed = {k: [previous.get(k), v] for k, v in self._public(fields).items() if previous.get(k) != v}
            self.s.audit(c, 'job', job_id, 'dispatch_amended',
                         {'dispatch_id': ident, 'supersedes': active['id'], 'version': active['version'] + 1,
                          'reason': reason.strip(), 'changes': changed})
            if operation_id:
                insert(c, 'commands', operation_id=operation_id, kind='dispatch_amend', result_id=ident)
            return ident

    def cancel(self, job_id, reason):
        self.s.require_permission('cancel_records')
        if not reason.strip():
            raise RuleError('Record why this dispatch is cancelled.')
        with self.db.transaction() as c:
            job = dict(self.s._job(c, job_id))
            active = c.execute('SELECT * FROM dispatches WHERE job_id=? AND current=1 ORDER BY cycle DESC LIMIT 1', (job_id,)).fetchone()
            if not active:
                raise RuleError('There is no dispatch record to cancel for this job.')
            if active['status'] in SENT:
                raise RuleError('A sent dispatch cannot be cancelled. Record the physical return instead.')
            c.execute("UPDATE dispatches SET status='CANCELLED',current=0,notes=? WHERE id=?",
                      (reason.strip(), active['id']))
            self.s.audit(c, 'job', job_id, 'dispatch_cancelled', {'dispatch_id': active['id'], 'reason': reason.strip()})
            return active['id']

    @staticmethod
    def _public(fields):
        """Audit-friendly view: the partner snapshot is on the dispatch row, only names go to the timeline."""
        values = dict(fields)
        values['transport'] = json.loads(values['transport'])
        values['manifest'] = json.loads(values['manifest'])
        values.pop('contact_snapshot', None)
        values['transporter'] = json.loads(values.pop('transporter_snapshot') or '{}').get('name', '')
        return values
