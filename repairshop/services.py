"""Application commands. Permissions and invariants apply equally to UI and tests."""
import json
import secrets
import uuid
from datetime import date
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from .domain import RuleError, now, norm, phone, day, STAGES, ROUTES, MASTER_KINDS, in_shop, staff_custody, custody_kind
from .permissions import allowed
from .persistence import insert
from .customer_records import dirty, customer_folder, device_record
from .local_files import managed_path, digest

# Intake condition of a received device or accessory. "Not tested" matters because the
# owner often cannot power up an accessory at the counter.
ITEM_CONDITIONS = ("Working", "Not Working", "Not Tested", "Damaged")

hashes = PasswordHasher()


class Service:
    def __init__(self, db):
        self.db = db
        self.user = None

    def require(self, *roles):
        """Confirm the session is still a live, active user. Roles are legacy; prefer
        `require_permission`, which states the operation instead of who may do it."""
        if not self.user:
            raise RuleError("Please sign in.")
        live = self.db.one("SELECT * FROM users WHERE id=?", (self.user["id"],))
        if not live or not live["active"] or live["role"] not in (roles or ("owner", "counter", "technician")):
            raise RuleError("Your role cannot perform this action.")
        self.user = live
        return live

    def require_permission(self, *permissions):
        """The authoritative check: may this signed-in user perform this operation?

        Every permission is listed in `permissions.py`, so what a role can do is one
        readable table rather than a role name repeated through the service layer.
        """
        live = self.require()
        for permission in permissions:
            if not allowed(live['role'], permission):
                raise RuleError('Your role cannot perform this action: '
                                + permission.replace('_', ' ') + '.')
        return live

    def may(self, permission):
        return bool(self.user) and allowed(self.user['role'], permission)

    # ---- job-level access -----------------------------------------------
    # One definition of "this repair is mine", used by every job read and write. A user
    # without `view_all_jobs` reaches a repair only when it is assigned to them (by login
    # account or through the directory technician linked to it) or when they are actually
    # holding the product. Knowing another job's id is never enough.
    MINE = """(EXISTS(SELECT 1 FROM assignments a WHERE a.id={alias}.assignment_id
            AND (a.technician_id=:uid OR (a.technician_master_id IS NOT NULL
                AND a.technician_master_id IN (SELECT m.id FROM masters m
                    WHERE m.kind='technician' AND m.user_id IS NOT NULL AND m.user_id=:uid))))
        OR EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id
            WHERE i.job_id={alias}.id AND h.quantity>0
            AND (h.location='staff:' || :uid OR h.location='technician:' || :uid)))"""

    def scope_jobs(self, alias='j'):
        """SQL predicate and arguments limiting a job query to what this user may see."""
        if self.may('view_all_jobs') or not self.user:
            return '1=1', []
        sql = self.MINE.format(alias=alias)
        # The driver uses positional parameters, so expand the repeated id by hand.
        return sql.replace(':uid', '?'), [self.user['id']] * sql.count(':uid')

    def job_access(self, job_id, c=None):
        if self.may('view_all_jobs'):
            return True
        sql = 'SELECT 1 FROM jobs j WHERE j.id=? AND ' + self.MINE.format(alias='j')
        sql = sql.replace(':uid', '?')
        args = (job_id, *([self.user['id']] * (sql.count('?') - 1)))
        return bool(c.execute(sql, args).fetchone() if c else self.db.one(sql, args))

    def require_job_access(self, job_id, c=None):
        """The one guard every job-specific read and write goes through."""
        self.require()
        if not self.job_access(job_id, c):
            raise RuleError('This repair is not assigned to you.')
        return job_id

    def receiving_custody(self, location=None):
        """Where an item goes when this user physically takes it: to this user.

        The shop has no storage custodian, so there is nothing to choose. An explicit
        value is only accepted when it is the signed-in user's own identity, which means
        nobody can record a colleague as having taken delivery of anything.
        """
        mine = staff_custody(self.user['id'])
        if location and str(location) != mine:
            raise RuleError('The receiving person is taken from your sign-in and cannot be '
                            'recorded as someone else or as a storage place.')
        return mine

    def custodian(self, location):
        """Readable identity for one custody location: who has it, and what they are."""
        location = str(location or '')
        kind = custody_kind(location)
        token = location.split(':', 1)[1] if ':' in location else ''
        if kind == 'staff':
            row = self.db.one('SELECT name,role FROM users WHERE id=?', (token,))
            return dict(name=(row or {}).get('name', 'Staff member'), kind='staff',
                        role=(row or {}).get('role', 'staff').title())
        if kind == 'technician':
            if token.startswith('master-'):
                row = self.db.one("SELECT name FROM masters WHERE id=? AND kind='technician'", (token[7:],))
                return dict(name=(row or {}).get('name', 'Technician'), kind='technician', role='Technician')
            row = self.db.one('SELECT name,role FROM users WHERE id=?', (token,))
            return dict(name=(row or {}).get('name', 'Technician'), kind='technician', role='Technician')
        if kind == 'shop':
            return dict(name=token or self.db.setting('shop_name', 'Shop'), kind='shop', role='Shop storage')
        if kind == 'customer':
            return dict(name='Customer', kind='customer', role='Customer')
        labels = {'vendor': 'Third Party', 'centre': 'Authorized Service Center',
                  'transit': 'In transit', 'exception': 'Unresolved'}
        return dict(name=token or location, kind=kind, role=labels.get(kind, kind.title()))

    def guard_job_access(self, job, c=None):
        self.require_job_access(job['id'], c)
        return job

    def audit(self, c, entity, ident, action, payload):
        insert(c, "audit", actor=self.user["id"] if self.user else None, created=now(), entity=entity, entity_id=ident, action=action, payload=json.dumps(payload, ensure_ascii=False))
        customer_id = ident if entity == 'customer' or (entity == 'account' and payload.get('account_type') == 'customer') else None
        if entity in ('job', 'sale') and ident:
            row = c.execute('SELECT customer_id FROM ' + ('jobs' if entity == 'job' else 'sales') + ' WHERE id=?', (ident,)).fetchone()
            customer_id = row[0] if row else None
        dirty(c, customer_id)
        if entity in ('settings', 'master', 'staff'):
            c.execute("INSERT INTO folder_queue(customer_id) SELECT id FROM customers WHERE 1 ON CONFLICT(customer_id) DO UPDATE SET revision=revision+1,error=''")


    def setup(self, shop, username, password, name="Owner"):
        if len(password) < 10 or not shop.strip() or not username.strip():
            raise RuleError("Shop and username are required; use a password of at least 10 characters.")
        with self.db.transaction() as c:
            if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise RuleError("First-run setup has already been completed.")
            insert(c, "users", username=norm(username), name=name, password=hashes.hash(password), role="owner")
            defaults = {"shop_name": shop, "currency": "INR", "timezone": "Asia/Kolkata", "address": "", "hours": "", "messaging_mode": "test", "notifications_paused": False, "backup_retention": 30, "archive_days": 90, "decline_policy": "NO_CUSTOMER_CHARGE"}
            for key, value in defaults.items():
                insert(c, "settings", key=key, value=json.dumps(value))
        self.login(username, password)
        for kind, names in {"category": ["Laptop", "Desktop", "Printer", "Phone"], "service": ["Laptop repair", "Diagnosis", "Warranty assessment"], "transport_method": ["Courier", "Bus", "Train", "Hand delivery"], "payment_method": ["Cash", "UPI", "Bank"], "accessory": ["Adapter", "Mouse", "Wi-Fi dongle", "Loose RAM", "Bag"]}.items():
            for value in names:
                self.save_master(kind, value)
        laptop = self.db.one("SELECT id FROM masters WHERE kind='category' AND name='Laptop'")["id"]
        for accessory in self.masters("accessory"):
            self.save_master("accessory", accessory["name"], category_id=laptop)
        for category in self.masters('category'):
            self.save_master('service',category['name']+' repair',category_ids=[category['id']])

    def login(self, username, password):
        row = self.db.one("SELECT * FROM users WHERE username=? AND active=1", (norm(username),))
        try:
            if not row:
                hashes.verify(hashes.hash(secrets.token_hex(16)), password)
            hashes.verify(row["password"], password)
        except (VerificationError, TypeError):
            raise RuleError("Incorrect username or password.")
        self.user = row
        return {k: v for k, v in row.items() if k != "password"}

    def save_staff(self, username, name, role, password="", ident=None, active=True):
        self.require("owner")
        if role not in ("owner", "counter", "technician") or not name.strip():
            raise RuleError("Choose a role and enter a name.")
        if (not ident or password) and len(password) < 10:
            raise RuleError("Use at least 10 characters for a staff password.")
        with self.db.transaction() as c:
            if ident:
                old = c.execute("SELECT * FROM users WHERE id=?", (ident,)).fetchone()
                if old["role"] == "owner" and (role != "owner" or not active) and c.execute("SELECT count(*) FROM users WHERE role='owner' AND active=1").fetchone()[0] <= 1:
                    raise RuleError("Keep at least one active owner.")
                c.execute("UPDATE users SET username=?,name=?,role=?,active=?,password=? WHERE id=?", (norm(username), name, role, int(active), hashes.hash(password) if password else old["password"], ident))
            else:
                ident = insert(c, "users", username=norm(username), name=name, role=role, password=hashes.hash(password))
            self.audit(c, "staff", ident, "saved", {"name": name, "role": role, "active": active})
        return ident

    def settings(self, values):
        self.require("owner")
        allowed = {"shop_name", "address", "hours", "timezone", "decline_policy", "backup_destination", "external_backup", "backup_retention", "archive_days", "messaging_mode", "notifications_paused", "whatsapp", "smtp", "templates", "reminder_days", 'message_template', 'email_subject', 'paper_size', 'include_photos'}
        if not set(values) <= allowed:
            raise RuleError("Unsupported setting. Secrets belong in Windows Credential Manager.")
        if "archive_days" in values and int(values["archive_days"]) not in (60, 90):
            raise RuleError("Choose a 60 or 90 day archive interval.")
        if "backup_retention" in values and int(values["backup_retention"]) < 1:
            raise RuleError("Keep at least one daily backup.")
        from zoneinfo import ZoneInfo
        if "timezone" in values:
            ZoneInfo(values["timezone"])
        from string import Formatter
        for key in ('message_template','email_subject'):
            if key in values:
                for _,field,format_spec,conversion in Formatter().parse(values[key]):
                    if field and (field not in ('shop_name','job_number','device','message','event','shop_address','shop_hours') or format_spec or conversion):
                        raise RuleError('Unsupported template variable or formatting. Use the listed simple variables.')
        if 'reminder_days' in values and (not isinstance(values['reminder_days'],int) or not 0 <= values['reminder_days'] <= 90):
            raise RuleError('Reminder interval must be 0 (off) to 90 days.')
        if 'paper_size' in values and values['paper_size'] not in ('A4', 'A5'):
            raise RuleError('Choose A4 or A5 as the default paper size.')
        if 'include_photos' in values and not isinstance(values['include_photos'], bool):
            raise RuleError('Choose Yes or No for including photos in customer messages.')
        with self.db.transaction() as c:
            for k, v in values.items():
                c.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v)))
            self.audit(c, "settings", None, "saved", values)
        if 'timezone' in values:
            self.db.apply_timezone()

    def masters(self, kind):
        return self.db.rows("SELECT * FROM masters WHERE kind=? AND active=1 ORDER BY name", (kind,))

    def services_for_category(self,category_id):
        if not category_id:return []
        return self.db.rows("""SELECT m.*,NOT EXISTS(SELECT 1 FROM category_services cs WHERE cs.service_id=m.id) AS general
            FROM masters m WHERE m.kind='service' AND m.active=1 AND
            (NOT EXISTS(SELECT 1 FROM category_services cs WHERE cs.service_id=m.id) OR EXISTS(SELECT 1 FROM category_services cs WHERE cs.service_id=m.id AND cs.category_id=?)) ORDER BY m.name""",(category_id,))

    def validate_intake_service(self,category_id,service_id):
        if category_id and not self.db.one("SELECT 1 FROM masters WHERE id=? AND kind='category' AND active=1",(category_id,)):
            raise RuleError('Choose an active product category.')
        if service_id and service_id not in {r['id'] for r in self.services_for_category(category_id)}:
            raise RuleError('Choose a repair/service that applies to this product category.')

    PARTY_KINDS = ('vendor', 'centre', 'supplier')

    def save_master(self, kind, name, contact="", details="", category_id=None, ident=None, active=True, category_ids=None, photo_id=None, specialization=None, user_id=None, **address_fields):
        self.require_permission('directories')
        if kind not in MASTER_KINDS or not norm(name):
            raise RuleError("Choose a directory and enter a name.")
        if user_id is not None and kind != 'technician':
            raise RuleError("Only a technician directory entry can be linked to a login account.")
        from . import addresses
        if not set(address_fields) <= set(addresses.FIELDS):
            raise RuleError("Unknown directory address field.")
        if address_fields and kind not in self.PARTY_KINDS:
            raise RuleError("Postal address applies to third parties, service centres and suppliers.")
        profile = dict(addresses.clean(address_fields, required=False)) if address_fields else {}
        if kind in self.PARTY_KINDS and address_fields:
            if not contact.strip():
                raise RuleError("Enter a mobile number for this third party.")
            profile = addresses.clean(address_fields, required=True)
        if specialization is not None:
            profile['specialization'] = specialization.strip()
        if photo_id is not None:
            profile['photo_id'] = photo_id
        with self.db.transaction() as c:
            if photo_id and not c.execute("SELECT 1 FROM attachments WHERE id=?", (photo_id,)).fetchone():
                raise RuleError("The selected directory photo is not available.")
            if user_id is not None:
                # The link is what lets job ownership be checked for a technician who is
                # assigned through the directory rather than through their login account.
                profile['user_id'] = self._technician_login(c, user_id, ident)
            existing = c.execute("SELECT * FROM masters WHERE kind=? AND normalized=?", (kind, norm(name))).fetchone()
            new_record=not existing and not ident
            if existing and not ident:
                # Re-adding an existing normalized directory entry means the owner
                # intends to reuse/update that entry, not create a silent no-op.
                # Preserve existing display name and optional text when quick-add omitted it, while
                # always applying the requested active state (so an inactive entry
                # can be reactivated simply by adding it again).
                ident = existing["id"]
                merged_contact = contact if contact.strip() else existing["contact"]
                merged_details = details if details.strip() else existing["details"]
                c.execute("UPDATE masters SET contact=?,details=?,active=? WHERE id=?",
                          (merged_contact, merged_details, int(active), ident))
            elif ident:
                c.execute("UPDATE masters SET name=?,normalized=?,contact=?,details=?,active=? WHERE id=?", (name.strip(), norm(name), contact, details, int(active), ident))
            else:
                ident = insert(c, "masters", kind=kind, name=name.strip(), normalized=norm(name), contact=contact, details=details, category_id=category_id)
            if kind == "accessory" and category_id:
                c.execute("INSERT OR IGNORE INTO category_accessories VALUES (?,?)", (category_id, ident))
            if kind=='service':
                categories=category_ids if category_ids is not None else [category_id] if category_id and new_record else None
                if categories is not None:
                    if any(not c.execute("SELECT 1 FROM masters WHERE id=? AND kind='category'",(category,)).fetchone() for category in categories):
                        raise RuleError('Choose valid product categories for this service.')
                    c.execute('DELETE FROM category_services WHERE service_id=?',(ident,))
                    for category in set(categories):c.execute('INSERT INTO category_services VALUES (?,?)',(category,ident))
            if profile:
                c.execute("UPDATE masters SET " + ",".join(k + "=?" for k in profile) + " WHERE id=?", (*profile.values(), ident))
            self.audit(c, "master", ident, "saved", dict({"kind": kind, "name": name, "active": active}, **profile))
        return ident

    @staticmethod
    def _technician_login(c, user_id, master_id):
        """Validate the login account a directory technician is being linked to."""
        if not user_id:
            return None
        row = c.execute("SELECT id FROM users WHERE id=? AND active=1 AND role='technician'", (user_id,)).fetchone()
        if not row:
            raise RuleError("Link this technician to an active technician login account.")
        clash = c.execute("""SELECT name FROM masters WHERE kind='technician' AND user_id=?
            AND id IS NOT ?""", (user_id, master_id)).fetchone()
        if clash:
            raise RuleError("That login is already linked to the technician " + clash[0] + ".")
        return user_id

    def save_customer(self, name=None, phone_number=None, email=None, address=None, whatsapp_consent=None, email_consent=None, alternate=None, ident=None, complete=True, **address_fields):
        """Create or correct a customer record.

        Every rule the registration screen shows is enforced here as well, so a customer
        created from anywhere else in the application is just as complete. `complete=False`
        is the deliberate quick counter registration, which records a name and a contact
        number now and the postal address later; it has to be asked for rather than being
        what omitting arguments silently gives you.

        An omitted argument on an update means "leave this as it is": only what is passed
        changes, so correcting a name can never blank a phone number or a postal address.
        """
        self.require_permission('customer_records')
        from . import addresses
        if not set(address_fields) <= set(addresses.FIELDS):
            raise RuleError("Unknown customer address field.")
        with self.db.transaction() as c:
            before = None
            if ident:
                row = c.execute("SELECT * FROM customers WHERE id=?", (ident,)).fetchone()
                if not row:
                    raise RuleError("Customer not found.")
                before = dict(row)
            supplied = dict(name=name, phone=phone_number, email=email, alternate=alternate,
                            whatsapp_consent=whatsapp_consent, email_consent=email_consent)
            merged = {k: (before or {}).get(k, '') if v is None else v for k, v in supplied.items()}
            structured = {k: address_fields[k] if address_fields.get(k) is not None
                          else (before or {}).get(k, '') for k in addresses.FIELDS}
            if not str(merged['name'] or '').strip():
                raise RuleError("Enter the customer's full name.")
            if merged['email'] and ("@" not in merged['email'] or "\n" in merged['email'] or "\r" in merged['email']):
                raise RuleError("Enter a valid email address or leave it blank.")
            contact = phone(merged['phone'])
            if not contact:
                raise RuleError("Enter the customer's phone / WhatsApp number.")
            # A record that already exists without a postal address stays readable and can
            # still be corrected; a complete address is required as soon as one is being
            # written, and always for a new customer.
            require_address = (complete and before is None) \
                or any(str((before or {}).get(k) or '').strip() for k in addresses.FIELDS) \
                or any(str(v or '').strip() for v in address_fields.values())
            structured = addresses.clean(structured, required=require_address)
            composed = addresses.readable(structured) if any(structured.values()) \
                else (address if address is not None else (before or {}).get('address', ''))
            values = dict(name=str(merged['name']).strip(), phone=contact,
                          email=str(merged['email'] or '').strip().lower(), address=composed,
                          whatsapp_consent=int(bool(merged['whatsapp_consent'])),
                          email_consent=int(bool(merged['email_consent'])),
                          alternate=str(merged['alternate'] or ''), **structured)
            if ident:
                c.execute("UPDATE customers SET " + ",".join(k+"=?" for k in values) + " WHERE id=?", (*values.values(), ident))
            else:
                ident = insert(c, "customers", **values, created=now())
            customer_folder(c, ident)
            self.audit(c, "customer", ident, "saved", {"before": before, "after": values})
        return ident

    def save_sale(self, customer_id, device, **fields):
        self.require_permission('customer_records')
        if not device.strip():
            raise RuleError("Device description is required.")
        allowed = {"category_id", "serial", "invoice_ref", "invoice_date", "sale_date", "amount", "cost", "provider", "warranty_start", "warranty_end", "warranty_terms"}
        if not set(fields) <= allowed:
            raise RuleError("Unknown product fields.")
        for k in ("invoice_date", "sale_date", "warranty_start", "warranty_end"):
            if k in fields:
                fields[k] = day(fields[k])
        with self.db.transaction() as c:
            device_id = device_record(c, customer_id, device, fields.get("category_id"), fields.get("serial", ""))
            ident = insert(c, "sales", customer_id=customer_id, device=device, device_id=device_id, **fields)
            self.audit(c, "sale", ident, "registered", fields)
        return ident

    def collect_sale(self, ident, collector, acknowledgment):
        self.require_permission('customer_delivery')
        if not collector.strip() or not acknowledgment.strip():
            raise RuleError("Record collector and acknowledgment.")
        with self.db.transaction() as c:
            if c.execute("UPDATE sales SET collected=1,collector=?,acknowledgment=? WHERE id=? AND collected=0", (collector, acknowledgment, ident)).rowcount != 1:
                raise RuleError("Product has already been collected.")
            self.audit(c, "sale", ident, "collected", {"collector": collector, "acknowledgment": acknowledgment})

    def notify(self, c, job_id, event, message, quote_id=None, event_key=None):
        j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        key = event_key or uuid.uuid4().hex
        settings = {r[0]: json.loads(r[1]) for r in c.execute("SELECT key,value FROM settings")}
        variables = {'shop_name':settings.get('shop_name','RepairShop Manager'),'job_number':j['number'],'device':j['device'],'message':message,'event':event.replace('_',' '),'shop_address':settings.get('address',''),'shop_hours':settings.get('hours','')}
        payload = {"subject": settings.get('email_subject','{job_number} · {event}').format(**variables), "body": settings.get('message_template','{shop_name}\n{job_number} · {device}\n{message}').format(**variables), "template": settings.get("templates", {}).get(event, {}), "job_version": j["version"]}
        for contact_id in set(filter(None, (j["customer_id"], j["update_contact_id"]))):
            contact = c.execute("SELECT * FROM customers WHERE id=?", (contact_id,)).fetchone()
            for channel, destination, consent in (("whatsapp", contact["phone"], contact["whatsapp_consent"]), ("email", contact["email"], contact["email_consent"])):
                if destination:
                    c.execute("INSERT OR IGNORE INTO outbox(event_key,job_id,quote_id,contact_id,channel,destination,event,payload,state,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (key, job_id, quote_id, contact_id, channel, destination, event, json.dumps(payload), "pending" if consent else "blocked_consent", now(), now()))
        # Notify owners and the assigned technician. A staff recipient is always a login
        # account, so a technician assigned through the directory is resolved to the
        # account linked to that directory record instead of being looked up by an id that
        # belongs to a different table.
        internal = c.execute("""SELECT r.* FROM recipients r JOIN users u ON u.id=r.entity_id
            WHERE r.kind='staff' AND r.active=1 AND u.active=1 AND u.role='owner'
            UNION ALL
            SELECT r.* FROM recipients r JOIN users u ON u.id=r.entity_id
            WHERE r.kind='staff' AND r.active=1 AND u.active=1 AND u.id=(
                SELECT COALESCE(a.technician_id,
                                (SELECT m.user_id FROM masters m
                                 WHERE m.id=a.technician_master_id AND m.kind='technician' AND m.active=1))
                FROM assignments a WHERE a.id=?)""",
            (j['assignment_id'],)).fetchall()
        for recipient in internal:
            c.execute('INSERT OR IGNORE INTO outbox(event_key,job_id,quote_id,recipient_id,channel,destination,event,payload,state,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(key,job_id,quote_id,recipient['id'],recipient['channel'],recipient['destination'],event,json.dumps(payload),'pending' if recipient['consent'] else 'blocked_consent',now(),now()))

    def save_recipient(self, kind, entity_id, channel, destination, consent=False, active=True):
        self.require('owner')
        if kind not in ('staff','vendor') or channel not in ('email','whatsapp'):
            raise RuleError('Choose a staff/vendor recipient and channel.')
        destination = phone(destination) if channel == 'whatsapp' else destination.strip().lower()
        if not destination or (channel=='email' and ('@' not in destination or '\n' in destination or '\r' in destination)):
            raise RuleError('Enter a valid destination.')
        with self.db.transaction() as c:
            if kind == 'staff':
                exists = c.execute('SELECT id FROM users WHERE id=?', (entity_id,)).fetchone()
            else:
                exists = c.execute('SELECT id FROM masters WHERE id=?', (entity_id,)).fetchone()
            if not exists:
                raise RuleError('Recipient account does not exist.')
            c.execute('INSERT INTO recipients(kind,entity_id,channel,destination,consent,active) VALUES (?,?,?,?,?,?) ON CONFLICT(kind,entity_id,channel) DO UPDATE SET destination=excluded.destination,consent=excluded.consent,active=excluded.active',(kind,entity_id,channel,destination,int(consent),int(active)))
            self.audit(c,'recipient',entity_id,'configured',{'kind':kind,'channel':channel,'destination':destination,'consent':consent,'active':active})

    def queue_document(self, attachment_id, recipient_id, subject, body, operation_id):
        self.require('owner')
        with self.db.transaction() as c:
            r=c.execute('SELECT * FROM recipients WHERE id=? AND active=1',(recipient_id,)).fetchone()
            a=c.execute("SELECT * FROM attachments WHERE id=? AND kind='issued_document'",(attachment_id,)).fetchone()
            if not r or not a:
                raise RuleError('Choose a configured recipient and saved issued document.')
            if r['channel']!='email':
                raise RuleError('Choose an email recipient for direct PDF statement attachment.')
            payload={'subject':subject,'body':body}
            c.execute('INSERT OR IGNORE INTO outbox(event_key,recipient_id,attachment_id,channel,destination,event,payload,state,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?)',(operation_id,recipient_id,attachment_id,r['channel'],r['destination'],'statement',json.dumps(payload),'pending' if r['consent'] else 'blocked_consent',now(),now()))
            self.audit(c,'document',attachment_id,'queued_for_recipient',{'recipient_id':recipient_id,'subject':subject})

    def queue_customer_document(self, attachment_id, customer_id, channels, event, message, operation_id, job_id=None):
        """Optional customer copy of an issued document. Never part of an intake transaction."""
        self.require_permission('messaging')
        if not set(channels) <= {'whatsapp', 'email'}:
            raise RuleError('Choose WhatsApp and/or email.')
        with self.db.transaction() as c:
            contact = c.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
            attachment = c.execute("SELECT * FROM attachments WHERE id=? AND kind='issued_document'", (attachment_id,)).fetchone()
            if not contact or not attachment:
                raise RuleError('Choose a customer and a saved issued document.')
            settings = self.db.setting('templates', {})
            results = []
            for channel in channels:
                destination, consent = (contact['phone'], contact['whatsapp_consent']) if channel == 'whatsapp' else (contact['email'], contact['email_consent'])
                if not destination:
                    # Nothing was queued: say so rather than reporting a send that cannot happen.
                    results.append(dict(channel=channel, state='no_contact'))
                    continue
                payload = {'subject': event.replace('_', ' ').title(), 'body': message,
                           'template': settings.get(event, {})}
                if self.db.setting('include_photos', False) and channel == 'email':
                    payload['include_photos'] = True
                state = 'pending' if consent else 'blocked_consent'
                c.execute('''INSERT OR IGNORE INTO outbox(event_key,job_id,contact_id,attachment_id,channel,destination,
                    event,payload,state,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (f'{operation_id}:{channel}', job_id, customer_id, attachment_id, channel, destination,
                     event, json.dumps(payload), state, now(), now()))
                results.append(dict(channel=channel, state=state))
            self.audit(c, 'document', attachment_id, 'queued_for_customer',
                       {'customer_id': customer_id, 'event': event,
                        'outcomes': {r['channel']: r['state'] for r in results}})
            return results

    def intake(self, customer_id, device, complaint, accessories=(), storage=None, advance=0, operation_id=None, photo_id=None, device_id=None, draft_id=None, guided=False, brand=None, model=None, intake_warranty=None, visit_id=None, **fields):
        self.require_permission('intake')
        # Whoever is signed in is the person the customer handed the product to, so they
        # become the receiver and the first custodian without being asked to say so.
        storage = self.receiving_custody(storage)
        if not device.strip() or not complaint.strip():
            raise RuleError("Device and complaint are required.")
        allowed = {"submitter", "relationship", "update_contact_id", "sale_id", "parent_id", "category_id", "service_id", "serial", "origin", "damage", "route", "repair_due", "collection_due", "return_due", "policy", "transport_agreed", "assessment_agreed", "assessment_consent", "deposit", "intake_ref", "initial_estimate", "customer_requirement"}
        if not set(fields) <= allowed:
            raise RuleError("Unknown intake field.")
        fields.setdefault("policy", self.db.setting("decline_policy", "NO_CUSTOMER_CHARGE"))
        if not isinstance(fields.get("initial_estimate", 0), int) or fields.get("initial_estimate", 0) < 0:
            raise RuleError("Enter the initial estimate as a nonnegative whole-paise amount.")
        fields.setdefault("intake_ref", "REF-" + uuid.uuid4().hex[:10].upper())
        if fields.get("route", "in_house") not in ROUTES:
            raise RuleError("Invalid repair route.")
        for k in ("repair_due", "collection_due", "return_due"):
            if k in fields:
                fields[k] = day(fields[k])
        with self.db.transaction() as c:
            if operation_id:
                duplicate = c.execute("SELECT result_id FROM commands WHERE operation_id=? AND kind='intake'", (operation_id,)).fetchone()
                if duplicate:
                    return duplicate[0]
            self.validate_intake_service(fields.get('category_id'),fields.get('service_id'))
            owner = c.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
            if not owner:
                raise RuleError('Select an existing customer.')
            photo_id = photo_id or owner['current_photo_id']
            photo = c.execute("SELECT * FROM attachments WHERE id=? AND customer_id=? AND kind='customer_photo'", (photo_id, customer_id)).fetchone()
            if not photo:
                raise RuleError('Save the required customer photo before finalizing intake. You can keep this intake as a draft.')
            if photo['person_role'] == 'submitter' and norm(photo['person_name']) != norm(fields.get('submitter', '')):
                raise RuleError('The captured submitter does not match Submitted by. Correct the name or capture the right person.')
            photo_path = managed_path(self.db.root, photo['path'])
            if not photo_path.is_file() or digest(photo_path.read_bytes()) != photo['sha256']:
                raise RuleError('The saved customer photo is missing or damaged. Recover the original from backup or capture a new photo.')
            for key, table in (('parent_id', 'jobs'), ('sale_id', 'sales')):
                if fields.get(key):
                    linked = c.execute(f'SELECT customer_id,device_id FROM {table} WHERE id=?', (fields[key],)).fetchone()
                    if not linked or linked['customer_id'] != customer_id or (device_id and device_id != linked['device_id']):
                        raise RuleError('The linked repair/product must belong to this customer and device.')
                    device_id = linked['device_id']
            warranty_snapshot = None
            if fields.get('sale_id'):
                from .warranties import sale_warranty
                sale = c.execute('SELECT * FROM sales WHERE id=?', (fields['sale_id'],)).fetchone()
                warranty_snapshot = sale_warranty(sale)
            elif intake_warranty is not None:
                from .warranties import reported_intake_warranty
                warranty_snapshot = reported_intake_warranty(intake_warranty)
            device_id = device_record(c, customer_id, device, fields.get('category_id'), fields.get('serial', ''), device_id)
            for key,value in (('brand',brand),('model',model)):
                if value is not None:
                    c.execute('UPDATE devices SET '+key+'=? WHERE id=?',(value.strip(),device_id))
            active = c.execute("SELECT j.number FROM jobs j WHERE j.device_id=? AND EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND h.quantity>0 AND h.location!='customer' AND h.location NOT LIKE 'exception:%')", (device_id,)).fetchone()
            if active:
                raise RuleError('This physical device still has outstanding items on ' + active[0] + '. Complete that handover first, or select New physical device.')
            from .visits import Visits
            visits = Visits(self)
            if visit_id:
                owning = c.execute('SELECT customer_id FROM visits WHERE id=?', (visit_id,)).fetchone()
                if not owning or owning[0] != customer_id:
                    raise RuleError('This visit belongs to a different customer.')
            else:
                # A single product still becomes one visit with one job, so every job
                # is reachable through the same customer -> visit -> jobs relationship.
                visit_id = visits.create(c, customer_id, intake_ref=fields["intake_ref"],
                                         estimated_total=fields.get("initial_estimate", 0), advance_total=advance)['id']
            ident = insert(c, "jobs", customer_id=customer_id, device=device, device_id=device_id, photo_id=photo_id, complaint=complaint, received=now(), actor=self.user["id"], lifecycle_version=int(guided), visit_id=visit_id, **fields)
            visits.attach(c, visit_id, ident)
            if warranty_snapshot is not None:
                data = json.loads(c.execute('SELECT lifecycle_data FROM jobs WHERE id=?', (ident,)).fetchone()[0])
                data['intake_warranty'] = warranty_snapshot
                c.execute('UPDATE jobs SET lifecycle_data=? WHERE id=?', (json.dumps(data), ident))
                self.audit(c, 'job', ident, 'intake_warranty_recorded', warranty_snapshot)
            if draft_id:
                c.execute('DELETE FROM intake_drafts WHERE id=? AND actor=?', (draft_id, self.user['id']))
            number = f"REP-{date.today().year}-{ident:06d}"
            c.execute("UPDATE jobs SET number=? WHERE id=?", (number, ident))
            received = [{"type": "device", "description": device, "quantity": 1, "serial": fields.get("serial", ""), "condition": fields.get("damage", "")}, *accessories]
            for item in received:
                if not isinstance(item.get("quantity", 1), int) or item.get("quantity", 1) < 1:
                    raise RuleError("Received quantities must be positive whole numbers.")
                if item.get("serial") and item.get("quantity", 1) != 1:
                    raise RuleError("Record each serialized unit separately.")
                if item.get("type", "accessory") == "accessory" and item.get("condition") and item["condition"] not in ITEM_CONDITIONS:
                    raise RuleError("Record each accessory as Working, Not Working, Not Tested or Damaged.")
                if item.get("photo_id"):
                    self._bind_evidence(c, item["photo_id"], customer_id, ident, ('accessory_photo', 'product_photo'),
                                        'An accessory photo must be a photo captured for this customer at this intake.')
                item_id = insert(c, "items", job_id=ident, type=item.get("type", "accessory"), description=item["description"], quantity=item.get("quantity", 1), serial=item.get("serial", ""), condition=item.get("condition", ""), notes=item.get("notes", ""), photo_id=item.get("photo_id"))
                insert(c, "holdings", item_id=item_id, location=storage, quantity=item.get("quantity", 1))
                insert(c, "movements", operation_id=uuid.uuid4().hex, item_id=item_id, quantity=item.get("quantity", 1), from_location="customer", to_location=storage, happened=now(), recorded=now(), actor=self.user["id"], counterparty=fields.get("submitter", "") or "Device owner", notes="Initial receipt")
            if advance:
                self._post(c, "customer", customer_id, "receipt", advance, operation_id or uuid.uuid4().hex, job_id=ident, notes="Intake advance")
            self.audit(c, "job", ident, "received", {"number": number, "fields": fields, "items": received})
            from .job_cards import JobCards
            JobCards(self).issue(ident, 'customer_receiving', f'intake:{ident}')
            self.notify(c, ident, "received", "Your device has been received for assessment. We will record your approval before starting quoted paid repair.")
            if operation_id:
                insert(c, 'commands', operation_id=operation_id, kind='intake', result_id=ident)
        return ident

    @staticmethod
    def _bind_evidence(c, attachment_id, customer_id, job_id, kinds, message):
        """Tie one photo to the record it is evidence for, and to nothing else.

        Belonging to the same customer is not enough: a customer accumulates photos across
        every visit, so an unrelated historical picture must not be usable as evidence for
        this job. The attachment is claimed by this job the first time it is used, which
        both proves the link afterwards and stops the same photo being reused elsewhere.
        """
        row = c.execute('SELECT id,kind,customer_id,job_id FROM attachments WHERE id=?', (attachment_id,)).fetchone()
        if not row or row['customer_id'] != customer_id or row['kind'] not in kinds:
            raise RuleError(message)
        if row['job_id'] is not None and row['job_id'] != job_id:
            raise RuleError(message + ' This photo already belongs to another repair.')
        if c.execute('SELECT 1 FROM items WHERE photo_id=? AND job_id IS NOT ?', (attachment_id, job_id)).fetchone():
            raise RuleError(message + ' This photo is already recorded against another item.')
        if row['job_id'] is None:
            c.execute('UPDATE attachments SET job_id=? WHERE id=?', (job_id, attachment_id))
        return attachment_id

    def job(self, ident):
        self.require()
        row = self.db.one("SELECT j.*,c.name AS customer,c.phone,c.email FROM jobs j JOIN customers c ON c.id=j.customer_id WHERE j.id=?", (ident,))
        if not row:
            raise RuleError("Job not found.")
        return self.guard_job_access(row)

    def intake_visit(self,products,operation_id,draft_id=None,notes=''):
        """Receive one visit atomically; each physical device keeps its own job."""
        self.require_permission('intake')
        if not operation_id or not products or len(products)>50:
            raise RuleError('A visit needs between 1 and 50 products and an operation reference.')
        with self.db.transaction() as c:
            previous=c.execute("SELECT result_id FROM commands WHERE operation_id=? AND kind='intake_visit'",(operation_id,)).fetchone()
            if previous:
                event=c.execute("SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='visit_received' ORDER BY id DESC LIMIT 1",(previous[0],)).fetchone()
                return json.loads(event[0])['jobs']
            customer=products[0].get('customer_id')
            if not customer or any(p.get('customer_id')!=customer for p in products):
                raise RuleError('All products in one visit must belong to the same customer.')
            reference=products[0].get('intake_ref') or 'REF-'+uuid.uuid4().hex[:10].upper()
            if any(p.get('intake_ref') and p['intake_ref']!=reference for p in products):
                raise RuleError('Use one visit reference for these products.')
            from .visits import Visits
            visit=Visits(self).create(c,customer,intake_ref=reference,notes=notes,
                estimated_total=sum(int(p.get('initial_estimate') or 0) for p in products),
                advance_total=sum(int(p.get('advance') or 0) for p in products))
            jobs=[]
            for index,product in enumerate(products):
                if set(product)&{'operation_id','draft_id','visit_id'}:
                    raise RuleError('Product operation references are managed by the visit.')
                fields=dict(product,intake_ref=reference)
                jobs.append(self.intake(**fields,visit_id=visit['id'],operation_id=f'{operation_id}:product:{index}'))
            self.audit(c,'job',jobs[0],'visit_received',{'visit':reference,'visit_id':visit['id'],'visit_number':visit['number'],'jobs':jobs,'products':len(jobs)})
            insert(c,'commands',operation_id=operation_id,kind='intake_visit',result_id=jobs[0])
            if draft_id:c.execute('DELETE FROM intake_drafts WHERE id=? AND actor=?',(draft_id,self.user['id']))
            return jobs

    def _job(self, c, ident, version=None):
        j = c.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
        if not j:
            raise RuleError("Job not found.")
        if version is not None and j["version"] != version:
            raise RuleError("This job changed. Refresh and review before saving.")
        self.require_job_access(ident, c)
        return j

    def _touch(self, c, job_id):
        c.execute("UPDATE jobs SET version=version+1 WHERE id=?", (job_id,))

    def move(self, item_id, quantity, source, destination, counterparty, operation_id, reference="", condition="", notes="", acknowledgment="", happened=None, reverses_id=None):
        self.require_permission('handover')
        if not isinstance(quantity, int) or quantity <= 0 or source == destination or not counterparty.strip():
            raise RuleError("Choose a positive quantity, different destination, and counterparty.")
        if destination.split(":")[0] not in ("shop", "staff", "technician", "vendor", "centre", "transit", "customer", "exception"):
            raise RuleError("Invalid custody destination.")
        if destination.startswith("exception"):
            self.require("owner")
            if not notes.strip():
                raise RuleError("Owner resolution requires a reason.")
        if destination == "customer" and not acknowledgment.strip():
            raise RuleError("Customer collection requires an acknowledgment.")
        if reverses_id:
            self.require("owner")
            if not notes.strip():
                raise RuleError("Movement correction requires a reason.")
        with self.db.transaction() as c:
            duplicate = c.execute("SELECT * FROM movements WHERE operation_id=?", (operation_id,)).fetchone()
            if duplicate:
                if (duplicate['item_id'], duplicate['quantity'], duplicate['from_location'], duplicate['to_location']) != (item_id, quantity, source, destination):
                    raise RuleError('This operation ID belongs to a different handover.')
                return duplicate['id']
            item = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            j = self._job(c, item["job_id"])
            from .lifecycle import guard
            guard(j, 'move or collect items')
            if j["stage"] in ("closed", "collected"):
                raise RuleError("Open a linked follow-up job for work after collection.")
            if destination == "customer" and j["stage"] not in ("ready_repaired", "ready_unrepaired"):
                raise RuleError("Check the returned device and mark it ready before collection.")
            if not in_shop(source) and destination == "customer":
                raise RuleError("Receive the item at the shop before customer collection.")
            if destination.startswith(("vendor:", "centre:", "transit:")) and not j["assessment_consent"]:
                raise RuleError("Record customer assessment/transport consent before external dispatch.")
            if c.execute("UPDATE holdings SET quantity=quantity-? WHERE item_id=? AND location=? AND quantity>=?", (quantity, item_id, source, quantity)).rowcount != 1:
                raise RuleError("That quantity is unavailable at the selected location.")
            c.execute("INSERT INTO holdings VALUES (?,?,?) ON CONFLICT(item_id,location) DO UPDATE SET quantity=quantity+excluded.quantity", (item_id, destination, quantity))
            ident = insert(c, "movements", operation_id=operation_id, item_id=item_id, quantity=quantity, from_location=source, to_location=destination, happened=happened or now(), recorded=now(), actor=self.user["id"], counterparty=counterparty, reference=reference, condition=condition, notes=notes, acknowledgment=acknowledgment, reverses_id=reverses_id)
            self._touch(c, item["job_id"])
            self.audit(c, "job", item["job_id"], "custody_moved", {"movement": ident, "from": source, "to": destination, "quantity": quantity})
            event = "collected" if destination == "customer" else "return_arrival" if in_shop(destination) else "dispatch"
            self.notify(c, item["job_id"], event, f"{item['description']}: {quantity} unit(s) handed to {counterparty}. Reference: {reference}.")
        return ident

    def assign(self, job_id, route, contact_id=None, technician_id=None, technician_master_id=None, reference="", estimate=0):
        self.require_permission('assign_job')
        if route not in ROUTES or (route != "in_house" and not contact_id):
            raise RuleError("Choose a route and its responsible repairer.")
        with self.db.transaction() as c:
            j = self._job(c, job_id)
            from .lifecycle import guard
            guard(j, 'change the repair route')
            if j['stage'] in ('closed', 'collected'):
                raise RuleError('Use a linked follow-up job after collection.')
            if route == 'in_house':
                if technician_master_id:
                    technician = c.execute("SELECT id FROM masters WHERE id=? AND kind='technician' AND active=1", (technician_master_id,)).fetchone()
                    if not technician:
                        raise RuleError('Assign an active technician from the Technician directory.')
                    technician_id = None
                elif technician_id:
                    # Backward compatibility for existing databases/assignments that used a login user as technician.
                    if not c.execute("SELECT id FROM users WHERE id=? AND active=1", (technician_id,)).fetchone():
                        raise RuleError('Assign an active technician.')
                else:
                    raise RuleError('Assign an active shop technician.')
            else:
                technician_id = technician_master_id = None
            ident = insert(c, "assignments", job_id=job_id, route=route, contact_id=contact_id, technician_id=technician_id,
                           technician_master_id=technician_master_id, reference=reference, estimate=estimate, created=now(), actor=self.user["id"])
            c.execute("UPDATE jobs SET assignment_id=?,route=?,version=version+1 WHERE id=?", (ident, route, job_id))
            self.audit(c, "job", job_id, "assigned", {"assignment": ident, "route": route, "contact_id": contact_id,
                "technician_id": technician_id, "technician_master_id": technician_master_id})
            if route == 'in_house' and (technician_id or technician_master_id):
                from .job_cards import JobCards
                JobCards(self).issue(job_id, 'in_house_assignment', f'assignment:{ident}')
        return ident

    def record_work(self, job_id, kind, payload):
        self.require()
        with self.db.transaction() as c:
            j = self._job(c, job_id)
            if j["stage"] in ("closed", "collected"):
                raise RuleError("Use a follow-up job for rework.")
            if kind in ('repair', 'installed_part'):
                self._authorize_repair(c, j)
            if kind == 'assessment' and not j['assessment_consent']:
                raise RuleError('Record assessment consent before assessment work.')
            ident = insert(c, "work", job_id=job_id, assignment_id=j["assignment_id"], kind=kind, payload=json.dumps(payload), created=now(), actor=self.user["id"])
            self._touch(c, job_id)
            self.audit(c, "job", job_id, "work_recorded", {"kind": kind, "details": payload})
        return ident

    def _authorize_repair(self, c, j):
        from .parts import Parts
        Parts(self).validate_approval(c,j)
        if j['hold_reason']:
            raise RuleError('Release the job hold before starting repair.')
        q = c.execute('SELECT * FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1', (j['id'],)).fetchone()
        warranty = c.execute('SELECT * FROM warranty WHERE job_id=? ORDER BY id DESC LIMIT 1', (j['id'],)).fetchone()
        if not q and not (warranty and warranty['decision'] == 'accepted'):
            raise RuleError('Paid repair needs an approved current quotation.')
        if q and (q['state'] != 'approved' or (q['valid_until'] and q['valid_until'] < date.today().isoformat())):
            raise RuleError('Approval must apply to the current unexpired quotation.')
        retained = -c.execute("SELECT COALESCE(sum(CASE WHEN e.kind IN ('receipt','refund') OR (e.kind='reversal' AND original.kind IN ('receipt','refund')) THEN e.amount ELSE 0 END),0) FROM entries e LEFT JOIN entries original ON original.id=e.reverses_id WHERE e.account_type='customer' AND e.job_id=?", (j['id'],)).fetchone()[0]
        if retained < j['deposit']:
            raise RuleError('The required deposit has not been received.')

    def dates(self, job_id, repair_due, collection_due, return_due, reason, version=None, duration_days=None, reference_date=None):
        self.require_permission('assign_job')
        if not reason.strip():
            raise RuleError("Record the reason for these estimated dates.")
        with self.db.transaction() as c:
            j = self._job(c, job_id, version)
            if duration_days is not None:
                from datetime import timedelta
                if not isinstance(duration_days,int) or duration_days<0 or not reference_date:
                    raise RuleError('Duration needs nonnegative calendar days and a reference date.')
                repair_due = (date.fromisoformat(reference_date) + timedelta(days=duration_days)).isoformat()
            values = [day(v) for v in (repair_due, collection_due, return_due)]
            c.execute("UPDATE jobs SET repair_due=?,collection_due=?,return_due=?,version=version+1 WHERE id=?", (*values, job_id))
            self.audit(c, "job", job_id, "dates_revised", {"before": [j[k] for k in ("repair_due", "collection_due", "return_due")], "after": values, "reason": reason, "basis": "calendar days", 'duration_days': duration_days, 'reference_date': reference_date})
            self.notify(c, job_id, "dates_revised", f"Estimated collection: {collection_due or 'to be confirmed'}. {reason}")

    def stage(self, job_id, stage, reason="", test_result="", version=None):
        self.require()
        if stage not in STAGES:
            raise RuleError("Choose a valid stage.")
        with self.db.transaction() as c:
            j = self._job(c, job_id, version)
            from .lifecycle import guard
            guard(j, 'change repair progress')
            if j["stage"] in ("closed", "collected") and stage != "closed":
                raise RuleError("Create a linked follow-up job after collection.")
            if self.user["role"] == "technician" and stage not in ("diagnosis", "under_repair", "waiting_parts", "testing", "awaiting_return"):
                raise RuleError("Counter staff handles approval and customer handover stages.")
            if stage == "under_repair":
                self._authorize_repair(c, j)
            if stage in ("ready_repaired", "ready_unrepaired"):
                away = c.execute("SELECT sum(h.quantity) FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND i.type='device' AND NOT ((h.location LIKE 'shop:%' OR h.location LIKE 'staff:%' OR h.location LIKE 'technician:%') OR h.location LIKE 'staff:%' OR h.location LIKE 'technician:%') AND h.location NOT LIKE 'exception:%'", (job_id,)).fetchone()[0] or 0
                at_shop = c.execute("SELECT sum(h.quantity) FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND i.type='device' AND (h.location LIKE 'shop:%' OR h.location LIKE 'staff:%' OR h.location LIKE 'technician:%')", (job_id,)).fetchone()[0] or 0
                if away or not at_shop:
                    raise RuleError("The device must be physically received at the shop.")
                if stage == "ready_repaired" and (test_result or j["test_result"]) != "passed":
                    raise RuleError("Record a passed shop test before repaired collection.")
                if stage == "ready_unrepaired" and not reason.strip():
                    raise RuleError("Record the unrepaired outcome and return check.")
            if stage in ("collected", "closed"):
                outstanding = c.execute("SELECT sum(h.quantity) FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND h.location!='customer' AND h.location NOT LIKE 'exception:%'", (job_id,)).fetchone()[0] or 0
                if outstanding:
                    raise RuleError("Return or explicitly resolve every device/accessory before closure.")
            c.execute("UPDATE jobs SET stage=?,test_result=CASE WHEN ?!='' THEN ? ELSE test_result END,outcome=CASE WHEN ?!='' THEN ? ELSE outcome END,actual_completion=CASE WHEN ?='ready_repaired' THEN ? ELSE actual_completion END,actual_collection=CASE WHEN ?='collected' THEN ? ELSE actual_collection END,version=version+1 WHERE id=?", (stage, test_result, test_result, reason, reason, stage, now(), stage, now(), job_id))
            self.audit(c, "job", job_id, "stage_changed", {"before": j["stage"], "after": stage, "reason": reason, "test_result": test_result})
            messages = {"awaiting_return": "External repair is reported complete. The device is awaiting return to our shop; please wait for a collection confirmation.", "ready_repaired": "Your repaired device has passed testing at our shop and is ready for collection.", "ready_unrepaired": "Your device is ready for collection without repair. " + reason, "collected": "Collection has been recorded. Thank you."}
            if stage in messages:
                self.notify(c, job_id, stage, messages[stage])

    def hold(self, job_id, reason):
        self.require_permission('assign_job')
        with self.db.transaction() as c:
            self._job(c, job_id)
            c.execute("UPDATE jobs SET hold_reason=?,version=version+1 WHERE id=?", (reason, job_id))
            self.audit(c, "job", job_id, "hold_changed", {"reason": reason})

    def record_warranty(self, job_id, decision, rma="", findings="", covered="", excluded="", terms=""):
        self.require_permission('manage_warranty')
        if decision not in ("pending", "accepted", "rejected", "partial") or (decision in ("rejected", "partial") and not findings.strip()):
            raise RuleError("Record the centre decision and rejection/partial-coverage reason.")
        with self.db.transaction() as c:
            j = self._job(c, job_id)
            from .lifecycle import guard
            guard(j, 'record a warranty decision')
            sale = c.execute("SELECT * FROM sales WHERE id=?", (j["sale_id"],)).fetchone()
            eligibility = "unknown"
            if sale and sale["warranty_end"]:
                eligibility = "in_date" if (not sale["warranty_start"] or sale["warranty_start"] <= j["received"][:10]) and sale["warranty_end"] >= j["received"][:10] else "out_of_date"
            ident = insert(c, "warranty", job_id=job_id, eligibility=eligibility, decision=decision, rma=rma, findings=findings, covered=covered, excluded=excluded, terms=terms, created=now(), actor=self.user["id"])
            self._touch(c, job_id)
            self.audit(c, "job", job_id, "warranty_decision", {"decision": decision, "findings": findings})
            self.notify(c, job_id, "warranty_" + decision, f"Warranty decision: {decision}. {findings}. Any paid work requires your separate approval.")
        return ident

    def replacement(self, item_id, description, serial, location, terms, evidence):
        self.require_permission('handover')
        if not serial.strip() or not evidence.strip() or not terms.strip():
            raise RuleError("Record replacement serial, supplied warranty terms, and evidence.")
        with self.db.transaction() as c:
            old = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            j = self._job(c, old["job_id"])
            from .lifecycle import guard
            guard(j, 'record replacement custody')
            if c.execute("SELECT 1 FROM items WHERE replaces_id=?", (item_id,)).fetchone():
                raise RuleError("A replacement is already linked to this item.")
            ident = insert(c, "items", job_id=old["job_id"], type=old["type"], description=description, quantity=1, serial=serial, provenance=evidence, replaces_id=item_id)
            insert(c, "holdings", item_id=ident, location=location, quantity=1)
            insert(c, "movements", operation_id=uuid.uuid4().hex, item_id=ident, quantity=1, from_location="replacement_supplier", to_location=location, happened=now(), recorded=now(), actor=self.user["id"], counterparty=location, notes=evidence)
            self.audit(c, "job", old["job_id"], "replacement_received", {"original": item_id, "replacement": ident, "warranty_terms": terms, "evidence": evidence})
        return ident

    def issue_quote(self, job_id, scope, lines, terms="", valid_until=None):
        self.require_permission('create_quote')
        valid_until = day(valid_until)
        if valid_until and valid_until < date.today().isoformat():
            raise RuleError('Quotation expiry cannot be in the past. Choose today or a future date, or leave expiry off.')
        if not scope.strip() or not lines or any(not line.get("description", "").strip() or not isinstance(line.get("amount"), int) for line in lines):
            raise RuleError("Quotation needs scope and itemized amounts in paise.")
        total = sum(line["amount"] for line in lines)
        if total < 0:
            raise RuleError("Quotation total cannot be negative.")
        with self.db.transaction() as c:
            current = self._job(c, job_id)
            from .lifecycle import quote_guard
            quote_guard(c, current)
            from .parts import Parts
            if any('part_id' in line for line in lines):
                raise RuleError('Structured part lines are added automatically from the Parts tab.')
            lines = list(lines) + Parts(self).quote_lines(job_id)
            total = sum(line['amount'] for line in lines)
            if current['stage'] in ('closed', 'collected'):
                raise RuleError('Create a follow-up job for new work after collection.')
            v = c.execute("SELECT COALESCE(max(version),0)+1 FROM quotes WHERE job_id=?", (job_id,)).fetchone()[0]
            c.execute("UPDATE quotes SET state='superseded' WHERE job_id=? AND state IN ('issued','approved')", (job_id,))
            customer = dict(c.execute('SELECT * FROM customers WHERE id=?', (current['customer_id'],)).fetchone())
            branding = {r[0]: json.loads(r[1]) for r in c.execute("SELECT key,value FROM settings WHERE key IN ('shop_name','address','hours')")}
            snapshot = {'customer': customer, 'job': dict(current), 'shop': branding}
            ident = insert(c, "quotes", job_id=job_id, version=v, state="issued", scope=scope, lines=json.dumps(lines), total=total, terms=terms, valid_until=day(valid_until), created=now(), actor=self.user["id"], snapshot=json.dumps(snapshot))
            c.execute("UPDATE jobs SET stage='awaiting_approval',version=version+1 WHERE id=?", (job_id,))
            self.audit(c, "job", job_id, "quote_issued", {"quote_id": ident, "version": v, "scope": scope, "total": total})
            if current['lifecycle_version']:
                self.audit(c, 'job', job_id, 'lifecycle', {'action': 'quote', 'before': current['stage'], 'after': 'awaiting_approval', 'quote_id': ident})
            from .domain import rupees
            self.notify(c, job_id, "quote_issued", f"Quotation version {v}: {scope}. Total {rupees(total)}. Please contact the shop to approve or decline this specific quotation.", ident)
        return ident

    def _quote_for_decision(self, c, quote_id):
        q = c.execute('SELECT * FROM quotes WHERE id=?', (quote_id,)).fetchone()
        if not q:
            raise RuleError('Quotation not found. Refresh the quotation list.')
        latest = c.execute('SELECT id,version FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1', (q['job_id'],)).fetchone()
        if latest['id'] != q['id']:
            raise RuleError(f"Quotation version {q['version']} has been replaced. Open current version {latest['version']} (quotation #{latest['id']}) to record the decision.")
        if q['state'] != 'issued':
            raise RuleError(f"Quotation version {q['version']} is already {q['state']}. Its recorded decision cannot be overwritten. Review the repair workspace for the next action.")
        j = self._job(c, q['job_id'])
        if j['stage'] in ('closed','collected') or (j['lifecycle_version'] and j['stage'] != 'awaiting_approval'):
            raise RuleError('This job is no longer waiting for approval. Review its current lifecycle before recording a decision.')
        return q, j

    def quote_decision_details(self, quote_id):
        self.require_permission('create_quote')
        with self.db.read() as c:
            q, _ = self._quote_for_decision(c, quote_id)
            return dict(q, expired=bool(q['valid_until'] and q['valid_until'] < date.today().isoformat()))

    def decide_quote(self, quote_id, decision, person, channel, evidence=""):
        self.require_permission('approve_quote')
        if decision not in ("approved", "declined") or not person.strip() or channel not in ("call", "in_person", "whatsapp", "email"):
            raise RuleError("Record the decision, authorized person's name, and channel.")
        with self.db.transaction() as c:
            q, j = self._quote_for_decision(c, quote_id)
            if decision == 'approved' and q['valid_until'] and q['valid_until'] < date.today().isoformat():
                raise RuleError(f"This quotation expired on {q['valid_until']}. Issue a revised quotation before recording approval. A customer decline can still be recorded.")
            insert(c, "decisions", quote_id=quote_id, decision=decision, person=person, channel=channel, amount=q["total"], evidence=evidence, created=now(), actor=self.user["id"])
            c.execute("UPDATE quotes SET state=? WHERE id=?", (decision, quote_id))
            c.execute("UPDATE jobs SET stage=?,version=version+1 WHERE id=?", ("approved" if decision == "approved" else "return_unrepaired", q["job_id"]))
            if j['lifecycle_version']:
                data = json.loads(j['lifecycle_data'])
                if decision == 'declined':
                    data['unrepaired'] = 'Customer declined quotation: ' + (evidence or person)
                c.execute('UPDATE jobs SET lifecycle_data=? WHERE id=?', (json.dumps(data), j['id']))
                self.audit(c, 'job', j['id'], 'lifecycle', {'action':'decision', 'before':j['stage'], 'after':'approved' if decision=='approved' else 'return_unrepaired', 'decision':decision})
            self.audit(c, "job", q["job_id"], "quote_decision", {"quote_id": quote_id, "decision": decision, "person": person, "channel": channel, "evidence": evidence})
            self.notify(c, q["job_id"], "decision_recorded", f"Your decision on quotation version {q['version']} was recorded as {decision}.", quote_id)

    def _post(self, c, account_type, account_id, kind, amount, operation_id, job_id=None, quote_id=None, posted=None, method="", reference="", notes="", payload=None, reverses_id=None):
        allowed = {"invoice": 1, "charge": 1, "opening": 1, "credit": -1, "receipt": -1, "payment": -1, "refund": 1, "adjustment": 0, "reversal": 0}
        if account_type not in ("customer", "vendor") or kind not in allowed or not isinstance(amount, int) or (allowed[kind] and amount <= 0) or amount == 0:
            raise RuleError("Choose a valid account, entry type, and nonzero whole-paise amount.")
        if (account_type == "customer" and kind == "payment") or (account_type == "vendor" and kind == "receipt"):
            raise RuleError("Use customer receipts or vendor payments for this account.")
        table = "customers" if account_type == "customer" else "masters"
        if not c.execute(f"SELECT 1 FROM {table} WHERE id=?", (account_id,)).fetchone():
            raise RuleError("Counterparty does not exist.")
        if job_id:
            j = c.execute("SELECT customer_id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not j or (account_type == "customer" and j[0] != account_id):
                raise RuleError("This job belongs to a different customer.")
        existing = c.execute("SELECT * FROM entries WHERE operation_id=?", (operation_id,)).fetchone()
        signed = amount * allowed[kind] if allowed[kind] else amount
        if existing:
            if (existing["account_type"], existing["account_id"], existing["kind"], existing["amount"]) != (account_type, account_id, kind, signed):
                raise RuleError("Operation ID was already used for a different financial entry.")
            return existing["id"]
        ident = insert(c, "entries", operation_id=operation_id, account_type=account_type, account_id=account_id, job_id=job_id, quote_id=quote_id, kind=kind, amount=signed, posted=day(posted or date.today().isoformat()), created=now(), method=method, reference=reference, notes=notes, payload=json.dumps(payload or {}), reverses_id=reverses_id, actor=self.user["id"])
        self.audit(c, "job" if job_id else "account", job_id or account_id, "finance_posted", {"entry": ident, "account_type": account_type, "kind": kind, "amount": signed, "notes": notes})
        return ident

    def post(self, account_type, account_id, kind, amount, operation_id, allocations=(), **fields):
        self.require_permission('collect_payment')
        if self.user["role"] != "owner" and (account_type != "customer" or kind != "receipt"):
            raise RuleError("Only the owner can post bills, refunds, vendor entries, or corrections.")
        if kind in ("credit", "adjustment", "opening") and not fields.get("notes", "").strip():
            raise RuleError("Credits, adjustments and opening balances require a reason/provenance.")
        if kind in ("invoice", "reversal"):
            raise RuleError("Use Issue bill or Reverse entry to preserve its source reference.")
        with self.db.transaction() as c:
            ident = self._post(c, account_type, account_id, kind, amount, operation_id, **fields)
            if allocations and not c.execute("SELECT 1 FROM allocations WHERE payment_id=?", (ident,)).fetchone():
                if kind not in ("payment", "receipt") or sum(a for _, a in allocations) > amount:
                    raise RuleError("Payment allocations exceed available funds.")
                for charge_id, allocation in allocations:
                    charge = c.execute("SELECT * FROM entries WHERE id=?", (charge_id,)).fetchone()
                    used = c.execute("SELECT COALESCE(sum(a.amount),0) FROM allocations a WHERE a.charge_id=? AND NOT EXISTS(SELECT 1 FROM allocation_reversals r WHERE r.allocation_id=a.id)", (charge_id,)).fetchone()[0]
                    if not charge or charge["account_type"] != account_type or charge["account_id"] != account_id or charge["amount"] <= 0 or allocation <= 0 or used + allocation > charge["amount"]:
                        raise RuleError("Invalid allocation or charge already fully allocated.")
                    if c.execute('SELECT 1 FROM entries WHERE reverses_id=?', (charge_id,)).fetchone():
                        raise RuleError('Cannot allocate to a reversed charge.')
                    insert(c, "allocations", payment_id=ident, charge_id=charge_id, amount=allocation)
        return ident

    def invoice(self, quote_id, operation_id):
        # Counter staff run the whole counter workflow: they issue the quotation, record
        # the customer's approval and take payment, so they also raise the bill that
        # follows from the approved quotation. Correcting a posted entry stays with the
        # owner, in `reverse`.
        self.require_permission('billing')
        with self.db.transaction() as c:
            q = c.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not q or q["state"] != "approved":
                raise RuleError("Bill must refer to an approved quotation.")
            j = self._job(c, q["job_id"])
            existing = c.execute("SELECT id FROM entries WHERE quote_id=? AND kind='invoice'", (quote_id,)).fetchone()
            if existing:
                return existing[0]
            prior = c.execute("SELECT e.id FROM entries e WHERE e.job_id=? AND e.kind='invoice' AND NOT EXISTS(SELECT 1 FROM entries r WHERE r.reverses_id=e.id)", (j['id'],)).fetchone()
            if prior:
                raise RuleError('A previous bill is still posted for this job. Reverse it with a reason before billing the full revised quotation.')
            if not q["total"]:
                raise RuleError("Zero-charge warranty work needs a warranty summary, not a money posting.")
            from .billing import Billing
            Billing(self).guard_final_bill(c, j["id"], q["total"])
            return self._post(c, "customer", j["customer_id"], "invoice", q["total"], operation_id, job_id=j["id"], quote_id=quote_id, payload=dict(q), notes="Issued customer bill")

    def reverse(self, entry_id, reason, operation_id):
        self.require("owner")
        if not reason.strip():
            raise RuleError("A correction reason is required.")
        with self.db.transaction() as c:
            e = c.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not e or e["kind"] == "reversal":
                raise RuleError("Select an original entry to reverse.")
            ident = self._post(c, e["account_type"], e["account_id"], "reversal", -e["amount"], operation_id, job_id=e["job_id"], reverses_id=entry_id, notes=reason)
            for allocation in c.execute('SELECT id FROM allocations WHERE payment_id=? OR charge_id=?', (entry_id,entry_id)).fetchall():
                c.execute('INSERT OR IGNORE INTO allocation_reversals(allocation_id,created,actor,reason) VALUES (?,?,?,?)', (allocation[0],now(),self.user['id'],reason))
            return ident

    def decline_balance(self, job_id):
        j = self.job(job_id)
        allowed = (j["transport_agreed"] if j["policy"] == "AGREED_TRANSPORT_ONLY" else 0) + j["assessment_agreed"]
        retained = -(self.db.one("SELECT COALESCE(sum(e.amount),0) AS n FROM entries e LEFT JOIN entries original ON original.id=e.reverses_id WHERE e.job_id=? AND e.account_type='customer' AND (e.kind IN ('receipt','refund') OR (e.kind='reversal' AND original.kind IN ('receipt','refund')))", (job_id,))["n"])
        corrections = self.db.one("SELECT COALESCE(sum(e.amount),0) n FROM entries e LEFT JOIN entries original ON original.id=e.reverses_id WHERE e.job_id=? AND e.account_type='customer' AND (e.kind IN ('credit','adjustment') OR (e.kind='reversal' AND original.kind IN ('credit','adjustment')))", (job_id,))['n']
        return {"agreed_charges": allowed, 'waivers_adjustments': corrections, "money_retained": retained, "balance_due": allowed + corrections - retained}

    def bill_decline(self, job_id, operation_id):
        # Reached from the counter-permitted billing review, on the agreed return charges
        # the customer already consented to at intake.
        self.require_permission('billing')
        with self.db.transaction() as c:
            j = self._job(c, job_id)
            if j["stage"] not in ("return_unrepaired", "ready_unrepaired"):
                raise RuleError("Record the decline/return outcome first.")
            prior=c.execute("SELECT e.id,e.operation_id FROM entries e WHERE e.job_id=? AND e.kind='invoice' AND NOT EXISTS(SELECT 1 FROM entries r WHERE r.reverses_id=e.id)",(job_id,)).fetchone()
            if prior:
                if prior['operation_id']==operation_id:
                    return prior['id']
                raise RuleError('Reverse the prior bill before issuing replacement decline charges.')
            amount = (j["transport_agreed"] if j["policy"] == "AGREED_TRANSPORT_ONLY" else 0) + j["assessment_agreed"]
            if not amount:
                raise RuleError("No agreed cancellation charges; no bill is needed.")
            return self._post(c, "customer", j["customer_id"], "invoice", amount, operation_id, job_id=job_id, payload={"policy": j["policy"], "transport": j["transport_agreed"], "assessment": j["assessment_agreed"]}, notes="Agreed decline/return charges")

    def expense(self, amount, allocations, kind, payer, reference, payload, operation_id, included_entry_id=None):
        self.require("owner")
        if not isinstance(amount, int) or amount < 0 or sum(allocations.values()) != amount or any(not isinstance(v, int) or v < 0 for v in allocations.values()):
            raise RuleError("Job allocations must exactly equal the shared expense.")
        if kind=='additional_vendor_charge' and (not payload.get('reason') or not reference or payload.get('acceptance') not in ('pending','accepted','declined')):
            raise RuleError('Additional charges require a reason, supporting reference and pending/accepted/declined status.')
        with self.db.transaction() as c:
            duplicate = c.execute("SELECT id FROM expenses WHERE operation_id=?", (operation_id,)).fetchone()
            if duplicate:
                return duplicate[0]
            if included_entry_id:
                e = c.execute("SELECT * FROM entries WHERE id=? AND account_type='vendor' AND kind='charge'", (included_entry_id,)).fetchone()
                if not e or sum(allocations.values()) > e["amount"]:
                    raise RuleError("Included cost needs a sufficient confirmed vendor bill.")
            ident = insert(c, "expenses", operation_id=operation_id, kind=kind, amount=amount, payer=payer, reference=reference, included_entry_id=included_entry_id, payload=json.dumps(payload), created=now(), actor=self.user["id"])
            for job_id, portion in allocations.items():
                insert(c, "expense_allocations", expense_id=ident, job_id=job_id, amount=portion)
                self.audit(c, "job", job_id, "expense_allocated", {"expense": ident, "amount": portion, "included_entry": included_entry_id})
        return ident
