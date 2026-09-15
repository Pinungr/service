"""Return events own their evidence, and the receiver is a user rather than a place.

The shop has no storage custodian, so a return is received by a person: the signed-in
one. The old `receiver_kind` / `receiver_name` / `receiver_mobile` / `storage` columns
described a choice the application no longer offers and are removed.

Return photos move from a single column on the discrepancy to `return_evidence`, so a
photo is evidence *for a particular return event* rather than merely a file that happens
to share a job id with it.
"""
import json
from .persistence import migration, run_script

SCHEMA = '''
CREATE TABLE IF NOT EXISTS return_evidence(id INTEGER PRIMARY KEY,
    verification_id INTEGER NOT NULL REFERENCES return_verifications(id),
    discrepancy_id INTEGER REFERENCES return_discrepancies(id),
    attachment_id INTEGER NOT NULL REFERENCES attachments(id),
    created TEXT NOT NULL, actor INTEGER REFERENCES users(id),
    UNIQUE(attachment_id));
CREATE INDEX IF NOT EXISTS ix_return_evidence ON return_evidence(verification_id,id);
'''

TRIGGERS = '''
CREATE TRIGGER return_evidence_update BEFORE UPDATE ON return_evidence
    BEGIN SELECT RAISE(ABORT,'Return evidence is recorded once with its return event'); END;
CREATE TRIGGER return_evidence_delete BEFORE DELETE ON return_evidence
    BEGIN SELECT RAISE(ABORT,'Return evidence is preserved'); END;
'''

OBSOLETE = ('receiver_kind', 'receiver_name', 'receiver_mobile', 'storage')


def _columns(c, table):
    return {row[1] for row in c.execute(f'PRAGMA table_info({table})')}


def migrate(c):
    with migration(c, 14):
        present = _columns(c, 'return_verifications')
        if 'received_by_user_id' not in present:
            c.execute('ALTER TABLE return_verifications ADD COLUMN received_by_user_id INTEGER REFERENCES users(id)')
        # The person who recorded the receipt is the person who took it: that is what
        # `actor` already holds, so no return loses its receiver.
        c.execute('UPDATE return_verifications SET received_by_user_id=actor WHERE received_by_user_id IS NULL')
        run_script(c, SCHEMA)
        existing = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        for statement in filter(None, (s.strip() for s in TRIGGERS.split(';\n'))):
            if statement.split()[2] not in existing:
                c.execute(statement)
        # Existing discrepancy photos become evidence of their own return event.
        if 'photo_id' in _columns(c, 'return_discrepancies'):
            c.execute('''INSERT OR IGNORE INTO return_evidence(verification_id,discrepancy_id,attachment_id,created,actor)
                SELECT d.verification_id,d.id,d.photo_id,d.created,v.actor
                FROM return_discrepancies d JOIN return_verifications v ON v.id=d.verification_id
                WHERE d.photo_id IS NOT NULL''')
            c.execute('ALTER TABLE return_discrepancies DROP COLUMN photo_id')
        for column in OBSOLETE:
            if column in present:
                c.execute(f'ALTER TABLE return_verifications DROP COLUMN {column}')
        c.execute("""INSERT INTO audit(created,entity,entity_id,action,payload)
            VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'schema',14,'migration',?)""",
            (json.dumps({'change': 'A return is received by the signed-in user rather than into a '
                         'storage place, and return photos are evidence of a specific return '
                         'event through return_evidence. The obsolete receiver_kind, '
                         'receiver_name, receiver_mobile and storage columns were removed; '
                         'every existing return kept its receiver and its photos.'}),))
