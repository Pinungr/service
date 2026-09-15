"""Versioned third-party / service-centre quotations.

These are what the external repairer charges the SHOP. They are internal cost records
and are never shown as a customer charge by themselves: the customer price is decided
separately in the existing customer quotation, so the shop's margin stays private.

Parts quoted here are supplied by the third party. They are deliberately not written to
the shop inventory ledger, because the shop never physically procured them into stock.
"""
import json
from .domain import RuleError, now
from .persistence import insert

LINE_KINDS = ('part', 'labour', 'transport', 'other')


class PartyQuotes:
    def __init__(self, service):
        self.s, self.db = service, service.db

    # ---- reads ----------------------------------------------------------
    def current(self, job_id):
        row = self.db.one("SELECT * FROM party_quotes WHERE job_id=? AND state='current'", (job_id,))
        return self._with_lines(row) if row else None

    def history(self, job_id):
        rows = self.db.rows('SELECT * FROM party_quotes WHERE job_id=? ORDER BY version', (job_id,))
        if not rows:
            return []
        # One extra query for every version, not one per line: no N+1 per row.
        lines = self.db.rows('''SELECT l.* FROM party_quote_lines l JOIN party_quotes q ON q.id=l.quote_id
            WHERE q.job_id=? ORDER BY l.id''', (job_id,))
        grouped = {}
        for line in lines:
            grouped.setdefault(line['quote_id'], []).append(line)
        return [dict(r, lines=grouped.get(r['id'], []), label=f"V{r['version']}" + ('' if r['state'] == 'current' else ' · ' + r['state'])) for r in rows]

    def _with_lines(self, row):
        row = dict(row)
        row['lines'] = self.db.rows('SELECT * FROM party_quote_lines WHERE quote_id=? ORDER BY id', (row['id'],))
        row['label'] = f"V{row['version']}" + ('' if row['state'] == 'current' else ' · ' + row['state'])
        return row

    # ---- writes ---------------------------------------------------------
    @staticmethod
    def _clean_lines(lines):
        result = []
        for line in lines or []:
            kind = line.get('kind', 'part')
            if kind not in LINE_KINDS:
                raise RuleError('Each quotation line must be a part, labour, transport or other charge.')
            name = str(line.get('name', '')).strip()
            if not name:
                raise RuleError('Name every third-party quotation line.')
            quantity = line.get('quantity', 1)
            if not isinstance(quantity, int) or quantity < 1:
                raise RuleError('Quotation quantities must be positive whole numbers.')
            for key in ('unit_cost', 'customer_charge'):
                value = line.get(key, 0)
                if not isinstance(value, int) or value < 0:
                    raise RuleError('Quotation amounts must be nonnegative whole paise.')
            result.append(dict(kind=kind, name=name, quantity=quantity,
                               unit_cost=line.get('unit_cost', 0), customer_charge=line.get('customer_charge', 0),
                               warranty=str(line.get('warranty', '')).strip(), notes=str(line.get('notes', '')).strip()))
        return result

    def issue(self, job_id, lines, labour=0, transport=0, other=0, reference='', notes='', reason=''):
        """Issue version 1, or supersede the current version with a new one."""
        self.s.require('owner')
        for value in (labour, transport, other):
            if not isinstance(value, int) or value < 0:
                raise RuleError('Third-party labour, transport and other costs must be nonnegative whole paise.')
        lines = self._clean_lines(lines)
        with self.db.transaction() as c:
            j = self.s._job(c, job_id)
            if j['route'] == 'in_house':
                raise RuleError('Third-party quotations apply to a third-party or service-centre repair.')
            if j['stage'] in ('closed', 'collected'):
                raise RuleError('This repair is closed. Its quotation history remains readable.')
            previous = c.execute("SELECT * FROM party_quotes WHERE job_id=? AND state='current'", (job_id,)).fetchone()
            if previous and not reason.strip():
                raise RuleError('Record why the third-party quotation is being revised.')
            parts_total = sum(l['unit_cost'] * l['quantity'] for l in lines)
            total = parts_total + labour + transport + other
            version = (c.execute('SELECT COALESCE(max(version),0) FROM party_quotes WHERE job_id=?', (job_id,)).fetchone()[0] or 0) + 1
            if previous:
                c.execute("UPDATE party_quotes SET state='superseded' WHERE id=?", (previous['id'],))
            assignment = c.execute('SELECT contact_id FROM assignments WHERE id=?', (j['assignment_id'],)).fetchone()
            dispatch = c.execute('SELECT id FROM dispatches WHERE job_id=? AND current=1 ORDER BY cycle DESC LIMIT 1', (job_id,)).fetchone()
            ident = insert(c, 'party_quotes', job_id=job_id, dispatch_id=dispatch[0] if dispatch else None,
                           contact_id=assignment[0] if assignment else None, version=version, state='current',
                           labour=labour, transport=transport, other=other, parts_total=parts_total, total=total,
                           reference=reference.strip(), notes=notes.strip(),
                           supersedes_id=previous['id'] if previous else None,
                           revision_reason=reason.strip(), created=now(), actor=self.s.user['id'])
            for line in lines:
                insert(c, 'party_quote_lines', quote_id=ident, **line)
            self.s.audit(c, 'job', job_id, 'party_quote_issued',
                         {'quote_id': ident, 'version': version, 'total': total, 'parts': len(lines),
                          'supersedes': previous['id'] if previous else None, 'reason': reason.strip()})
            return ident

    def cancel(self, job_id, reason):
        self.s.require('owner')
        if not reason.strip():
            raise RuleError('Record why the third-party quotation is being cancelled.')
        with self.db.transaction() as c:
            self.s._job(c, job_id)
            current = c.execute("SELECT id FROM party_quotes WHERE job_id=? AND state='current'", (job_id,)).fetchone()
            if not current:
                raise RuleError('There is no current third-party quotation for this repair.')
            c.execute("UPDATE party_quotes SET state='cancelled' WHERE id=?", (current[0],))
            self.s.audit(c, 'job', job_id, 'party_quote_cancelled', {'quote_id': current[0], 'reason': reason.strip()})
            return current[0]

    # ---- projections ----------------------------------------------------
    def customer_lines(self, job_id):
        """Quotation lines the owner marked as chargeable onward to the customer."""
        quote = self.current(job_id)
        if not quote:
            return []
        return [dict(description=l['name'] + (f" × {l['quantity']}" if l['quantity'] > 1 else ''),
                     amount=l['customer_charge'] * l['quantity'], kind=l['kind'], source='third_party',
                     part_warranty=l['warranty'])
                for l in quote['lines'] if l['customer_charge']]

    def internal_total(self, job_id):
        quote = self.current(job_id)
        return quote['total'] if quote else 0
