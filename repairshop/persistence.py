"""SQLAlchemy connection lifecycle, SQLite transactions, explicit numbered migrations.

Services use SQLite parameter binding through SQLAlchemy's driver connection. No
session crosses a thread. WAL + FULL synchronous prioritizes durability.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import threading
import os
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from .domain import RuleError

SCHEMA_VERSION = 10
SCHEMA = """
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','counter','technician')), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE masters(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, normalized TEXT NOT NULL, category_id INTEGER REFERENCES masters(id), contact TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, UNIQUE(kind,normalized));
CREATE TABLE category_accessories(category_id INTEGER NOT NULL REFERENCES masters(id), accessory_id INTEGER NOT NULL REFERENCES masters(id), PRIMARY KEY(category_id,accessory_id));
CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', whatsapp_consent INTEGER NOT NULL DEFAULT 0, email_consent INTEGER NOT NULL DEFAULT 0, alternate TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE INDEX ix_customer_phone ON customers(phone);
CREATE INDEX ix_customer_name ON customers(name COLLATE NOCASE);
CREATE TABLE sales(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), category_id INTEGER REFERENCES masters(id), device TEXT NOT NULL, serial TEXT NOT NULL DEFAULT '', invoice_ref TEXT NOT NULL DEFAULT '', invoice_date TEXT, sale_date TEXT, amount INTEGER NOT NULL DEFAULT 0 CHECK(amount>=0), cost INTEGER NOT NULL DEFAULT 0 CHECK(cost>=0), provider TEXT NOT NULL DEFAULT '', warranty_start TEXT, warranty_end TEXT, warranty_terms TEXT NOT NULL DEFAULT '', collected INTEGER NOT NULL DEFAULT 0, collector TEXT NOT NULL DEFAULT '', acknowledgment TEXT NOT NULL DEFAULT '');
CREATE TABLE jobs(id INTEGER PRIMARY KEY, number TEXT UNIQUE, intake_ref TEXT NOT NULL, customer_id INTEGER NOT NULL REFERENCES customers(id), submitter TEXT NOT NULL DEFAULT '', relationship TEXT NOT NULL DEFAULT '', update_contact_id INTEGER REFERENCES customers(id), sale_id INTEGER REFERENCES sales(id), parent_id INTEGER REFERENCES jobs(id), category_id INTEGER REFERENCES masters(id), service_id INTEGER REFERENCES masters(id), device TEXT NOT NULL, serial TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT 'elsewhere', complaint TEXT NOT NULL, damage TEXT NOT NULL DEFAULT '', received TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), stage TEXT NOT NULL DEFAULT 'received', route TEXT NOT NULL DEFAULT 'in_house', assignment_id INTEGER, repair_due TEXT, collection_due TEXT, return_due TEXT, actual_completion TEXT, actual_collection TEXT, policy TEXT NOT NULL CHECK(policy IN ('NO_CUSTOMER_CHARGE','AGREED_TRANSPORT_ONLY')), transport_agreed INTEGER NOT NULL DEFAULT 0 CHECK(transport_agreed>=0), assessment_agreed INTEGER NOT NULL DEFAULT 0 CHECK(assessment_agreed>=0), assessment_consent INTEGER NOT NULL DEFAULT 0, deposit INTEGER NOT NULL DEFAULT 0 CHECK(deposit>=0), test_result TEXT NOT NULL DEFAULT '', hold_reason TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_job_customer ON jobs(customer_id,id);
CREATE INDEX ix_job_stage ON jobs(stage,id);
CREATE INDEX ix_job_received ON jobs(received);
CREATE INDEX ix_job_route ON jobs(route,id);
CREATE INDEX ix_job_serial ON jobs(serial);
CREATE TABLE items(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), type TEXT NOT NULL, description TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0), serial TEXT NOT NULL DEFAULT '', condition TEXT NOT NULL DEFAULT '', provenance TEXT NOT NULL DEFAULT 'received', replaces_id INTEGER REFERENCES items(id));
CREATE INDEX ix_items_job ON items(job_id);
CREATE TABLE holdings(item_id INTEGER NOT NULL REFERENCES items(id), location TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0), PRIMARY KEY(item_id,location));
CREATE INDEX ix_holdings_location ON holdings(location,quantity);
CREATE TABLE movements(id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, item_id INTEGER NOT NULL REFERENCES items(id), quantity INTEGER NOT NULL CHECK(quantity>0), from_location TEXT NOT NULL, to_location TEXT NOT NULL, happened TEXT NOT NULL, recorded TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), counterparty TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '', condition TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', acknowledgment TEXT NOT NULL DEFAULT '', reverses_id INTEGER REFERENCES movements(id));
CREATE TABLE assignments(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), route TEXT NOT NULL, contact_id INTEGER REFERENCES masters(id), technician_id INTEGER REFERENCES users(id), reference TEXT NOT NULL DEFAULT '', estimate INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE work(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), assignment_id INTEGER REFERENCES assignments(id), kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE warranty(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), eligibility TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('pending','accepted','rejected','partial')), rma TEXT NOT NULL DEFAULT '', findings TEXT NOT NULL DEFAULT '', covered TEXT NOT NULL DEFAULT '', excluded TEXT NOT NULL DEFAULT '', terms TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE quotes(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), version INTEGER NOT NULL, state TEXT NOT NULL, scope TEXT NOT NULL, lines TEXT NOT NULL, total INTEGER NOT NULL CHECK(total>=0), terms TEXT NOT NULL, valid_until TEXT, created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), UNIQUE(job_id,version));
CREATE TABLE decisions(id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES quotes(id), decision TEXT NOT NULL, person TEXT NOT NULL, channel TEXT NOT NULL, amount INTEGER NOT NULL, evidence TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE entries(id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, account_type TEXT NOT NULL CHECK(account_type IN ('customer','vendor')), account_id INTEGER NOT NULL, job_id INTEGER REFERENCES jobs(id), quote_id INTEGER REFERENCES quotes(id), kind TEXT NOT NULL, amount INTEGER NOT NULL, posted TEXT NOT NULL, created TEXT NOT NULL, method TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}', reverses_id INTEGER UNIQUE REFERENCES entries(id), actor INTEGER NOT NULL REFERENCES users(id));
CREATE INDEX ix_entries_account ON entries(account_type,account_id,posted,id);
CREATE INDEX ix_entries_job ON entries(job_id);
CREATE UNIQUE INDEX ix_invoice_quote ON entries(quote_id) WHERE kind='invoice';
CREATE TABLE allocations(id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL REFERENCES entries(id), charge_id INTEGER NOT NULL REFERENCES entries(id), amount INTEGER NOT NULL CHECK(amount>0), UNIQUE(payment_id,charge_id));
CREATE TABLE expenses(id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0), payer TEXT NOT NULL, reference TEXT NOT NULL, included_entry_id INTEGER REFERENCES entries(id), payload TEXT NOT NULL, created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE expense_allocations(expense_id INTEGER NOT NULL REFERENCES expenses(id), job_id INTEGER NOT NULL REFERENCES jobs(id), amount INTEGER NOT NULL CHECK(amount>=0), PRIMARY KEY(expense_id,job_id));
CREATE TABLE outbox(id INTEGER PRIMARY KEY, event_key TEXT NOT NULL, job_id INTEGER REFERENCES jobs(id), quote_id INTEGER REFERENCES quotes(id), contact_id INTEGER NOT NULL REFERENCES customers(id), channel TEXT NOT NULL, destination TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt TEXT, provider_id TEXT, error TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE(event_key,channel,destination));
CREATE INDEX ix_outbox_state ON outbox(state,next_attempt);
CREATE TABLE attachments(id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES jobs(id), sale_id INTEGER REFERENCES sales(id), kind TEXT NOT NULL, path TEXT NOT NULL UNIQUE, title TEXT NOT NULL, created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE audit(id INTEGER PRIMARY KEY, actor INTEGER REFERENCES users(id), created TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER, action TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX ix_audit_entity ON audit(entity,entity_id,id);
CREATE TABLE backups(id INTEGER PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, created TEXT NOT NULL, state TEXT NOT NULL, external_state TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '');
"""

class Database:
    def __init__(self, root, readonly=False):
        self.root = Path(root).resolve()
        self.readonly = readonly
        self.guard = threading.RLock()
        self.local = threading.local()
        self.path = self.root / "shop.db"
        if not readonly:
            self.root.mkdir(parents=True, exist_ok=True)
            self.recover_interrupted_restore()
            (self.root / "managed").mkdir(exist_ok=True)
        def connect():
            if readonly:
                c = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
            else:
                c = sqlite3.connect(self.path, timeout=5)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=5000")
            if not readonly:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=FULL")
            return c
        self.engine = create_engine("sqlite://", creator=connect, poolclass=NullPool)
        if readonly:
            with self.read() as c:
                if c.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise RuleError("Historical viewer needs the current schema; restore an older archive into a working copy first.")
        else:
            self.migrate()

    def recover_interrupted_restore(self):
        journal = self.root / 'restore-journal.json'
        if not journal.exists():
            return
        data = json.loads(journal.read_text(encoding='utf-8'))
        recovery = (self.root / data['recovery']).resolve()
        if not recovery.is_relative_to(self.root) or not recovery.name.startswith('restore-recovery-'):
            raise RuleError('Unsafe restore recovery journal. Owner attention required.')
        previous = recovery / 'previous'
        failed = recovery / 'interrupted-candidate'
        failed.mkdir(exist_ok=True)
        for name in ('shop.db', 'shop.db-wal', 'shop.db-shm', 'managed', 'Customers'):
            old = previous / name
            current = self.root / name
            if old.exists():
                if current.exists():
                    os.replace(current, failed / name)
                os.replace(old, current)
            elif 'original_names' in data and name not in data['original_names'] and current.exists():
                os.replace(current, failed / name)
        os.replace(journal, recovery / 'recovered-journal.json')

    def migrate(self):
        with self.guard:
            c = self.engine.raw_connection()
            try:
                version = c.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise RuleError("This database was made by a newer application.")
                if 0 < version < SCHEMA_VERSION:
                    from .backup import snapshot_archive
                    snapshot_archive(self, f"pre-upgrade-v{version}", self.root / "backups")
                if version == 0:
                    existing = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    if existing:
                        raise RuleError("Unrecognized existing database; refusing to overwrite it.")
                    c.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version=1; COMMIT;")
                    version = 1
                if version == 1:
                    immutable = ["audit", "entries", "movements", "decisions", "work", "warranty", "assignments", "expenses", "expense_allocations", "allocations"]
                    statements = []
                    for table in immutable:
                        for action in ("UPDATE", "DELETE"):
                            statements.append(f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable record: add a correcting event'); END;")
                    statements.append("CREATE TRIGGER quote_snapshot BEFORE UPDATE ON quotes WHEN NEW.job_id!=OLD.job_id OR NEW.version!=OLD.version OR NEW.scope!=OLD.scope OR NEW.lines!=OLD.lines OR NEW.total!=OLD.total OR NEW.terms!=OLD.terms OR NEW.valid_until IS NOT OLD.valid_until BEGIN SELECT RAISE(ABORT,'Issued quote is immutable'); END;")
                    c.executescript("BEGIN IMMEDIATE;\n" + "\n".join(statements) + "\nPRAGMA user_version=2; COMMIT;")
                    version = 2
                if version == 2:
                    c.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE commands(operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, result_id INTEGER NOT NULL);
                    ALTER TABLE quotes ADD COLUMN snapshot TEXT NOT NULL DEFAULT '{}';
                    CREATE TABLE allocation_reversals(id INTEGER PRIMARY KEY, allocation_id INTEGER NOT NULL UNIQUE REFERENCES allocations(id), created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL);
                    CREATE TRIGGER immutable_allocation_reversals_update BEFORE UPDATE ON allocation_reversals BEGIN SELECT RAISE(ABORT,'Immutable allocation correction'); END;
                    CREATE TRIGGER immutable_allocation_reversals_delete BEFORE DELETE ON allocation_reversals BEGIN SELECT RAISE(ABORT,'Immutable allocation correction'); END;
                    CREATE TRIGGER immutable_job_number BEFORE UPDATE ON jobs WHEN OLD.number IS NOT NULL AND NEW.number IS NOT OLD.number BEGIN SELECT RAISE(ABORT,'Job number is immutable'); END;
                    CREATE TRIGGER immutable_quote_snapshot BEFORE UPDATE ON quotes WHEN NEW.snapshot!=OLD.snapshot BEGIN SELECT RAISE(ABORT,'Quote snapshot is immutable'); END;
                    PRAGMA user_version=3; COMMIT;""")
                    version = 3
                if version == 3:
                    c.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE recipients(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('staff','vendor')), entity_id INTEGER NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('email','whatsapp')), destination TEXT NOT NULL, consent INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, UNIQUE(kind,entity_id,channel));
                    CREATE TABLE outbox_new(id INTEGER PRIMARY KEY, event_key TEXT NOT NULL, job_id INTEGER REFERENCES jobs(id), quote_id INTEGER REFERENCES quotes(id), contact_id INTEGER REFERENCES customers(id), recipient_id INTEGER REFERENCES recipients(id), attachment_id INTEGER REFERENCES attachments(id), channel TEXT NOT NULL, destination TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt TEXT, provider_id TEXT, error TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE(event_key,channel,destination), CHECK(contact_id IS NOT NULL OR recipient_id IS NOT NULL));
                    INSERT INTO outbox_new(id,event_key,job_id,quote_id,contact_id,channel,destination,event,payload,state,attempts,next_attempt,provider_id,error,created,updated) SELECT id,event_key,job_id,quote_id,contact_id,channel,destination,event,payload,state,attempts,next_attempt,provider_id,error,created,updated FROM outbox;
                    DROP TABLE outbox;
                    ALTER TABLE outbox_new RENAME TO outbox;
                    CREATE INDEX ix_outbox_state ON outbox(state,next_attempt);
                    PRAGMA user_version=4; COMMIT;""")
                    version = 4
                if version == 4:
                    from .migration5 import migrate
                    migrate(c)
                    version = 5
                if version == 5:
                    from .migration6 import migrate
                    migrate(c)
                    version = 6
                if version == 6:
                    from .migration7 import migrate
                    migrate(c)
                    version = 7
                if version == 7:
                    from .migration8 import migrate
                    migrate(c)
                    version = 8
                if version == 8:
                    from .migration9 import migrate
                    migrate(c)
                    version = 9
                if version == 9:
                    from .migration10 import migrate
                    migrate(c)
            finally:
                c.close()

    @contextmanager
    def read(self):
        active = getattr(self.local, 'connection', None)
        if active is not None:
            yield active
            return
        c = self.engine.raw_connection()
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def read_snapshot(self):
        """One consistent connection for composite read-only projections."""
        if getattr(self.local, 'connection', None) is not None:
            yield
            return
        c = self.engine.raw_connection()
        try:
            c.execute('BEGIN')
            self.local.connection = c
            self.local.read_only_scope = True
            yield
        finally:
            self.local.connection = None
            self.local.read_only_scope = False
            c.rollback()
            c.close()

    @contextmanager
    def transaction(self):
        if self.readonly:
            raise RuleError("This is a read-only archive. Business changes are disabled.")
        if getattr(self.local, 'read_only_scope', False):
            raise RuleError('Business changes are not allowed inside a read-only projection.')
        active = getattr(self.local, 'connection', None)
        if active is not None:
            self.local.sequence += 1
            name = 'nested_' + str(self.local.sequence)
            active.execute('SAVEPOINT ' + name)
            try:
                yield active
                active.execute('RELEASE ' + name)
            except Exception:
                active.execute('ROLLBACK TO ' + name)
                active.execute('RELEASE ' + name)
                raise
            return
        with self.guard:
            c = self.engine.raw_connection()
            try:
                c.execute("BEGIN IMMEDIATE")
                self.local.connection = c
                self.local.sequence = 0
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                self.local.connection = None
                c.close()

    def rows(self, sql, params=()):
        with self.read() as c:
            return [dict(row) for row in c.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.rows(sql, params)
        return rows[0] if rows else None

    def setting(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default


def insert(c, table, **values):
    keys = ",".join(values)
    return c.execute(f"INSERT INTO {table}({keys}) VALUES ({','.join('?' for _ in values)})", tuple(values.values())).lastrowid
