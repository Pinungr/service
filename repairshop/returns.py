"""Physical verification of items coming back from a third party or service centre.

The expected list comes from the outbound dispatch manifest. Custody only changes when
the owner confirms an actual receipt: opening this screen changes nothing. Items that did
not come back are recorded as explicit discrepancies rather than silently ticked off.
"""
import json
from .domain import RuleError, now
from .persistence import insert

DISCREPANCIES = ('missing', 'damaged', 'wrong_item', 'quantity', 'other')


class Returns:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def expected(self, job_id):
        """Outbound manifest joined to what is currently away, for the receive screen."""
        self.s.require()
        from .dispatch import Dispatches
        dispatch = Dispatches(self.s).current(job_id)
        held = {r['id']: r for r in self.db.rows('''SELECT i.id,i.type,i.description,i.serial,h.location,h.quantity
            FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND h.quantity>0''', (job_id,))}
        away = [r for r in held.values() if r['location'].startswith(('vendor:', 'centre:', 'transit:'))]
        manifest = dispatch['manifest'] if dispatch else [r['id'] for r in away]
        rows = []
        for item_id in manifest:
            row = held.get(item_id)
            if row and not row['location'].startswith(('vendor:', 'centre:', 'transit:')):
                # Already back at the shop, delivered, or resolved as a custody exception.
                continue
            rows.append(dict(item_id=item_id,
                             description=(row or {}).get('description', 'Item no longer listed'),
                             type=(row or {}).get('type', ''), serial=(row or {}).get('serial', ''),
                             location=(row or {}).get('location', 'Not held'),
                             expected=(row or {}).get('quantity', 0),
                             available=bool(row) and row['location'].startswith(('vendor:', 'centre:', 'transit:'))))
        # Anything away but not on the manifest still has to be accounted for.
        for row in away:
            if row['id'] not in manifest:
                rows.append(dict(item_id=row['id'], description=row['description'], type=row['type'],
                                 serial=row['serial'], location=row['location'], expected=row['quantity'],
                                 available=True))
        return dict(job_id=job_id, dispatch=dispatch, items=rows,
                    party=(dispatch or {}).get('party') or (dispatch or {}).get('contact_name') or '')

    def verify(self, job_id, received, operation_id, receiver_kind='storage', receiver_name='',
               receiver_mobile='', storage='', notes='', discrepancies=()):
        """Record the physical check. Returns the verification id; custody is moved by the caller."""
        self.s.require('owner', 'counter')
        expected = self.expected(job_id)
        by_item = {r['item_id']: r for r in expected['items']}
        received = {int(k): int(v) for k, v in dict(received).items()}
        if set(received) - set(by_item):
            raise RuleError('Verify only the items recorded on the outbound dispatch.')
        reported = self._clean_discrepancies(discrepancies, by_item)
        # Items the owner brought into this receipt must balance. Items left out entirely
        # are a staged return: they stay recorded as still away and keep blocking handover,
        # which is different from claiming fewer units came back than were sent.
        unaccounted = []
        for item_id, count in received.items():
            row = by_item[item_id]
            if count > row['expected']:
                raise RuleError('More units cannot be received than were dispatched. Report a discrepancy instead.')
            if count < row['expected'] and item_id not in {d['item_id'] for d in reported}:
                unaccounted.append(row['description'])
        if unaccounted:
            raise RuleError('One or more dispatched items have not been verified: '
                            + ', '.join(unaccounted) + '. Confirm the units received or report a discrepancy.')
        if receiver_kind not in ('storage', 'person'):
            raise RuleError('Record whether the shop storage or a named person received the items.')
        if receiver_kind == 'storage' and (not storage.startswith('shop:') or not storage[5:].strip()):
            raise RuleError('Choose the shop storage location that received the items.')
        if receiver_kind == 'person' and not receiver_name.strip():
            raise RuleError('Record the name of the person who received the items.')
        with self.db.transaction() as c:
            done = c.execute('SELECT id FROM return_verifications WHERE operation_id=?', (operation_id,)).fetchone()
            if done:
                return done[0]
            self.s._job(c, job_id)
            complete = bool(by_item) and all(received.get(i, 0) == r['expected'] for i, r in by_item.items())
            ident = insert(c, 'return_verifications', job_id=job_id,
                           dispatch_id=(expected['dispatch'] or {}).get('id'), operation_id=operation_id,
                           complete=int(complete and not reported), receiver_kind=receiver_kind,
                           receiver_name=receiver_name.strip(), receiver_mobile=receiver_mobile.strip(),
                           storage=storage, checked=json.dumps(received), notes=notes.strip(),
                           created=now(), actor=self.s.user['id'])
            for item in reported:
                insert(c, 'return_discrepancies', verification_id=ident, created=now(), **item)
            self.s.audit(c, 'job', job_id, 'return_verified',
                         {'verification_id': ident, 'complete': complete, 'received': received,
                          'discrepancies': [dict(d, item_id=d['item_id']) for d in reported],
                          'receiver': receiver_name or storage})
            return ident

    @staticmethod
    def _clean_discrepancies(discrepancies, by_item):
        result = []
        for entry in discrepancies or []:
            kind = entry.get('kind')
            if kind not in DISCREPANCIES:
                raise RuleError('Choose a supported discrepancy type.')
            item_id = entry.get('item_id')
            if item_id is not None and int(item_id) not in by_item:
                raise RuleError('Report a discrepancy against a dispatched item.')
            if not str(entry.get('notes', '')).strip():
                raise RuleError('Explain every reported discrepancy.')
            result.append(dict(item_id=int(item_id) if item_id is not None else None, kind=kind,
                               expected=int(entry.get('expected', by_item.get(int(item_id or 0), {}).get('expected', 0))),
                               received=int(entry.get('received', 0)), notes=str(entry['notes']).strip(),
                               photo_id=entry.get('photo_id')))
        return result

    def verifications(self, job_id):
        rows = self.db.rows('SELECT * FROM return_verifications WHERE job_id=? ORDER BY id', (job_id,))
        if not rows:
            return []
        found = self.db.rows('''SELECT d.*,i.description FROM return_discrepancies d
            LEFT JOIN items i ON i.id=d.item_id
            WHERE d.verification_id IN (SELECT id FROM return_verifications WHERE job_id=?) ORDER BY d.id''', (job_id,))
        grouped = {}
        for row in found:
            grouped.setdefault(row['verification_id'], []).append(row)
        for row in rows:
            row['checked'] = json.loads(row['checked'] or '{}')
            row['discrepancies'] = grouped.get(row['id'], [])
        return rows

    def open_discrepancies(self, job_id):
        return self.db.rows('''SELECT d.*,i.description FROM return_discrepancies d
            JOIN return_verifications v ON v.id=d.verification_id
            LEFT JOIN items i ON i.id=d.item_id
            WHERE v.job_id=? AND d.resolved='' ORDER BY d.id''', (job_id,))
