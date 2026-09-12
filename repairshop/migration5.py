"""Stable physical devices, locally saved photos, drafts and folder projections."""
import re


def slug(value):
    return re.sub(r'[^\w-]+', '_', value, flags=re.UNICODE).strip('_.')[:48] or 'Record'


def migrate(c):
    c.executescript('''BEGIN IMMEDIATE;
    ALTER TABLE customers ADD COLUMN folder TEXT;
    ALTER TABLE customers ADD COLUMN current_photo_id INTEGER REFERENCES attachments(id);
    CREATE UNIQUE INDEX ix_customer_folder ON customers(folder);
    CREATE TABLE devices(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), name TEXT NOT NULL, category_id INTEGER REFERENCES masters(id), brand TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', serial TEXT NOT NULL DEFAULT '', folder TEXT UNIQUE, created TEXT NOT NULL);
    CREATE INDEX ix_device_customer ON devices(customer_id);
    ALTER TABLE sales ADD COLUMN device_id INTEGER REFERENCES devices(id);
    ALTER TABLE jobs ADD COLUMN device_id INTEGER REFERENCES devices(id);
    ALTER TABLE jobs ADD COLUMN photo_id INTEGER REFERENCES attachments(id);
    CREATE INDEX ix_job_device ON jobs(device_id);
    ALTER TABLE attachments ADD COLUMN customer_id INTEGER REFERENCES customers(id);
    ALTER TABLE attachments ADD COLUMN device_id INTEGER REFERENCES devices(id);
    ALTER TABLE attachments ADD COLUMN person_role TEXT;
    ALTER TABLE attachments ADD COLUMN person_name TEXT;
    ALTER TABLE attachments ADD COLUMN captured TEXT;
    ALTER TABLE attachments ADD COLUMN sha256 TEXT;
    CREATE INDEX ix_attachment_customer ON attachments(customer_id,id);
    CREATE INDEX ix_attachment_device ON attachments(device_id,id);
    CREATE TABLE intake_drafts(id TEXT PRIMARY KEY, actor INTEGER NOT NULL REFERENCES users(id), customer_id INTEGER REFERENCES customers(id), payload TEXT NOT NULL, updated TEXT NOT NULL);
    CREATE TABLE folder_queue(customer_id INTEGER PRIMARY KEY REFERENCES customers(id), revision INTEGER NOT NULL DEFAULT 1, error TEXT NOT NULL DEFAULT '');
    CREATE TABLE folder_files(path TEXT PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), sha256 TEXT NOT NULL);
    ''')
    try:
        for row in c.execute('SELECT id,name FROM customers').fetchall():
            c.execute('UPDATE customers SET folder=? WHERE id=?', (f'Customers/{slug(row[1])}_CUST-{row[0]:06d}', row[0]))
        sale_devices, job_devices = {}, {}
        for table, mapping in (('sales', sale_devices), ('jobs', job_devices)):
            for row in c.execute(f'SELECT * FROM {table} ORDER BY id').fetchall():
                device = None
                if table == 'jobs':
                    device = job_devices.get(row['parent_id']) or sale_devices.get(row['sale_id'])
                    if device and c.execute('SELECT customer_id FROM devices WHERE id=?', (device,)).fetchone()[0] != row['customer_id']:
                        device = None
                if not device:
                    device = c.execute('INSERT INTO devices(customer_id,name,category_id,serial,created) VALUES (?,?,?,?,?)', (row['customer_id'], row['device'], row['category_id'], row['serial'], row['received'] if table == 'jobs' else row['sale_date'] or '')).lastrowid
                mapping[row['id']] = device
                c.execute(f'UPDATE {table} SET device_id=? WHERE id=?', (device, row['id']))
        c.execute('INSERT INTO folder_queue(customer_id) SELECT id FROM customers')
        c.execute('PRAGMA user_version=5')
        c.commit()
    except Exception:
        c.rollback()
        raise
