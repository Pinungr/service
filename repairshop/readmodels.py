"""Read-only list projections that used to be written inline in desktop screens.

Each one states the permission it needs and applies the same job scope as every other
job read, so a list can never show more than the record screens behind it.
"""
from .domain import phone, RuleError


def needs_setup(db):
    """True until the first-run setup has created the owner login."""
    return not db.one('SELECT id FROM users LIMIT 1')


def schema_version(db):
    return db.one('PRAGMA user_version')['user_version']


class ReadModels:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def quotes(self, limit=300):
        self.s.require_permission('create_quote')
        scope, args = self.s.scope_jobs()
        return self.db.rows('''SELECT q.id,q.job_id,q.version,q.state,q.scope,q.total,q.valid_until,q.created,
                j.number,j.device,c.name AS customer
            FROM quotes q JOIN jobs j ON j.id=q.job_id JOIN customers c ON c.id=j.customer_id
            WHERE ''' + scope + ' ORDER BY q.id DESC LIMIT ?', (*args, limit))

    def job_quotes(self, job_id):
        self.s.require_job_access(job_id)
        return self.db.rows('''SELECT q.id,q.job_id,q.version,q.state,q.scope,q.total,q.valid_until,q.created,
                (SELECT d.decision FROM decisions d WHERE d.quote_id=q.id ORDER BY d.id DESC LIMIT 1) AS decision
            FROM quotes q WHERE q.job_id=? ORDER BY q.version DESC''', (job_id,))

    def entries(self, account_type, limit=300, account_id=None, job_id=None):
        self.s.require_permission('collect_payment' if account_type == 'customer' else 'vendor_accounts')
        where, args = ['e.account_type=?'], [account_type]
        if account_id:
            where.append('e.account_id=?')
            args.append(account_id)
        if job_id:
            where.append('e.job_id=?')
            args.append(job_id)
        names = ('(SELECT name FROM customers WHERE id=e.account_id)' if account_type == 'customer'
                 else '(SELECT name FROM masters WHERE id=e.account_id)')
        return self.db.rows(f'''SELECT e.id,e.account_id,{names} AS account,e.job_id,j.number,e.posted,e.kind,e.amount,
                e.method,e.reference,e.notes,e.reverses_id,
                EXISTS(SELECT 1 FROM entries r WHERE r.reverses_id=e.id) AS reversed
            FROM entries e LEFT JOIN jobs j ON j.id=e.job_id WHERE ''' + ' AND '.join(where)
            + ' ORDER BY e.id DESC LIMIT ?', (*args, limit))

    def vendor_estimates(self, contact_id):
        self.s.require_permission('vendor_accounts')
        return self.db.rows('''SELECT a.reference,a.estimate,j.number,j.device,j.stage FROM assignments a
            JOIN jobs j ON j.id=a.job_id WHERE a.contact_id=? AND j.stage NOT IN ('collected','closed')
            ORDER BY a.id DESC LIMIT 100''', (contact_id,))

    def account_parties(self, account_type):
        """Who an account entry may be posted against."""
        self.s.require_permission('collect_payment' if account_type == 'customer' else 'vendor_accounts')
        if account_type == 'vendor':
            return self.db.rows("SELECT id,name,kind,active FROM masters WHERE kind IN ('vendor','centre') ORDER BY active DESC,name")
        raise RuleError('Search customers by name or phone instead.')

    def outbox(self, limit=300):
        self.s.require_permission('messaging')
        return self.db.rows('''SELECT id,job_id,event,channel,destination,state,attempts,error,provider_id,created,updated
            FROM outbox ORDER BY id DESC LIMIT ?''', (limit,))

    def outbox_message(self, ident):
        self.s.require_permission('messaging')
        row = self.db.one('SELECT * FROM outbox WHERE id=?', (ident,))
        if not row:
            raise RuleError('Message not found.')
        return row

    def recipients(self):
        self.s.require_permission('messaging_admin')
        return self.db.rows('SELECT * FROM recipients ORDER BY kind,destination')

    def issued_documents(self, limit=300):
        self.s.require_permission('messaging_admin')
        return self.db.rows("SELECT id,title,created,job_id FROM attachments WHERE kind='issued_document' ORDER BY id DESC LIMIT ?", (limit,))

    def backups(self, limit=100):
        self.s.require_permission('backup_restore')
        return self.db.rows('SELECT id,path,kind,created,state,external_state,error FROM backups ORDER BY id DESC LIMIT ?', (limit,))

    def staff(self):
        self.s.require_permission('user_management')
        return self.db.rows('SELECT id,username,name,role,active FROM users ORDER BY active DESC,name')

    def colleagues(self):
        """Active staff a product can be physically handed to."""
        self.s.require()
        return self.db.rows('SELECT id,name,role FROM users WHERE active=1 ORDER BY name')

    def technicians(self):
        self.s.require()
        return self.db.rows("SELECT id,name,user_id FROM masters WHERE kind='technician' AND active=1 ORDER BY name")

    def attachments(self, job_id):
        self.s.require_job_access(job_id)
        device = (self.db.one('SELECT device_id FROM jobs WHERE id=?', (job_id,)) or {}).get('device_id')
        return self.db.rows('''SELECT id,job_id,device_id,customer_id,kind,title,created,captured,person_role
            FROM attachments WHERE job_id=? OR (device_id IS NOT NULL AND device_id=?) ORDER BY id DESC''', (job_id, device))

    def customers_with_phone(self, number, exclude_id=None):
        """Existing customers already using this phone number, for the duplicate choice."""
        self.s.require_permission('customer_records')
        normalized = phone(number)
        if not normalized:
            return []
        return self.db.rows('''SELECT id,name,phone,alternate,address FROM customers
            WHERE (phone=? OR alternate=?) AND id IS NOT ? ORDER BY name LIMIT 20''', (normalized, normalized, exclude_id))

    def attachment_for(self, path):
        """The attachment record a document generator just wrote, found by its managed path."""
        from pathlib import Path
        relative = Path(path).resolve().relative_to(self.db.root).as_posix()
        return self.db.one('SELECT id,title,kind,job_id,created FROM attachments WHERE path=?', (relative,))

    def attachment_file(self, ident):
        """One stored file and its location, after the same checks as the record it belongs to.

        Callers receive a confined path inside the managed data folder only; an attachment
        id can never be turned into a read of an arbitrary file.
        """
        from .local_files import managed_path
        from .domain import NotFound
        self.s.require()
        row = self.db.one('SELECT id,job_id,sale_id,customer_id,device_id,kind,path,title FROM attachments WHERE id=?', (ident,))
        if not row:
            raise NotFound('File not found.')
        if row['kind'] == 'internal_document':
            self.s.require_permission('view_internal_cost')
        if row['job_id']:
            self.s.require_job_access(row['job_id'])
        elif row['customer_id'] or row['device_id']:
            self.s.require_permission('customer_records')
        elif row['sale_id']:
            self.s.require_permission('register_sale')
        elif row['kind'] == 'directory_photo':
            self.s.require_permission('directories')
        else:
            self.s.require_permission('view_all_jobs')
        path = managed_path(self.db.root, row['path'])
        if not path.is_file():
            raise NotFound('This file is missing from the data folder. Its record is kept; restore it from a verified backup.')
        return row, path

    def item_names(self, job_id):
        self.s.require_job_access(job_id)
        return {r['id']: r['description'] for r in self.db.rows('SELECT id,description FROM items WHERE job_id=?', (job_id,))}

    def customer(self, ident):
        self.s.require_permission('customer_records')
        row = self.db.one('SELECT * FROM customers WHERE id=?', (ident,))
        if not row:
            from .domain import NotFound
            raise NotFound('Customer not found.')
        return row

    def device(self, ident):
        self.s.require_permission('customer_records')
        row = self.db.one('SELECT * FROM devices WHERE id=?', (ident,))
        if not row:
            from .domain import NotFound
            raise NotFound('Device not found.')
        return row

    def device_photos(self, ident):
        self.device(ident)
        return self.db.rows("SELECT * FROM attachments WHERE device_id=? AND kind='product_photo' ORDER BY id DESC", (ident,))

    def accessories(self, category_id):
        self.s.require()
        return self.db.rows('''SELECT m.id,m.name FROM masters m JOIN category_accessories ca ON ca.accessory_id=m.id
            WHERE ca.category_id=? AND m.active=1 ORDER BY m.name''', (category_id,))

    def setup_list(self, kind, include_inactive=True):
        self.s.require()
        rows = self.db.rows('SELECT id,kind,name,contact,details,category_id,active,user_id FROM masters WHERE kind=? '
                            + ('' if include_inactive else 'AND active=1 ') + 'ORDER BY active DESC,name', (kind,))
        if kind == 'service':
            links = {}
            for r in self.db.rows('SELECT service_id,category_id FROM category_services'):
                links.setdefault(r['service_id'], []).append(r['category_id'])
            for row in rows:
                row['category_ids'] = links.get(row['id'], [])
        return rows

    def custody_destinations(self):
        """Every holder an item may be handed to from the generic dispatch & receive screen."""
        self.s.require_permission('handover')
        from .domain import staff_custody
        rows = [dict(value='customer', label='Customer collection')]
        rows += [dict(value=staff_custody(r['id']), label=r['name'] + ' · ' + r['role'].title())
                 for r in self.db.rows('SELECT id,name,role FROM users WHERE active=1 ORDER BY name')]
        for kind, prefix, title in (('vendor', 'vendor', 'Third-party repairer'), ('centre', 'centre', 'Service centre'),
                                    ('transporter', 'transit', 'Bus / transport')):
            rows += [dict(value=prefix + ':' + r['name'], label=title + ': ' + r['name']) for r in self.s.masters(kind)]
        # Directory technicians are custodians by id, the same token the guided handover writes.
        rows += [dict(value='technician:master-' + str(r['id']), label='Technician: ' + r['name'])
                 for r in self.s.masters('technician')]
        rows += [dict(value='transit:Unspecified', label='In transit (record carrier below)'),
                 dict(value='exception:Resolved', label='Documented exception (owner)')]
        return rows
