"""Contacts & Services: reusable partner profiles and historical partner snapshots.

Every change is additive and lossless:

* Directory contacts gain real columns for the profile that used to live in a JSON blob
  inside `masters.details` (contact person, email, notes), plus alternate mobile, city,
  service-centre capabilities and bus-service route details. The JSON is lifted into those
  columns before it is cleared; a centre's "company / OEM" becomes a supported brand, any
  other company name is kept in notes.
* `master_supports` records which categories, brands and services a partner works on. It
  is used to recommend partners, never to hide them.
* Assignments and dispatches store a snapshot of the partner (and of the bus service) as
  it was, so later directory edits never rewrite repair history. Assignments recorded
  before this version had no snapshot; they are given one from the directory as it stands
  at upgrade time, which is the most accurate record still available.
* A dispatch is linked to the assignment (repair attempt) it was sent under.
* The unused `transport_method` list is deactivated. Dispatch's built-in transport modes
  were always the ones enforced, so no dispatch changes meaning.
"""
import json
from .persistence import migration, run_script

MASTER_COLUMNS = [
    ('contact_person', "TEXT NOT NULL DEFAULT ''"),
    ('alternate', "TEXT NOT NULL DEFAULT ''"),
    ('email', "TEXT NOT NULL DEFAULT ''"),
    ('city', "TEXT NOT NULL DEFAULT ''"),
    ('notes', "TEXT NOT NULL DEFAULT ''"),
    ('warranty_service', 'INTEGER NOT NULL DEFAULT 0'),
    ('pickup', 'INTEGER NOT NULL DEFAULT 0'),
    ('turnaround_days', 'INTEGER NOT NULL DEFAULT 0 CHECK(turnaround_days>=0)'),
    ('route_from', "TEXT NOT NULL DEFAULT ''"),
    ('route_to', "TEXT NOT NULL DEFAULT ''"),
    ('pickup_point', "TEXT NOT NULL DEFAULT ''"),
    ('drop_point', "TEXT NOT NULL DEFAULT ''"),
    ('vehicle_number', "TEXT NOT NULL DEFAULT ''"),
    ('created', 'TEXT'),
    ('updated', 'TEXT'),
]
ASSIGNMENT_COLUMNS = [
    ('contact_snapshot', "TEXT NOT NULL DEFAULT '{}'"),
    ('expected_return', 'TEXT'),
    ('instructions', "TEXT NOT NULL DEFAULT ''"),
]
DISPATCH_COLUMNS = [
    ('assignment_id', 'INTEGER REFERENCES assignments(id)'),
    ('contact_snapshot', "TEXT NOT NULL DEFAULT '{}'"),
    ('transporter_id', 'INTEGER REFERENCES masters(id)'),
    ('transporter_snapshot', "TEXT NOT NULL DEFAULT '{}'"),
]

SCHEMA = '''
CREATE TABLE IF NOT EXISTS master_supports(master_id INTEGER NOT NULL REFERENCES masters(id),
    target_id INTEGER NOT NULL REFERENCES masters(id), PRIMARY KEY(master_id,target_id));
CREATE INDEX IF NOT EXISTS ix_master_support_target ON master_supports(target_id,master_id);
CREATE INDEX IF NOT EXISTS ix_assignment_contact ON assignments(contact_id,job_id);
CREATE INDEX IF NOT EXISTS ix_dispatch_contact ON dispatches(contact_id,job_id);
CREATE INDEX IF NOT EXISTS ix_dispatch_transporter ON dispatches(transporter_id);
'''

ASSIGNMENT_TRIGGER = ("CREATE TRIGGER immutable_assignments_update BEFORE UPDATE ON assignments "
                      "BEGIN SELECT RAISE(ABORT,'Immutable record: add a correcting event'); END")

# The partner and bus-service snapshots join the details a sent dispatch can never rewrite.
DISPATCH_TRIGGER = '''CREATE TRIGGER dispatch_history_update BEFORE UPDATE ON dispatches
    WHEN OLD.status IN ('DISPATCHED','SUPERSEDED','RETURNED','CANCELLED') AND (
        NEW.job_id IS NOT OLD.job_id OR NEW.cycle IS NOT OLD.cycle OR NEW.version IS NOT OLD.version
        OR NEW.contact_id IS NOT OLD.contact_id OR NEW.contact_name IS NOT OLD.contact_name
        OR NEW.contact_snapshot IS NOT OLD.contact_snapshot OR NEW.assignment_id IS NOT OLD.assignment_id
        OR NEW.transporter_id IS NOT OLD.transporter_id OR NEW.transporter_snapshot IS NOT OLD.transporter_snapshot
        OR NEW.reference IS NOT OLD.reference OR NEW.transport_mode IS NOT OLD.transport_mode
        OR NEW.transport IS NOT OLD.transport OR NEW.amount IS NOT OLD.amount
        OR NEW.manifest IS NOT OLD.manifest OR NEW.condition IS NOT OLD.condition
        OR NEW.actual_dispatch_at IS NOT OLD.actual_dispatch_at OR NEW.created IS NOT OLD.created)
    BEGIN SELECT RAISE(ABORT,'Sent dispatch details are historical: record an amendment instead'); END'''


def _columns(c, table):
    return {row[1] for row in c.execute(f'PRAGMA table_info({table})')}


def _add(c, table, columns):
    present = _columns(c, table)
    for name, definition in columns:
        if name not in present:
            c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')


def migrate(c):
    with migration(c, 15):
        _add(c, 'masters', MASTER_COLUMNS)
        _add(c, 'assignments', ASSIGNMENT_COLUMNS)
        _add(c, 'dispatches', DISPATCH_COLUMNS)
        run_script(c, SCHEMA)
        lifted = _lift_profiles(c)
        retired = c.execute("UPDATE masters SET active=0 WHERE kind='transport_method' AND active=1").rowcount
        snapshots = _snapshot_assignments(c)
        dispatches = _snapshot_dispatches(c)
        c.execute("""INSERT INTO audit(created,entity,entity_id,action,payload)
            VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'schema',15,'migration',?)""",
            (json.dumps({'change': 'Contacts & Services: repairer, service centre, supplier and bus-service '
                         'profiles moved from the details text into their own fields; partners can list '
                         'supported categories, brands and services; every repair assignment and dispatch '
                         'keeps a snapshot of the partner as it was. Assignments recorded earlier were '
                         'given a snapshot of the directory as it stood at upgrade. The unused transport '
                         'method list was deactivated: Courier, Bus and In hand remain the dispatch methods.',
                         'profiles_lifted': lifted, 'transport_methods_retired': retired,
                         'assignment_snapshots': snapshots, 'dispatch_snapshots': dispatches}),))


def _lift_profiles(c):
    """Move the JSON profile out of `details` into columns, losing nothing."""
    from .domain import norm
    lifted = 0
    rows = c.execute("""SELECT id,kind,details,specialization,notes FROM masters
        WHERE kind IN ('vendor','centre','supplier','transporter') AND details!=''""").fetchall()
    for row in rows:
        try:
            profile = json.loads(row['details'])
        except ValueError:
            profile = None
        if not isinstance(profile, dict):
            # Free text written before the structured form existed: it was always notes.
            c.execute("UPDATE masters SET notes=CASE WHEN notes='' THEN ? ELSE notes || char(10) || ? END,details='' WHERE id=?",
                      (row['details'], row['details'], row['id']))
            lifted += 1
            continue
        notes = [str(profile.get('notes') or '').strip()]
        company = str(profile.get('company') or '').strip()
        if company and row['kind'] == 'centre':
            brand = c.execute("SELECT id FROM masters WHERE kind='brand' AND normalized=?", (norm(company),)).fetchone()
            brand_id = brand[0] if brand else c.execute(
                "INSERT INTO masters(kind,name,normalized,created,updated) VALUES ('brand',?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'),strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (company, norm(company))).lastrowid
            c.execute('INSERT OR IGNORE INTO master_supports(master_id,target_id) VALUES (?,?)', (row['id'], brand_id))
        elif company:
            notes.insert(0, 'Company: ' + company)
        # Any key the old form never had is still kept, readable, in notes.
        extra = {k: v for k, v in profile.items()
                 if k not in ('company', 'contact_person', 'email', 'notes', 'address', 'specialization') and v}
        notes += [k.replace('_', ' ').title() + ': ' + str(v) for k, v in extra.items()]
        merged = '\n'.join(x for x in [row['notes'] or '', *notes] if x)
        c.execute('''UPDATE masters SET contact_person=CASE WHEN contact_person='' THEN ? ELSE contact_person END,
                email=CASE WHEN email='' THEN ? ELSE email END, notes=?,
                specialization=CASE WHEN specialization='' THEN ? ELSE specialization END, details='' WHERE id=?''',
                  (str(profile.get('contact_person') or '').strip(), str(profile.get('email') or '').strip(), merged,
                   str(profile.get('specialization') or '').strip(), row['id']))
        lifted += 1
    return lifted


def _snapshot_assignments(c):
    from .contacts import snapshot
    rows = c.execute("SELECT id,contact_id FROM assignments WHERE contact_id IS NOT NULL AND contact_snapshot='{}'").fetchall()
    if not rows:
        return 0
    # The one-off backfill needs the immutability trigger lifted for its own statement only.
    c.execute('DROP TRIGGER IF EXISTS immutable_assignments_update')
    for row in rows:
        shot = snapshot(c, row['contact_id'])
        shot['captured'] = 'schema upgrade'
        c.execute('UPDATE assignments SET contact_snapshot=? WHERE id=?', (json.dumps(shot, ensure_ascii=False), row['id']))
    c.execute(ASSIGNMENT_TRIGGER)
    return len(rows)


def _snapshot_dispatches(c):
    """Link each dispatch to the assignment it was sent under and copy that partner snapshot."""
    c.execute('DROP TRIGGER IF EXISTS dispatch_history_update')
    rows = c.execute("SELECT id,job_id,contact_id,created FROM dispatches WHERE assignment_id IS NULL").fetchall()
    for row in rows:
        attempt = c.execute('''SELECT id,contact_snapshot FROM assignments WHERE job_id=? AND contact_id IS ?
            AND created<=? ORDER BY id DESC LIMIT 1''', (row['job_id'], row['contact_id'], row['created'])).fetchone() \
            or c.execute('SELECT id,contact_snapshot FROM assignments WHERE job_id=? AND contact_id IS ? ORDER BY id DESC LIMIT 1',
                         (row['job_id'], row['contact_id'])).fetchone()
        if attempt:
            c.execute("UPDATE dispatches SET assignment_id=?,contact_snapshot=CASE WHEN contact_snapshot='{}' THEN ? ELSE contact_snapshot END WHERE id=?",
                      (attempt['id'], attempt['contact_snapshot'], row['id']))
    c.execute(DISPATCH_TRIGGER)
    return len(rows)
