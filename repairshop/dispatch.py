"""Versioned third-party / service-centre dispatch records, owned by one repair job.

A dispatch is administrative information about sending one job's items to one
external repairer. It is never a substitute for the custody ledger: the physical
handover stays in movements/holdings and is not rewritten by a correction here.

Before the physical handover a draft may be edited in place. Afterwards a
correction creates a new version that supersedes the previous one, with a
mandatory reason, and both versions remain readable.
"""
import json
from .domain import RuleError, now, money, in_shop
from .persistence import insert

TRANSPORT_MODES = {
    'BY_HAND': ('person_name', 'mobile', 'handover_date'),
    'BUS': ('bus_name', 'bus_number', 'mobile', 'dispatch_date'),
    'COURIER': ('courier_name', 'docket_number', 'docket_date', 'dispatch_date'),
    'OTHER': ('details',),
}
EDITABLE = ('reference', 'transport_mode', 'transport', 'amount', 'expected_return',
            'condition', 'notes', 'manifest', 'consent', 'contact_id')
SENT = ('DISPATCHED', 'RETURNED')


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

    @staticmethod
    def _readable(row):
        row = dict(row)
        try:
            row['transport'] = json.loads(row['transport'] or '{}')
        except ValueError:
            row['transport'] = {}
        try:
            row['manifest'] = json.loads(row['manifest'] or '[]')
        except ValueError:
            row['manifest'] = []
        row['transport_summary'] = ' · '.join(
            k.replace('_', ' ').title() + ': ' + str(v) for k, v in row['transport'].items() if v)
        row['label'] = f"Version {row['version']}" + ('' if row['current'] else ' · superseded')
        row['editable'] = row['status'] in ('DRAFT', 'READY')
        return row

    # ---- validation -----------------------------------------------------
    def _clean(self, c, job, values, existing=None, verify_manifest=True):
        p = dict(existing or {})
        for key in EDITABLE:
            if key in values:
                p[key] = values[key]
        mode = (p.get('transport_mode') or 'BY_HAND').upper()
        if mode not in TRANSPORT_MODES:
            raise RuleError('Choose a supported transport mode.')
        transport = p.get('transport') or {}
        if not isinstance(transport, dict):
            raise RuleError('Transport details must be recorded as named fields.')
        transport = {k: str(v).strip() for k, v in transport.items() if str(v).strip()}
        unknown = set(transport) - set(TRANSPORT_MODES[mode])
        if unknown:
            raise RuleError('Unsupported transport detail for ' + mode.replace('_', ' ').title() + ': ' + ', '.join(sorted(unknown)))
        amount = p.get('amount', 0)
        if isinstance(amount, str):
            amount = money(amount or '0')
        if not isinstance(amount, int) or amount < 0:
            raise RuleError('Enter the transport amount as a nonnegative whole-paise value.')
        manifest = sorted({int(i) for i in (p.get('manifest') or [])})
        if verify_manifest:
            # Only a not-yet-sent manifest is checked against live holdings: after the
            # handover the items are legitimately no longer in the shop.
            self._check_manifest(c, job, manifest)
        elif not manifest:
            raise RuleError('Select the physical items being sent.')
        contact_id = p.get('contact_id')
        party = c.execute('SELECT name,kind FROM masters WHERE id=? AND active=1', (contact_id,)).fetchone()
        if not party or party['kind'] != ('centre' if job['route'] == 'warranty_centre' else 'vendor'):
            raise RuleError('Select the active external repairer assigned to this job.')
        return dict(contact_id=contact_id, contact_name=party['name'], route=job['route'],
                    reference=str(p.get('reference', '')).strip(), transport_mode=mode,
                    transport=json.dumps(transport), amount=amount,
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
        self.s.require('owner')
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
        values = dict(fields)
        values['transport'] = json.loads(values['transport'])
        values['manifest'] = json.loads(values['manifest'])
        return values
