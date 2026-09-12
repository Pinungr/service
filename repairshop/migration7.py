"""Immutable job cards, spare-parts inventory, installed parts and warranty claims."""


def migrate(c):
    c.executescript('''BEGIN IMMEDIATE;
    CREATE TABLE job_cards(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), sequence INTEGER NOT NULL,
        kind TEXT NOT NULL, event_key TEXT NOT NULL UNIQUE, from_name TEXT NOT NULL, to_name TEXT NOT NULL,
        effective TEXT NOT NULL, created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), snapshot TEXT NOT NULL,
        UNIQUE(job_id,sequence));
    CREATE INDEX ix_card_job ON job_cards(job_id,sequence);
    CREATE TRIGGER immutable_job_cards_update BEFORE UPDATE ON job_cards BEGIN SELECT RAISE(ABORT,'Issued Job Cards are immutable'); END;
    CREATE TRIGGER immutable_job_cards_delete BEFORE DELETE ON job_cards BEGIN SELECT RAISE(ABORT,'Issued Job Cards are immutable'); END;
    CREATE TABLE stock_items(id INTEGER PRIMARY KEY, name TEXT NOT NULL, part_number TEXT NOT NULL DEFAULT '',
        brand TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', purchase_cost INTEGER NOT NULL CHECK(purchase_cost>=0),
        customer_price INTEGER NOT NULL CHECK(customer_price>=0), active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE repair_parts(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), device_id INTEGER NOT NULL REFERENCES devices(id),
        estimate_id INTEGER REFERENCES quotes(id), card_id INTEGER REFERENCES job_cards(id), name TEXT NOT NULL, part_type TEXT NOT NULL DEFAULT '',
        brand TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', part_number TEXT NOT NULL DEFAULT '', serial TEXT NOT NULL DEFAULT '',
        quantity INTEGER NOT NULL CHECK(quantity>0), source TEXT NOT NULL CHECK(source IN ('stock','supplier','technician','other')),
        inventory_id INTEGER REFERENCES stock_items(id), supplier_id INTEGER REFERENCES masters(id), supplier_snapshot TEXT NOT NULL DEFAULT '',
        invoice TEXT NOT NULL DEFAULT '', purchase_date TEXT, purchase_cost INTEGER NOT NULL CHECK(purchase_cost>=0), customer_price INTEGER NOT NULL CHECK(customer_price>=0),
        installed_by TEXT NOT NULL DEFAULT '', installed_at TEXT, warranty_duration INTEGER NOT NULL DEFAULT 0 CHECK(warranty_duration>=0),
        warranty_unit TEXT NOT NULL DEFAULT 'months' CHECK(warranty_unit IN ('days','months','years')), warranty_provider TEXT NOT NULL DEFAULT '',
        warranty_terms TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','installed','removed')),
        notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX ix_repair_part_job ON repair_parts(job_id,status);
    CREATE INDEX ix_repair_part_device ON repair_parts(device_id);
    CREATE TRIGGER installed_part_history_update BEFORE UPDATE ON repair_parts WHEN OLD.status='installed' BEGIN SELECT RAISE(ABORT,'Installed part history cannot be overwritten'); END;
    CREATE TRIGGER installed_part_history_delete BEFORE DELETE ON repair_parts BEGIN SELECT RAISE(ABORT,'Keep part history; remove planned parts with an audit event'); END;
    CREATE TABLE stock_movements(id INTEGER PRIMARY KEY, stock_id INTEGER NOT NULL REFERENCES stock_items(id), delta INTEGER NOT NULL CHECK(delta!=0),
        part_id INTEGER UNIQUE REFERENCES repair_parts(id), job_id INTEGER REFERENCES jobs(id), reference TEXT NOT NULL, notes TEXT NOT NULL,
        created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
    CREATE INDEX ix_stock_item ON stock_movements(stock_id);
    CREATE TRIGGER immutable_stock_update BEFORE UPDATE ON stock_movements BEGIN SELECT RAISE(ABORT,'Add a stock correction movement'); END;
    CREATE TRIGGER immutable_stock_delete BEFORE DELETE ON stock_movements BEGIN SELECT RAISE(ABORT,'Stock movements are immutable'); END;
    CREATE TABLE part_warranties(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id), job_id INTEGER NOT NULL REFERENCES jobs(id),
        part_id INTEGER UNIQUE REFERENCES repair_parts(id), name TEXT NOT NULL, installed_at TEXT NOT NULL,
        duration INTEGER NOT NULL CHECK(duration>=0), unit TEXT NOT NULL CHECK(unit IN ('days','months','years')), start_date TEXT NOT NULL,
        expiry TEXT NOT NULL, source TEXT NOT NULL, provider TEXT NOT NULL, terms TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','VOID','CLAIMED','REPLACED')),
        notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
    CREATE INDEX ix_warranty_device ON part_warranties(device_id,expiry);
    CREATE TRIGGER warranty_history_delete BEFORE DELETE ON part_warranties BEGIN SELECT RAISE(ABORT,'Preserve warranty history'); END;
    CREATE TABLE warranty_claims(id INTEGER PRIMARY KEY, new_job_id INTEGER NOT NULL REFERENCES jobs(id), original_job_id INTEGER NOT NULL REFERENCES jobs(id),
        device_id INTEGER NOT NULL REFERENCES devices(id), part_id INTEGER REFERENCES repair_parts(id), warranty_id INTEGER NOT NULL REFERENCES part_warranties(id),
        complaint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','ACCEPTED','REJECTED','IN_REPAIR','REPLACED','COMPLETED','CLOSED')),
        resolution TEXT NOT NULL DEFAULT '', replacement_part_id INTEGER REFERENCES repair_parts(id), notes TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), UNIQUE(new_job_id,warranty_id));
    CREATE TRIGGER claim_history_delete BEFORE DELETE ON warranty_claims BEGIN SELECT RAISE(ABORT,'Preserve warranty claim history'); END;
    PRAGMA user_version=7;
    COMMIT;''')
