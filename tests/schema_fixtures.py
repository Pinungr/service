"""Construct actual older schemas for migration acceptance tests."""


def remove_v9(c):
    c.execute('DROP TABLE manual_warranty_checks')
    for index in ('ix_stock_sku','ix_stock_serial'):c.execute('DROP INDEX '+index)
    for column in ('sku','category_id','compatibility','serialized','serial','batch','supplier_id','invoice','purchase_date','storage','minimum_stock','warranty_duration','warranty_unit','warranty_provider','warranty_terms','markup_basis_points','notes'):
        c.execute('ALTER TABLE stock_items DROP COLUMN '+column)
    for column in ('stock_state','stock_location','procurement_status','requested_by','request_notes'):c.execute('ALTER TABLE repair_parts DROP COLUMN '+column)
    for column in ('original_status','outcome'):c.execute('ALTER TABLE warranty_claims DROP COLUMN '+column)
    c.execute('ALTER TABLE stock_movements RENAME TO movements_v9')
    c.execute('''CREATE TABLE stock_movements(id INTEGER PRIMARY KEY,stock_id INTEGER NOT NULL REFERENCES stock_items(id),delta INTEGER NOT NULL CHECK(delta!=0),
        part_id INTEGER UNIQUE REFERENCES repair_parts(id),job_id INTEGER REFERENCES jobs(id),reference TEXT NOT NULL,notes TEXT NOT NULL,created TEXT NOT NULL,actor INTEGER NOT NULL REFERENCES users(id))''')
    c.execute('INSERT INTO stock_movements SELECT id,stock_id,delta,part_id,job_id,reference,notes,created,actor FROM movements_v9 WHERE delta!=0')
    c.execute('DROP TABLE movements_v9')
    c.execute('CREATE INDEX ix_stock_item ON stock_movements(stock_id)')
    for action in ('UPDATE','DELETE'):
        c.execute(f"CREATE TRIGGER immutable_stock_{action.lower()} BEFORE {action} ON stock_movements BEGIN SELECT RAISE(ABORT,'Immutable stock movement'); END")
    c.execute('PRAGMA user_version=8')
