"""Decouple operational in-house technicians from application login accounts."""


def _has_column(c, table, column):
    return any(row[1] == column for row in c.execute(f'PRAGMA table_info({table})'))


def migrate(c):
    c.execute('BEGIN IMMEDIATE')
    try:
        if not _has_column(c, 'assignments', 'technician_master_id'):
            c.execute('ALTER TABLE assignments ADD COLUMN technician_master_id INTEGER REFERENCES masters(id)')
        if not _has_column(c, 'stock_movements', 'technician_master_id'):
            c.execute('ALTER TABLE stock_movements ADD COLUMN technician_master_id INTEGER REFERENCES masters(id)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_assignments_technician_master ON assignments(technician_master_id)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_stock_movements_technician_master ON stock_movements(technician_master_id)')
        c.execute("""INSERT INTO audit(created,entity,entity_id,action,payload)
            VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'schema',10,'migration',?)""",
            ('{"change":"In-house technician assignment now supports technician directory records without requiring technician login accounts."}',))
        c.execute('PRAGMA user_version=10')
        c.commit()
    except Exception:
        c.rollback()
        raise
