"""Correct visit estimate totals, link directory technicians to login accounts.

Two production-readiness corrections, both additive:

* `visits.estimated_total` was populated from the customer's deposit instead of the
  repair's initial estimate. The two are different figures and are recomputed here from
  the child jobs, which is the authoritative source. No deposit, payment, quotation or
  invoice record is touched: `jobs.deposit` still holds every deposit exactly as recorded.
* A directory technician (`masters` with kind `technician`) had no relationship to a login
  account, so job ownership could not be checked for technicians assigned that way.
  `masters.user_id` records that link.
"""
import json
from .persistence import migration, run_script

SCHEMA = '''
CREATE INDEX IF NOT EXISTS ix_master_user ON masters(user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ix_technician_user ON masters(user_id)
    WHERE user_id IS NOT NULL AND kind='technician';
'''


def _columns(c, table):
    return {row[1] for row in c.execute(f'PRAGMA table_info({table})')}


def recalculate_visit_estimates(c):
    """Rebuild every visit estimate from its own jobs. Safe to run repeatedly."""
    return c.execute('''UPDATE visits SET estimated_total=COALESCE(
        (SELECT sum(j.initial_estimate) FROM jobs j WHERE j.visit_id=visits.id),0)''').rowcount


def migrate(c):
    with migration(c, 13):
        if 'user_id' not in _columns(c, 'masters'):
            c.execute('ALTER TABLE masters ADD COLUMN user_id INTEGER REFERENCES users(id)')
        run_script(c, SCHEMA)
        corrected = c.execute('''SELECT count(*) FROM visits v WHERE v.estimated_total!=COALESCE(
            (SELECT sum(j.initial_estimate) FROM jobs j WHERE j.visit_id=v.id),0)''').fetchone()[0]
        recalculate_visit_estimates(c)
        c.execute("""INSERT INTO audit(created,entity,entity_id,action,payload)
            VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'schema',13,'migration',?)""",
            (json.dumps({'change': 'Visit estimated totals recomputed from the initial estimate of '
                         'each repair job instead of the customer deposit, and directory '
                         'technicians can now be linked to a login account so job ownership is '
                         'enforceable. Deposits, advances, quotations and invoices are unchanged.',
                         'visits_corrected': corrected}),))
