"""Customer visits grouping existing jobs, and versioned third-party dispatch records.

Historical jobs keep their identity, custody and financial references. Every existing
job is attached to a visit reconstructed from its own recorded intake reference, so no
two unrelated jobs are merged and no job is left without a visit.
"""
import json
from .persistence import migration, run_script


def _has_column(c, table, column):
    return any(row[1] == column for row in c.execute(f'PRAGMA table_info({table})'))


SCHEMA = '''
CREATE TABLE IF NOT EXISTS visits(id INTEGER PRIMARY KEY, number TEXT UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id), intake_ref TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL, actor INTEGER REFERENCES users(id), notes TEXT NOT NULL DEFAULT '',
    estimated_total INTEGER NOT NULL DEFAULT 0 CHECK(estimated_total>=0),
    advance_total INTEGER NOT NULL DEFAULT 0 CHECK(advance_total>=0),
    origin TEXT NOT NULL DEFAULT 'intake', cancelled_reason TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_visit_customer ON visits(customer_id,id);
CREATE INDEX IF NOT EXISTS ix_visit_created ON visits(created);
CREATE INDEX IF NOT EXISTS ix_visit_intake_ref ON visits(intake_ref);
CREATE TABLE IF NOT EXISTS dispatches(id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id), cycle INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL, current INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','READY','DISPATCHED','SUPERSEDED','RETURNED','CANCELLED')),
    route TEXT NOT NULL DEFAULT '', contact_id INTEGER REFERENCES masters(id),
    contact_name TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '',
    transport_mode TEXT NOT NULL DEFAULT '', transport TEXT NOT NULL DEFAULT '{}',
    amount INTEGER NOT NULL DEFAULT 0 CHECK(amount>=0), expected_return TEXT,
    condition TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    manifest TEXT NOT NULL DEFAULT '[]', consent INTEGER NOT NULL DEFAULT 0,
    supersedes_id INTEGER REFERENCES dispatches(id), amendment_reason TEXT NOT NULL DEFAULT '',
    actual_dispatch_at TEXT, created TEXT NOT NULL, actor INTEGER REFERENCES users(id),
    UNIQUE(job_id,cycle,version));
CREATE INDEX IF NOT EXISTS ix_dispatch_job ON dispatches(job_id,id);
CREATE INDEX IF NOT EXISTS ix_dispatch_status ON dispatches(status,job_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_dispatch_current ON dispatches(job_id,cycle) WHERE current=1;
'''

# Administrative dispatch data may be corrected only by superseding the row. The
# recorded physical handover time and party of a sent dispatch are never rewritten.
TRIGGERS = '''
CREATE TRIGGER dispatch_history_update BEFORE UPDATE ON dispatches
    WHEN OLD.status IN ('DISPATCHED','SUPERSEDED','RETURNED','CANCELLED') AND (
        NEW.job_id IS NOT OLD.job_id OR NEW.cycle IS NOT OLD.cycle OR NEW.version IS NOT OLD.version
        OR NEW.contact_id IS NOT OLD.contact_id OR NEW.contact_name IS NOT OLD.contact_name
        OR NEW.reference IS NOT OLD.reference OR NEW.transport_mode IS NOT OLD.transport_mode
        OR NEW.transport IS NOT OLD.transport OR NEW.amount IS NOT OLD.amount
        OR NEW.manifest IS NOT OLD.manifest OR NEW.condition IS NOT OLD.condition
        OR NEW.actual_dispatch_at IS NOT OLD.actual_dispatch_at OR NEW.created IS NOT OLD.created)
    BEGIN SELECT RAISE(ABORT,'Sent dispatch details are historical: record an amendment instead'); END;
CREATE TRIGGER dispatch_history_delete BEFORE DELETE ON dispatches
    BEGIN SELECT RAISE(ABORT,'Dispatch history is preserved; cancel or amend it instead'); END;
CREATE TRIGGER immutable_visit_number BEFORE UPDATE ON visits
    WHEN OLD.number IS NOT NULL AND NEW.number IS NOT OLD.number
    BEGIN SELECT RAISE(ABORT,'Visit number is immutable'); END;
CREATE TRIGGER visit_history_delete BEFORE DELETE ON visits
    BEGIN SELECT RAISE(ABORT,'Visit history is preserved; record a cancellation instead'); END;
'''


def visit_number(c, day, taken=None):
    """VIS-YYYYMMDD-NNNN. Unique per calendar day; safe inside a write transaction."""
    prefix = 'VIS-' + day.replace('-', '') + '-'
    highest = c.execute("SELECT max(CAST(substr(number,-4) AS INTEGER)) FROM visits WHERE number LIKE ?", (prefix + '%',)).fetchone()[0] or 0
    if taken is not None:
        highest = max(highest, taken.get(prefix, 0))
        taken[prefix] = highest + 1
    return f'{prefix}{highest + 1:04d}'


def _existing_triggers(c):
    return {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}


def migrate(c):
    with migration(c, 11):
        run_script(c, SCHEMA)
        if not _has_column(c, 'jobs', 'visit_id'):
            c.execute('ALTER TABLE jobs ADD COLUMN visit_id INTEGER REFERENCES visits(id)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_job_visit ON jobs(visit_id,id)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_job_intake_ref ON jobs(intake_ref)')
        present = _existing_triggers(c)
        for statement in filter(None, (s.strip() for s in TRIGGERS.split(';\n'))):
            name = statement.split()[2]
            if name not in present:
                c.execute(statement)
        _backfill_visits(c)
        _backfill_dispatches(c)
        c.execute("""INSERT INTO audit(created,entity,entity_id,action,payload)
            VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'schema',11,'migration',?)""",
            (json.dumps({'change': 'Customer visits now group repair jobs, and third-party dispatch '
                         'is a versioned record. Existing jobs, custody movements and financial '
                         'entries are unchanged; each historical job was attached to a visit '
                         'rebuilt from its own recorded intake reference.'}),))


def _backfill_visits(c):
    """One visit per recorded (customer, intake reference) group, in job order."""
    groups = c.execute('''SELECT customer_id,intake_ref,min(id) AS first_job,min(received) AS received,
        COALESCE(sum(deposit),0) AS estimated FROM jobs WHERE visit_id IS NULL
        GROUP BY customer_id,intake_ref ORDER BY min(id)''').fetchall()
    taken = {}
    for group in groups:
        day = (group['received'] or '')[:10] or '1970-01-01'
        number = visit_number(c, day, taken)
        actor = c.execute('SELECT actor FROM jobs WHERE id=?', (group['first_job'],)).fetchone()[0]
        visit = c.execute('''INSERT INTO visits(number,customer_id,intake_ref,created,actor,estimated_total,origin)
            VALUES (?,?,?,?,?,?,?)''', (number, group['customer_id'], group['intake_ref'] or '',
            group['received'] or '', actor, group['estimated'] or 0, 'migrated')).lastrowid
        c.execute('UPDATE jobs SET visit_id=? WHERE customer_id=? AND intake_ref=? AND visit_id IS NULL',
                  (visit, group['customer_id'], group['intake_ref']))


def _backfill_dispatches(c):
    """Rebuild an administrative dispatch record from saved guided-workflow evidence."""
    rows = c.execute("""SELECT j.id,j.route,j.stage,j.return_due,j.lifecycle_data,j.received,j.actor,j.assignment_id
        FROM jobs j WHERE j.route!='in_house' AND j.lifecycle_data LIKE '%"dispatch"%'""").fetchall()
    for row in rows:
        if c.execute('SELECT 1 FROM dispatches WHERE job_id=?', (row['id'],)).fetchone():
            continue
        try:
            manifest = json.loads(row['lifecycle_data']).get('dispatch') or {}
        except ValueError:
            continue
        if not isinstance(manifest, dict):
            continue
        assignment = c.execute('''SELECT a.contact_id,m.name FROM assignments a LEFT JOIN masters m ON m.id=a.contact_id
            WHERE a.id=?''', (row['assignment_id'],)).fetchone()
        sent = c.execute("""SELECT min(m.happened) FROM movements m JOIN items i ON i.id=m.item_id
            WHERE i.job_id=? AND (m.from_location LIKE 'shop:%' OR m.from_location LIKE 'staff:%' OR m.from_location LIKE 'technician:%')
            AND (m.to_location LIKE 'vendor:%' OR m.to_location LIKE 'centre:%' OR m.to_location LIKE 'transit:%')""",
            (row['id'],)).fetchone()[0]
        carrier = (manifest.get('carrier') or '').strip()
        c.execute('''INSERT INTO dispatches(job_id,cycle,version,current,status,route,contact_id,contact_name,
            reference,transport_mode,transport,amount,expected_return,condition,notes,manifest,consent,
            actual_dispatch_at,created,actor) VALUES (?,1,1,1,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?)''',
            (row['id'], 'DISPATCHED' if sent else 'READY', row['route'],
             assignment['contact_id'] if assignment else None, (assignment['name'] if assignment else '') or '',
             manifest.get('reference', ''), 'COURIER' if carrier else 'BY_HAND',
             json.dumps({'carrier': carrier} if carrier else {}), row['return_due'],
             manifest.get('condition', ''), manifest.get('notes', ''),
             json.dumps(manifest.get('items', [])), int(bool(manifest.get('consent'))),
             sent, sent or row['received'], row['actor']))
