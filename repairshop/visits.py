"""Customer visit / intake session grouping over the existing jobs table.

A visit answers who came, when, which products were received together and which
repair jobs belong to it. Repair progress stays authoritative on each job: the
visit-level status below is a read-only projection of its children.
"""
import json
from .domain import RuleError, now
from .persistence import insert
from .migration11 import visit_number

OPEN_STAGES = "j.stage NOT IN ('collected','closed')"


class Visits:
    def __init__(self, service):
        self.s, self.db = service, service.db

    # ---- creation -------------------------------------------------------
    def create(self, c, customer_id, intake_ref='', notes='', estimated_total=0, advance_total=0):
        """Create the visit inside the caller's intake transaction."""
        if not c.execute('SELECT 1 FROM customers WHERE id=?', (customer_id,)).fetchone():
            raise RuleError('Select an existing customer for this visit.')
        created = now()
        number = visit_number(c, created[:10])
        ident = insert(c, 'visits', number=number, customer_id=customer_id, intake_ref=intake_ref or '',
                       created=created, actor=self.s.user['id'] if self.s.user else None, notes=notes,
                       estimated_total=max(0, int(estimated_total or 0)), advance_total=max(0, int(advance_total or 0)))
        self.s.audit(c, 'visit', ident, 'visit_created',
                     {'number': number, 'customer_id': customer_id, 'intake_ref': intake_ref,
                      'estimated_total': estimated_total, 'advance_total': advance_total})
        return dict(id=ident, number=number)

    def attach(self, c, visit_id, job_id):
        c.execute('UPDATE jobs SET visit_id=? WHERE id=? AND visit_id IS NULL', (visit_id, job_id))
        self.s.audit(c, 'visit', visit_id, 'job_created_from_visit', {'job_id': job_id})

    def cancel(self, visit_id, reason):
        """Record an intake cancellation. Child jobs keep their own lifecycle and history."""
        self.s.require('owner')
        if not reason.strip():
            raise RuleError('Record why this visit is being cancelled.')
        with self.db.transaction() as c:
            visit = c.execute('SELECT * FROM visits WHERE id=?', (visit_id,)).fetchone()
            if not visit:
                raise RuleError('Visit not found.')
            c.execute('UPDATE visits SET cancelled_reason=? WHERE id=?', (reason, visit_id))
            self.s.audit(c, 'visit', visit_id, 'visit_cancelled', {'reason': reason})

    # ---- projections ----------------------------------------------------
    @staticmethod
    def status(total, closed, active):
        if not total:
            return 'Empty'
        if closed == total:
            return 'Completed'
        return 'Partly completed' if closed else 'Open'

    def _rows(self, where, args, limit=50, offset=0):
        """Lightweight list projection: one aggregate query, no per-job snapshots."""
        sql = f'''SELECT v.id,v.number,v.customer_id,v.created,v.notes,v.estimated_total,v.advance_total,
            v.cancelled_reason,c.name AS customer,c.phone,
            count(j.id) AS products,
            COALESCE(sum(CASE WHEN j.stage IN ('collected','closed') THEN 1 ELSE 0 END),0) AS closed_jobs,
            (SELECT group_concat(j2.device,' · ') FROM jobs j2 WHERE j2.visit_id=v.id) AS devices
            FROM visits v JOIN customers c ON c.id=v.customer_id LEFT JOIN jobs j ON j.visit_id=v.id
            WHERE {where} GROUP BY v.id ORDER BY v.id DESC'''
        if limit:
            sql += ' LIMIT ? OFFSET ?'
            args = list(args) + [limit, offset]
        rows = self.db.rows(sql, tuple(args))
        for row in rows:
            row['status'] = ('Cancelled · ' if row['cancelled_reason'] else '') + self.status(
                row['products'], row['closed_jobs'], row['products'] - row['closed_jobs'])
        return rows

    def search(self, text='', limit=50, offset=0):
        """Find visits by visit number, customer, phone, job number, product or serial."""
        self.s.require()
        if not text:
            return self._rows('1=1', (), limit, offset)
        like = '%' + text + '%'
        where = '''(v.number LIKE ? OR v.intake_ref LIKE ? OR c.name LIKE ? OR c.phone LIKE ?
            OR EXISTS(SELECT 1 FROM jobs jx WHERE jx.visit_id=v.id AND
                (jx.number LIKE ? OR jx.device LIKE ? OR jx.serial LIKE ?)))'''
        return self._rows(where, (like,) * 7, limit, offset)

    def for_customer(self, customer_id, limit=0, offset=0):
        self.s.require()
        return self._rows('v.customer_id=?', (customer_id,), limit, offset)

    def jobs(self, visit_id):
        """Child jobs with their own independent lifecycle stage."""
        self.s.require()
        return self.db.rows('''SELECT j.id,j.number,j.device,j.serial,j.stage,j.route,j.complaint,
            j.repair_due,j.collection_due,j.deposit,j.received,
            (SELECT name FROM masters WHERE id=j.category_id) AS category,
            (SELECT name FROM masters WHERE id=j.service_id) AS service
            FROM jobs j WHERE j.visit_id=? ORDER BY j.id''', (visit_id,))

    def detail(self, visit_id):
        self.s.require()
        rows = self._rows('v.id=?', (visit_id,), 0)
        if not rows:
            raise RuleError('Visit not found.')
        return dict(rows[0], jobs=self.jobs(visit_id))

    def for_job(self, job_id):
        """The visit a job belongs to, including its sibling jobs."""
        self.s.require()
        row = self.db.one('SELECT visit_id FROM jobs WHERE id=?', (job_id,))
        if not row:
            raise RuleError('Job not found.')
        return self.detail(row['visit_id']) if row['visit_id'] else None
