"""Device identity, photo evidence, durable drafts and browsable DB projections."""
import json
import uuid
from pathlib import Path
from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QImageReader
from .domain import RuleError, now, rupees, in_shop
from .persistence import insert
from .migration5 import slug
from .local_files import managed_path, publish, digest


def readable(value, level=0):
    """Plain-text export, with labelled dates and INR instead of raw paise."""
    labels = {'repair_due': 'Tentative repair completion', 'collection_due': 'Tentative customer collection', 'return_due': 'Tentative external return'}
    monetary = {'amount', 'balance', 'cost', 'deposit', 'total', 'estimate', 'transport_agreed', 'assessment_agreed', 'allocated'}
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            label = labels.get(key, key.replace('_', ' ').title())
            if key in ('payload', 'lines', 'snapshot') and isinstance(item, str):
                try:
                    item = json.loads(item)
                except (ValueError, TypeError):
                    pass
            if isinstance(item, (dict, list)):
                lines.append('  ' * level + label + ':')
                lines.append(readable(item, level + 1))
            else:
                display = rupees(item) if key in monetary and isinstance(item, int) else 'Not recorded' if item in ('', None) else item
                lines.append('  ' * level + f'{label}: {display}')
    elif isinstance(value, list):
        for index, item in enumerate(value, 1):
            lines.append('  ' * level + f'Record {index}')
            lines.append(readable(item, level + 1))
        if not value:
            lines.append('  ' * level + 'None recorded')
    else:
        lines.append('  ' * level + str(value))
    return '\n'.join(lines)


def dirty(c, customer_id):
    if customer_id:
        c.execute("INSERT INTO folder_queue(customer_id) VALUES (?) ON CONFLICT(customer_id) DO UPDATE SET revision=revision+1,error=''", (customer_id,))


def customer_folder(c, customer_id):
    row = c.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
    if not row:
        raise RuleError('Select an existing customer.')
    folder = row['folder'] or f"Customers/{slug(row['name'])}_CUST-{customer_id:06d}"
    if not row['folder']:
        c.execute('UPDATE customers SET folder=? WHERE id=?', (folder, customer_id))
    return folder


def device_record(c, customer_id, name, category_id=None, serial='', device_id=None, brand='', model=''):
    if device_id:
        row = c.execute('SELECT * FROM devices WHERE id=? AND customer_id=?', (device_id, customer_id)).fetchone()
        if not row:
            raise RuleError('The selected device does not belong to this customer.')
        return device_id
    ident = insert(c, 'devices', customer_id=customer_id, name=name, category_id=category_id, serial=serial, brand=brand, model=model, created=now())
    folder = customer_folder(c, customer_id) + f'/{slug(name)}_DEV-{ident:06d}'
    c.execute('UPDATE devices SET folder=? WHERE id=?', (folder, ident))
    dirty(c, customer_id)
    return ident


class CustomerRecords:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def document_folder(self, job_id=None, sale_id=None):
        with self.db.transaction() as c:
            row = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone() if job_id else c.execute('SELECT * FROM sales WHERE id=?', (sale_id,)).fetchone() if sale_id else None
            if not row or not row['device_id']:
                return 'managed'
            device = c.execute('SELECT * FROM devices WHERE id=?', (row['device_id'],)).fetchone()
            folder = self._device_folder(c, device)
            return folder + '/Repairs/' + slug(row['number']) + '/Documents' if job_id else folder + '/Purchase-Documents'

    def update_device(self, device_id, name, brand='', model='', serial=''):
        self.s.require('owner', 'counter')
        if not name.strip():
            raise RuleError('A product name is required.')
        with self.db.transaction() as c:
            row = c.execute('SELECT * FROM devices WHERE id=?', (device_id,)).fetchone()
            if not row:
                raise RuleError('Device not found.')
            c.execute('UPDATE devices SET name=?,brand=?,model=?,serial=? WHERE id=?', (name.strip(), brand.strip(), model.strip(), serial.strip(), device_id))
            self.s.audit(c, 'customer', row['customer_id'], 'device_details_updated', {'device_id': device_id, 'name': name, 'brand': brand, 'model': model, 'serial': serial})

    def save_draft(self, ident, payload):
        self.s.require('owner', 'counter')
        with self.db.transaction() as c:
            old = c.execute('SELECT actor FROM intake_drafts WHERE id=?', (ident,)).fetchone()
            if old and old[0] != self.s.user['id']:
                raise RuleError('This draft belongs to another staff member.')
            c.execute('INSERT INTO intake_drafts(id,actor,customer_id,payload,updated) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET customer_id=excluded.customer_id,payload=excluded.payload,updated=excluded.updated',
                (ident, self.s.user['id'], payload.get('customer_id'), json.dumps(payload, ensure_ascii=False), now()))
        return ident

    def drafts(self):
        self.s.require('owner', 'counter')
        return self.db.rows('SELECT d.*,c.name AS customer FROM intake_drafts d LEFT JOIN customers c ON c.id=d.customer_id WHERE actor=? ORDER BY updated DESC', (self.s.user['id'],))

    def save_photo(self, image, customer_id, person_role='owner', person_name='', device_id=None, job_id=None, captured=None):
        self.s.require('owner', 'counter')
        if person_role not in ('owner', 'submitter', 'product', 'accessory') or (person_role == 'product') != bool(device_id):
            raise RuleError('Choose whose photo is being saved.')
        if not isinstance(image, QImage) or image.isNull():
            raise RuleError('Photo capture failed. Retake the photo and try again.')
        if person_role in ('submitter', 'accessory') and not person_name.strip():
            raise RuleError('Enter the submitting person’s name before capture.' if person_role == 'submitter'
                            else 'Name the accessory before capturing its photo.')
        image = image.scaled(1920, 1920, Qt.AspectRatioMode.KeepAspectRatio) if max(image.width(), image.height()) > 1920 else image
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, 'JPEG', 90):
            raise RuleError('The captured photo could not be encoded. Please retake it.')
        data = bytes(buffer.data())
        with self.db.transaction() as c:
            folder = customer_folder(c, customer_id)
            owner = c.execute('SELECT name FROM customers WHERE id=?', (customer_id,)).fetchone()[0]
            if device_id:
                device = c.execute('SELECT * FROM devices WHERE id=? AND customer_id=?', (device_id, customer_id)).fetchone()
                if not device:
                    raise RuleError('Device does not belong to this customer.')
                folder = self._device_folder(c, device) + '/Product-Photos'
            elif person_role == 'accessory':
                # Accessories are photographed at the counter before the device record
                # exists, so the evidence is filed under the customer's own folder.
                folder += '/Accessory-Photos'
            else:
                folder += '/Customer-Photos'
            if job_id and not c.execute('SELECT id FROM jobs WHERE id=? AND customer_id=? AND device_id=?', (job_id, customer_id, device_id)).fetchone():
                raise RuleError('Photo job and device do not match.')
            name = owner if person_role == 'owner' else person_name.strip() if person_role in ('submitter', 'accessory') else device['name']
            relative = folder + '/' + uuid.uuid4().hex + '.jpg'
            target = managed_path(self.db.root, relative)
            publish(target, data)
            # An interrupted transaction can leave an unreferenced UUID file. Never overwrite/delete it.
            ident = insert(c, 'attachments', job_id=job_id, customer_id=customer_id, device_id=device_id,
                kind='product_photo' if device_id else 'accessory_photo' if person_role == 'accessory' else 'customer_photo', path=relative, title=f'{person_role.title()}: {name}',
                person_role=person_role, person_name=name, captured=captured or now(), sha256=digest(data), created=now(), actor=self.s.user['id'])
            if person_role == 'owner':
                c.execute('UPDATE customers SET current_photo_id=? WHERE id=?', (ident, customer_id))
            self.s.audit(c, 'customer', customer_id, 'photo_saved', {'attachment': ident, 'role': person_role, 'name': name})
        return ident

    def import_product_photo(self, source, customer_id, device_id, job_id=None):
        self.s.require('owner', 'counter')
        source = Path(source)
        if not source.is_file() or source.stat().st_size > 50 * 1024**2:
            raise RuleError('Choose a local image smaller than 50 MB.')
        reader = QImageReader(str(source))
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 80_000_000:
            raise RuleError('Choose a supported image with at most 80 million pixels.')
        return self.save_photo(reader.read(), customer_id, 'product', device_id=device_id, job_id=job_id)

    def recover_photo(self, attachment_id, source):
        """Restore the identical lost file without rewriting evidence or its history."""
        self.s.require('owner', 'counter')
        row = self.db.one('SELECT * FROM attachments WHERE id=? AND sha256 IS NOT NULL', (attachment_id,))
        if not row:
            raise RuleError('Select a photo with a recorded checksum.')
        source = Path(source)
        if not source.is_file() or source.stat().st_size > 50 * 1024**2:
            raise RuleError('Choose the original photo from a backup, up to 50 MB.')
        data = source.read_bytes()
        if digest(data) != row['sha256']:
            raise RuleError('This is not the original photo. Select the matching file from a verified backup.')
        with self.db.transaction() as c:
            target = managed_path(self.db.root, row['path'])
            if target.exists():
                raise RuleError('The saved file still exists. It has not been overwritten.')
            publish(target, data)
            self.s.audit(c, 'customer', row['customer_id'], 'photo_recovered', {'attachment': attachment_id})

    @staticmethod
    def _device_folder(c, row):
        folder = row['folder'] or customer_folder(c, row['customer_id']) + f"/{slug(row['name'])}_DEV-{row['id']:06d}"
        if not row['folder']:
            c.execute('UPDATE devices SET folder=? WHERE id=?', (folder, row['id']))
        return folder

    def overview(self, customer_id):
        self.s.require()
        customer = self.db.one('SELECT * FROM customers WHERE id=?', (customer_id,))
        if not customer:
            raise RuleError('Customer not found.')
        jobs = self.db.rows('''SELECT j.*,COALESCE(m.name,tm.name,u.name,'Unassigned') AS responsible,
            (SELECT COALESCE(sum(amount),0) FROM entries WHERE job_id=j.id AND account_type='customer') AS balance,
            (SELECT path FROM attachments WHERE device_id=j.device_id AND kind='product_photo' ORDER BY id DESC LIMIT 1) AS thumbnail
            FROM jobs j LEFT JOIN assignments a ON a.id=j.assignment_id LEFT JOIN masters m ON m.id=a.contact_id LEFT JOIN users u ON u.id=a.technician_id LEFT JOIN masters tm ON tm.id=a.technician_master_id
            WHERE j.customer_id=? ORDER BY j.id DESC''', (customer_id,))
        holdings = self.db.rows('''SELECT i.job_id,i.type,h.location,h.quantity FROM items i JOIN holdings h ON h.item_id=i.id JOIN jobs j ON j.id=i.job_id WHERE j.customer_id=? AND h.quantity>0''', (customer_id,))
        by_job = {}
        for holding in holdings:
            by_job.setdefault(holding['job_id'], []).append(holding)
        outstanding, history, sets = [], [], {key: set() for key in ('outstanding', 'under_repair_in_shop', 'vendors', 'service_centres', 'in_transit', 'ready', 'collected')}
        device_ready = {}
        for job in jobs:
            from .lifecycle import Lifecycle
            lifecycle = Lifecycle(self.s).snapshot(job['id'])
            job['route_label'] = lifecycle['route_label']
            job['current_status'] = lifecycle['current_status']
            job['current_location'] = lifecycle['current_location']
            job['current_card'] = lifecycle['current_card']
            job['warranty_indicator'] = lifecycle['warranty_indicator']
            job['next_action'] = lifecycle['next_action']
            job['last_update'] = lifecycle['timeline'][-1]['time'] if lifecycle['timeline'] else job['received']
            rows = by_job.get(job['id'], [])
            remaining = [h for h in rows if h['location'] != 'customer' and not h['location'].startswith('exception:')]
            collected = any(h['location'] == 'customer' for h in rows)
            job['location'] = ', '.join(sorted({h['location'] for h in remaining})) or 'No items held'
            job['collection_status'] = 'Partially collected' if collected and remaining else 'Collected' if collected else 'Resolved' if not remaining else 'Awaiting collection'
            job['ready'] = bool(remaining) and not job['hold_reason'] and all(in_shop(h['location']) for h in remaining) and (
                job['stage'] == 'ready_repaired' and job['test_result'] == 'passed' or job['stage'] == 'ready_unrepaired' and bool(job['outcome']))
            job['product'] = f"{job['device']} · DEV-{job['device_id']:06d}" if job['device_id'] else job['device']
            job['tentative_collection'] = job['collection_due'] or 'Not set'
            device = job['device_id'] or -job['id']
            if remaining:
                outstanding.append(job)
                sets['outstanding'].add(device)
                device_ready[device] = device_ready.get(device, True) and job['ready']
                for h in remaining:
                    prefix = h['location'].split(':')[0]
                    key = {'vendor': 'vendors', 'centre': 'service_centres', 'transit': 'in_transit'}.get(prefix)
                    if key:
                        sets[key].add(device)
                    if h['type'] == 'device' and prefix in ('shop', 'technician') and job['stage'] in ('received', 'inspection', 'warranty_check', 'route_selection', 'diagnosis', 'awaiting_estimate', 'awaiting_approval', 'approved', 'under_repair', 'waiting_parts', 'testing', 'technician_testing', 'final_qc', 'billing'):
                        sets['under_repair_in_shop'].add(device)
            else:
                history.append(job)
                if collected:
                    sets['collected'].add(device)
        sets['ready'] = {device for device, ready in device_ready.items() if ready}
        sets['collected'] -= sets['outstanding']
        from .visits import Visits
        visits = Visits(self.s).for_customer(customer_id)
        by_visit = {}
        for job in jobs:
            by_visit.setdefault(job['visit_id'], []).append(job)
        for visit in visits:
            visit['product_list'] = [dict(job_id=j['id'], number=j['number'], product=j['product'],
                                      status=j['current_status'], location=j['current_location'])
                                 for j in sorted(by_visit.get(visit['id'], []), key=lambda r: r['id'])]
        return dict(customer=customer, outstanding=outstanding, history=history, visits=visits,
                    counts={k: len(v) for k, v in sets.items()},
            all_ready=bool(outstanding) and all(j['ready'] for j in outstanding),
            devices=self.db.rows('SELECT * FROM devices WHERE customer_id=? ORDER BY id', (customer_id,)),
            photos=self.db.rows("SELECT * FROM attachments WHERE customer_id=? AND kind='customer_photo' ORDER BY id DESC", (customer_id,)))

    def _summary(self, c, customer_id, relative, text):
        data = ('RepairShop Manager — generated from the database; edit records in the application.\n\n' + text + '\n').encode('utf-8')
        target = managed_path(self.db.root, relative)
        old = c.execute('SELECT sha256 FROM folder_files WHERE path=?', (relative,)).fetchone()
        if target.exists():
            current = digest(target.read_bytes())
            if current == digest(data):
                pass  # Resumes after a successful file write but interrupted DB commit.
            elif not old or current != old[0]:
                raise RuleError('A browsable summary was edited outside the app. Move that file aside, then Retry folders: ' + relative)
            else:
                publish(target, data, replace=True)
        else:
            publish(target, data)
        c.execute('INSERT INTO folder_files(path,customer_id,sha256) VALUES (?,?,?) ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256', (relative, customer_id, digest(data)))

    def sync_customer(self, customer_id):
        if self.db.readonly:
            return
        # The worker holds the same guard used by backups: summaries and referenced photos form one snapshot.
        with self.db.transaction() as c:
            folder = customer_folder(c, customer_id)
            managed_path(self.db.root, folder + '/Customer-Photos').mkdir(parents=True, exist_ok=True)
            customer = dict(c.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone())
            overview = self.overview(customer_id)
            lines = [f'Customer ID: CUST-{customer_id:06d}', *[f'{k.title()}: {customer[k]}' for k in ('name', 'phone', 'email', 'address', 'alternate')],
                'Counts (overlapping location/progress views; do not add): ' + json.dumps(overview['counts']),
                'All outstanding items ready for collection' if overview['all_ready'] else 'Some items are not ready, or no items are outstanding.',
                'Customer balance: ' + rupees(c.execute("SELECT COALESCE(sum(amount),0) FROM entries WHERE account_type='customer' AND account_id=?", (customer_id,)).fetchone()[0]),
                'Photo history:\n' + readable(overview['photos'])]
            self._summary(c, customer_id, folder + '/customer-details.txt', '\n'.join(lines))
            for device in c.execute('SELECT * FROM devices WHERE customer_id=?', (customer_id,)).fetchall():
                device_folder = self._device_folder(c, device)
                managed_path(self.db.root, device_folder + '/Product-Photos').mkdir(parents=True, exist_ok=True)
                device_jobs = c.execute('SELECT * FROM jobs WHERE device_id=? ORDER BY id', (device['id'],)).fetchall()
                category = c.execute('SELECT name FROM masters WHERE id=?', (device['category_id'],)).fetchone()
                details = dict(device)
                details['category'] = category[0] if category else 'Not specified'
                details['repairs'] = [dict(j) for j in device_jobs]
                details['sales'] = [dict(r) for r in c.execute('SELECT * FROM sales WHERE device_id=?', (device['id'],))]
                details['photos'] = [dict(r) for r in c.execute('SELECT * FROM attachments WHERE device_id=?', (device['id'],))]
                self._summary(c, customer_id, device_folder + '/product-details.txt', 'Device ID: DEV-%06d\n%s' % (device['id'], readable(details)))
                for job in device_jobs:
                    job_folder = device_folder + '/Repairs/' + slug(job['number'])
                    details = dict(job)
                    details['date_note'] = 'repair_due, collection_due and return_due are tentative dates.'
                    for table in ('items', 'assignments', 'work', 'warranty', 'quotes', 'entries', 'attachments', 'job_cards', 'repair_parts', 'part_warranties'):
                        details[table] = [dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE job_id=?', (job['id'],))]
                    details['warranty_claims'] = [dict(r) for r in c.execute('SELECT * FROM warranty_claims WHERE new_job_id=? OR original_job_id=?',(job['id'],job['id']))]
                    details['approvals'] = [dict(r) for r in c.execute('SELECT d.* FROM decisions d JOIN quotes q ON q.id=d.quote_id WHERE q.job_id=?', (job['id'],))]
                    details['expenses'] = [dict(r) for r in c.execute('SELECT e.*,a.amount AS allocated FROM expenses e JOIN expense_allocations a ON a.expense_id=e.id WHERE a.job_id=?', (job['id'],))]
                    details['holdings'] = [dict(r) for r in c.execute('SELECT i.description,i.type,h.* FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND h.quantity>0', (job['id'],))]
                    details['handovers'] = [dict(r) for r in c.execute('SELECT m.* FROM movements m JOIN items i ON i.id=m.item_id WHERE i.job_id=?', (job['id'],))]
                    summary_row = next((r for r in overview['outstanding'] + overview['history'] if r['id'] == job['id']), {})
                    details['overview'] = summary_row
                    self._summary(c, customer_id, job_folder + '/job-details.txt', readable(details))
            c.execute('DELETE FROM folder_queue WHERE customer_id=?', (customer_id,))
        return managed_path(self.db.root, folder)

    def sync_pending(self, limit=10):
        errors = []
        for row in self.db.rows("SELECT customer_id FROM folder_queue WHERE error='' ORDER BY customer_id LIMIT ?", (limit,)):
            try:
                self.sync_customer(row['customer_id'])
            except Exception as exc:
                with self.db.transaction() as c:
                    c.execute('UPDATE folder_queue SET error=? WHERE customer_id=?', (str(exc), row['customer_id']))
                errors.append(str(exc))
        if errors:
            raise RuleError('Folder generation needs attention. Database records are safe. ' + '\n'.join(errors))
