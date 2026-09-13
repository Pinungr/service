"""Extend the existing stock ledger and preserve all issued device history."""


def migrate(c):
    c.executescript('''BEGIN IMMEDIATE;
    ALTER TABLE stock_items ADD COLUMN sku TEXT NOT NULL DEFAULT '';
    ALTER TABLE stock_items ADD COLUMN category_id INTEGER REFERENCES masters(id);
    ALTER TABLE stock_items ADD COLUMN compatibility TEXT NOT NULL DEFAULT '';
    ALTER TABLE stock_items ADD COLUMN serialized INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE stock_items ADD COLUMN serial TEXT NOT NULL DEFAULT '';
    ALTER TABLE stock_items ADD COLUMN batch TEXT NOT NULL DEFAULT '';
    ALTER TABLE stock_items ADD COLUMN supplier_id INTEGER REFERENCES masters(id);
    ALTER TABLE stock_items ADD COLUMN invoice TEXT NOT NULL DEFAULT '';
    ALTER TABLE stock_items ADD COLUMN purchase_date TEXT;
    ALTER TABLE stock_items ADD COLUMN storage TEXT NOT NULL DEFAULT 'Stock shelf';
    ALTER TABLE stock_items ADD COLUMN minimum_stock INTEGER NOT NULL DEFAULT 0 CHECK(minimum_stock>=0);
    ALTER TABLE stock_items ADD COLUMN warranty_duration INTEGER NOT NULL DEFAULT 0 CHECK(warranty_duration>=0);
    ALTER TABLE stock_items ADD COLUMN warranty_unit TEXT NOT NULL DEFAULT 'months';
    ALTER TABLE stock_items ADD COLUMN warranty_provider TEXT NOT NULL DEFAULT '';
    ALTER TABLE stock_items ADD COLUMN warranty_terms TEXT NOT NULL DEFAULT '';
    ALTER TABLE stock_items ADD COLUMN markup_basis_points INTEGER;
    ALTER TABLE stock_items ADD COLUMN notes TEXT NOT NULL DEFAULT '';
    UPDATE stock_items SET sku='STK-' || printf('%06d',id);
    CREATE UNIQUE INDEX ix_stock_sku ON stock_items(sku COLLATE NOCASE);
    CREATE UNIQUE INDEX ix_stock_serial ON stock_items(serial COLLATE NOCASE) WHERE serialized=1;
    ALTER TABLE repair_parts ADD COLUMN stock_state TEXT NOT NULL DEFAULT 'none';
    ALTER TABLE repair_parts ADD COLUMN stock_location TEXT NOT NULL DEFAULT '';
    ALTER TABLE repair_parts ADD COLUMN procurement_status TEXT NOT NULL DEFAULT 'legacy';
    ALTER TABLE repair_parts ADD COLUMN requested_by TEXT NOT NULL DEFAULT '';
    ALTER TABLE repair_parts ADD COLUMN request_notes TEXT NOT NULL DEFAULT '';
    DROP TRIGGER installed_part_history_update;
    UPDATE repair_parts SET stock_state='installed' WHERE source='stock' AND status='installed';
    CREATE TRIGGER installed_part_history_update BEFORE UPDATE ON repair_parts WHEN OLD.status='installed' BEGIN SELECT RAISE(ABORT,'Installed part history cannot be overwritten'); END;
    ALTER TABLE stock_movements RENAME TO stock_movements_v8;
    CREATE TABLE stock_movements(id INTEGER PRIMARY KEY, stock_id INTEGER NOT NULL REFERENCES stock_items(id),
        delta INTEGER NOT NULL DEFAULT 0, reserved_delta INTEGER NOT NULL DEFAULT 0, issued_delta INTEGER NOT NULL DEFAULT 0,
        quantity INTEGER NOT NULL CHECK(quantity>0), kind TEXT NOT NULL, part_id INTEGER REFERENCES repair_parts(id),
        job_id INTEGER REFERENCES jobs(id), from_location TEXT NOT NULL DEFAULT '', to_location TEXT NOT NULL DEFAULT '',
        party_id INTEGER REFERENCES masters(id), technician_id INTEGER REFERENCES users(id),
        reference TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        snapshot TEXT NOT NULL DEFAULT '{}', operation_id TEXT UNIQUE,
        created TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id));
    INSERT INTO stock_movements(id,stock_id,delta,quantity,kind,part_id,job_id,reference,notes,created,actor)
        SELECT id,stock_id,delta,abs(delta),CASE WHEN part_id IS NOT NULL THEN 'INSTALLED' ELSE 'LEGACY_ADJUSTMENT' END,
        part_id,job_id,reference,notes,created,actor FROM stock_movements_v8;
    DROP TABLE stock_movements_v8;
    CREATE INDEX ix_stock_item ON stock_movements(stock_id);
    CREATE INDEX ix_stock_part ON stock_movements(part_id,id);
    CREATE UNIQUE INDEX ix_stock_installed ON stock_movements(part_id) WHERE kind='INSTALLED';
    CREATE TRIGGER immutable_stock_update BEFORE UPDATE ON stock_movements BEGIN SELECT RAISE(ABORT,'Add a stock correction movement'); END;
    CREATE TRIGGER immutable_stock_delete BEFORE DELETE ON stock_movements BEGIN SELECT RAISE(ABORT,'Stock movements are immutable'); END;
    CREATE TABLE manual_warranty_checks(id INTEGER PRIMARY KEY,job_id INTEGER NOT NULL REFERENCES jobs(id),device_id INTEGER NOT NULL REFERENCES devices(id),
        result TEXT NOT NULL CHECK(result IN ('VALID','INVALID','UNVERIFIED')), evidence_type TEXT NOT NULL,
        reference TEXT NOT NULL,provider TEXT NOT NULL,coverage TEXT NOT NULL,notes TEXT NOT NULL,
        attachment_id INTEGER REFERENCES attachments(id),checked_at TEXT NOT NULL,actor INTEGER NOT NULL REFERENCES users(id));
    CREATE TRIGGER manual_warranty_update BEFORE UPDATE ON manual_warranty_checks BEGIN SELECT RAISE(ABORT,'Record a new warranty check'); END;
    CREATE TRIGGER manual_warranty_delete BEFORE DELETE ON manual_warranty_checks BEGIN SELECT RAISE(ABORT,'Keep warranty evidence'); END;
    ALTER TABLE warranty_claims ADD COLUMN original_status TEXT NOT NULL DEFAULT 'ACTIVE';
    ALTER TABLE warranty_claims ADD COLUMN outcome TEXT NOT NULL DEFAULT '';
    UPDATE part_warranties SET status='ACTIVE' WHERE status='CLAIMED' AND EXISTS
        (SELECT 1 FROM warranty_claims c WHERE c.warranty_id=part_warranties.id AND c.status IN ('OPEN','ACCEPTED','IN_REPAIR'));
    INSERT INTO audit(created,entity,entity_id,action,payload) VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'schema',9,'migration',
        '{"change":"Stock ledger extended; existing amounts and issued cards preserved. Active-claim display now derives from claim records instead of a permanent CLAIMED flag."}');
    PRAGMA user_version=9;
    COMMIT;''')
