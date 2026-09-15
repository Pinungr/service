"""Structured addresses, richer intake evidence, third-party quotations and return checks.

Every change is additive. The existing free-text `customers.address` column is kept and
still written, so historical records, folder projections and documents stay readable while
new structured columns become the editable source.
"""
import json

COLUMNS = {
    'customers': [
        ('address_line1', "TEXT NOT NULL DEFAULT ''"),
        ('address_line2', "TEXT NOT NULL DEFAULT ''"),
        ('pincode', "TEXT NOT NULL DEFAULT ''"),
        ('district', "TEXT NOT NULL DEFAULT ''"),
        ('state', "TEXT NOT NULL DEFAULT ''"),
    ],
    'jobs': [
        # The initial estimate given at collection. Never overwritten by a later quotation.
        ('initial_estimate', 'INTEGER NOT NULL DEFAULT 0 CHECK(initial_estimate>=0)'),
        ('customer_requirement', "TEXT NOT NULL DEFAULT ''"),
    ],
    'items': [
        ('notes', "TEXT NOT NULL DEFAULT ''"),
        ('photo_id', 'INTEGER REFERENCES attachments(id)'),
    ],
    'masters': [
        ('address_line1', "TEXT NOT NULL DEFAULT ''"),
        ('address_line2', "TEXT NOT NULL DEFAULT ''"),
        ('pincode', "TEXT NOT NULL DEFAULT ''"),
        ('district', "TEXT NOT NULL DEFAULT ''"),
        ('state', "TEXT NOT NULL DEFAULT ''"),
        ('specialization', "TEXT NOT NULL DEFAULT ''"),
        ('photo_id', 'INTEGER REFERENCES attachments(id)'),
    ],
    'dispatches': [
        ('paid_by', "TEXT NOT NULL DEFAULT 'shop'"),
    ],
}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS party_quotes(id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id), dispatch_id INTEGER REFERENCES dispatches(id),
    contact_id INTEGER REFERENCES masters(id), version INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('current','superseded','cancelled')),
    labour INTEGER NOT NULL DEFAULT 0 CHECK(labour>=0),
    transport INTEGER NOT NULL DEFAULT 0 CHECK(transport>=0),
    other INTEGER NOT NULL DEFAULT 0 CHECK(other>=0),
    parts_total INTEGER NOT NULL DEFAULT 0 CHECK(parts_total>=0),
    total INTEGER NOT NULL DEFAULT 0 CHECK(total>=0),
    reference TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    supersedes_id INTEGER REFERENCES party_quotes(id), revision_reason TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL, actor INTEGER REFERENCES users(id), UNIQUE(job_id,version));
CREATE INDEX IF NOT EXISTS ix_party_quote_job ON party_quotes(job_id,version);
CREATE UNIQUE INDEX IF NOT EXISTS ix_party_quote_current ON party_quotes(job_id) WHERE state='current';
CREATE TABLE IF NOT EXISTS party_quote_lines(id INTEGER PRIMARY KEY,
    quote_id INTEGER NOT NULL REFERENCES party_quotes(id),
    kind TEXT NOT NULL CHECK(kind IN ('part','labour','transport','other')),
    name TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>0),
    unit_cost INTEGER NOT NULL DEFAULT 0 CHECK(unit_cost>=0),
    customer_charge INTEGER NOT NULL DEFAULT 0 CHECK(customer_charge>=0),
    warranty TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_party_quote_line ON party_quote_lines(quote_id,id);
CREATE TABLE IF NOT EXISTS return_verifications(id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id), dispatch_id INTEGER REFERENCES dispatches(id),
    operation_id TEXT NOT NULL UNIQUE, complete INTEGER NOT NULL DEFAULT 0,
    receiver_kind TEXT NOT NULL DEFAULT 'storage', receiver_name TEXT NOT NULL DEFAULT '',
    receiver_mobile TEXT NOT NULL DEFAULT '', storage TEXT NOT NULL DEFAULT '',
    checked TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL, actor INTEGER REFERENCES users(id));
CREATE INDEX IF NOT EXISTS ix_return_verification_job ON return_verifications(job_id,id);
CREATE TABLE IF NOT EXISTS return_discrepancies(id INTEGER PRIMARY KEY,
    verification_id INTEGER NOT NULL REFERENCES return_verifications(id),
    item_id INTEGER REFERENCES items(id),
    kind TEXT NOT NULL CHECK(kind IN ('missing','damaged','wrong_item','quantity','other')),
    expected INTEGER NOT NULL DEFAULT 0, received INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '', photo_id INTEGER REFERENCES attachments(id),
    resolved TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_return_discrepancy ON return_discrepancies(verification_id,id);
'''

TRIGGERS = '''
CREATE TRIGGER party_quote_history_update BEFORE UPDATE ON party_quotes
    WHEN NEW.job_id IS NOT OLD.job_id OR NEW.version IS NOT OLD.version
        OR NEW.labour IS NOT OLD.labour OR NEW.transport IS NOT OLD.transport
        OR NEW.other IS NOT OLD.other OR NEW.parts_total IS NOT OLD.parts_total
        OR NEW.total IS NOT OLD.total OR NEW.created IS NOT OLD.created
    BEGIN SELECT RAISE(ABORT,'Issued third-party quotations are immutable: record a new version'); END;
CREATE TRIGGER party_quote_history_delete BEFORE DELETE ON party_quotes
    BEGIN SELECT RAISE(ABORT,'Third-party quotation history is preserved'); END;
CREATE TRIGGER party_quote_line_update BEFORE UPDATE ON party_quote_lines
    BEGIN SELECT RAISE(ABORT,'Quotation lines belong to an issued version'); END;
CREATE TRIGGER party_quote_line_delete BEFORE DELETE ON party_quote_lines
    BEGIN SELECT RAISE(ABORT,'Quotation lines belong to an issued version'); END;
CREATE TRIGGER return_verification_update BEFORE UPDATE ON return_verifications
    BEGIN SELECT RAISE(ABORT,'Record a new return verification instead of editing one'); END;
CREATE TRIGGER return_verification_delete BEFORE DELETE ON return_verifications
    BEGIN SELECT RAISE(ABORT,'Return verification evidence is preserved'); END;
CREATE TRIGGER return_discrepancy_delete BEFORE DELETE ON return_discrepancies
    BEGIN SELECT RAISE(ABORT,'Return discrepancy evidence is preserved'); END;
'''


def _columns(c, table):
    return {row[1] for row in c.execute(f'PRAGMA table_info({table})')}


def compose_address(line1, line2, pincode, district, state):
    """Readable single-line form kept in the legacy `address` column."""
    locality = ' '.join(filter(None, [district, state]))
    if pincode:
        locality = (locality + ' - ' + pincode).strip(' -')
    return '\n'.join(x for x in (line1, line2, locality) if x and x.strip())


def split_address(text):
    """Best-effort structuring of one historical free-text address."""
    lines = [line.strip() for line in (text or '').replace('\r', '').split('\n') if line.strip()]
    return dict(address_line1=lines[0] if lines else '',
                address_line2=' '.join(lines[1:]) if len(lines) > 1 else '',
                pincode='', district='', state='')


def migrate(c):
    c.execute('BEGIN IMMEDIATE')
    try:
        for table, columns in COLUMNS.items():
            present = _columns(c, table)
            for name, definition in columns:
                if name not in present:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        c.executescript(SCHEMA)
        existing = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        for statement in filter(None, (s.strip() for s in TRIGGERS.split(';\n'))):
            if statement.split()[2] not in existing:
                c.execute(statement)
        c.execute('CREATE INDEX IF NOT EXISTS ix_customer_pincode ON customers(pincode)')
        c.execute("CREATE INDEX IF NOT EXISTS ix_master_party ON masters(kind,active) WHERE kind IN ('vendor','centre','supplier')")
        _backfill_addresses(c)
        _backfill_party_profiles(c)
        c.execute("""INSERT INTO audit(created,entity,entity_id,action,payload)
            VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'schema',12,'migration',?)""",
            (json.dumps({'change': 'Structured customer and third-party addresses, accessory condition '
                         'and photo evidence, per-job initial estimate and customer requirement, '
                         'versioned third-party quotations and return verification records. '
                         'Existing free-text addresses were copied into address line 1 and the '
                         'original address column is still maintained.'}),))
        c.execute('PRAGMA user_version=12')
        c.commit()
    except Exception:
        c.rollback()
        raise


def _backfill_addresses(c):
    for row in c.execute("SELECT id,address FROM customers WHERE address!='' AND address_line1=''").fetchall():
        parts = split_address(row['address'])
        c.execute('UPDATE customers SET address_line1=?,address_line2=? WHERE id=?',
                  (parts['address_line1'], parts['address_line2'], row['id']))


def _backfill_party_profiles(c):
    """Lift the address already stored inside the directory JSON profile into columns."""
    rows = c.execute("""SELECT id,details FROM masters
        WHERE kind IN ('vendor','centre','supplier') AND details!='' AND address_line1=''""").fetchall()
    for row in rows:
        try:
            profile = json.loads(row['details'])
        except ValueError:
            continue
        if not isinstance(profile, dict):
            continue
        parts = split_address(profile.get('address', ''))
        c.execute('UPDATE masters SET address_line1=?,address_line2=?,specialization=? WHERE id=?',
                  (parts['address_line1'], parts['address_line2'], profile.get('specialization', ''), row['id']))
