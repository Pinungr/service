"""Category/service relationships without rewriting historical job selections."""
def migrate(c):
    c.executescript('''BEGIN IMMEDIATE;
    CREATE TABLE category_services(category_id INTEGER NOT NULL REFERENCES masters(id),
        service_id INTEGER NOT NULL REFERENCES masters(id), PRIMARY KEY(category_id,service_id));
    CREATE INDEX ix_category_service_service ON category_services(service_id,category_id);
    INSERT OR IGNORE INTO category_services
        SELECT category_id,id FROM masters WHERE kind='service' AND category_id IS NOT NULL;
    ''')
    try:
        for name in ('Laptop','Desktop','Printer','Phone'):
            category=c.execute("SELECT id FROM masters WHERE kind='category' AND normalized=?",(name.lower(),)).fetchone()
            if not category:continue
            label=name+' repair'
            c.execute("INSERT OR IGNORE INTO masters(kind,name,normalized) VALUES ('service',?,?)",(label,label.lower()))
            service=c.execute("SELECT id FROM masters WHERE kind='service' AND normalized=?",(label.lower(),)).fetchone()
            c.execute('INSERT OR IGNORE INTO category_services VALUES (?,?)',(category[0],service[0]))
        c.execute('PRAGMA user_version=8');c.commit()
    except Exception:
        c.rollback();raise
