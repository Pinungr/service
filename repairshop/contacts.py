"""Contacts & Services: reusable repair partners, suppliers and transport services.

Every reusable business contact is one `masters` row, configured once and selected many
times. A repair or dispatch stores the selected id for reporting and an immutable
snapshot of what the contact looked like at that moment for history, so editing a
directory record never rewrites where an old repair was sent.
"""
import json
import re
from .domain import RuleError, norm, phone, now
from . import addresses

#: Reusable business contacts and the words the shop owner sees for them. Internal kinds
#: are unchanged so existing records, custody tokens and accounts keep working.
CONTACT_KINDS = {
    'vendor': 'Third-Party Repairer',
    'centre': 'Authorized Service Centre',
    'supplier': 'Supplier',
    'transporter': 'Bus / Transport Service',
}
#: Shop configuration lists that are not contacts.
SETUP_KINDS = {
    'technician': 'Technicians', 'service': 'Services', 'category': 'Categories',
    'brand': 'Brands', 'model': 'Models', 'accessory': 'Accessories', 'payment_method': 'Payment methods',
}
#: Optional profile columns each contact kind may use, beyond name and mobile.
PROFILE_FIELDS = {
    'vendor': ('contact_person', 'alternate', 'email', 'city', 'specialization', 'notes'),
    'centre': ('contact_person', 'alternate', 'email', 'city', 'specialization', 'notes',
               'warranty_service', 'pickup', 'turnaround_days'),
    'supplier': ('contact_person', 'alternate', 'email', 'city', 'specialization', 'notes'),
    'transporter': ('contact_person', 'alternate', 'route_from', 'route_to', 'pickup_point',
                    'drop_point', 'vehicle_number', 'notes'),
}
FLAGS = ('warranty_service', 'pickup')
#: Product categories, brands and services a partner works on. Used to recommend, never to hide.
SUPPORT_KINDS = ('category', 'brand', 'service')
PARTNER_KINDS = ('vendor', 'centre')


SINGULAR = {'technician': 'Internal Technician', 'service': 'Repair / Service', 'category': 'Product Category',
            'brand': 'Brand', 'model': 'Model', 'accessory': 'Accessory', 'payment_method': 'Payment Method'}


def label(kind):
    """The one shop-owner name for a directory kind; internal kind values never change."""
    return CONTACT_KINDS.get(kind) or SINGULAR.get(kind) or kind.replace('_', ' ').title()


def _row(row):
    return dict(row) if row is not None else None


def supports(c, master_id):
    """Names of the categories, brands and services one contact supports, by kind."""
    found = {kind: [] for kind in SUPPORT_KINDS}
    for row in c.execute('''SELECT m.id,m.kind,m.name FROM master_supports s JOIN masters m ON m.id=s.target_id
            WHERE s.master_id=? ORDER BY m.name''', (master_id,)).fetchall():
        found.setdefault(row['kind'], []).append(row['name'])
    return found


def snapshot(c, master_id):
    """What this contact looked like now, for storing beside a repair or a dispatch.

    Empty values are left out so a snapshot reads cleanly in history and documents.
    """
    row = _row(c.execute('SELECT * FROM masters WHERE id=?', (master_id,)).fetchone())
    if not row:
        return {}
    kind = row['kind']
    shot = {'id': row['id'], 'kind': kind, 'name': row['name'], 'phone': row.get('contact', ''),
            'captured': now()}
    for key in PROFILE_FIELDS.get(kind, ()):
        shot[key] = row.get(key)
    if kind in ('vendor', 'centre', 'supplier'):
        shot['address'] = addresses.readable(row)
        for key in ('district', 'state', 'pincode'):
            shot[key] = row.get(key, '')
    if kind in PARTNER_KINDS:
        for key, names in supports(c, master_id).items():
            shot[key + '_supported'] = names
    return {k: v for k, v in shot.items() if v not in (None, '', [], 0) or k in ('id', 'name')}


def place(shot):
    """Short locality for one line of a selector: city, else district, else first address line."""
    shot = shot or {}
    first = (shot.get('address') or '').split('\n')[0]
    return ', '.join(dict.fromkeys(x for x in (shot.get('city'), shot.get('district')) if x)) or first


def headline(shot):
    """What the partner does: route for a bus service, otherwise specialization / supported work."""
    shot = shot or {}
    if shot.get('kind') == 'transporter':
        return ' → '.join(x for x in (shot.get('route_from'), shot.get('route_to')) if x)
    work = list(dict.fromkeys(filter(None, [*shot.get('brand_supported', []), *shot.get('category_supported', []),
                                            *[x.strip() for x in (shot.get('specialization') or '').split(',')]])))
    return ' · '.join(work)


def summary(shot):
    """Compact read-only card shown after a contact is selected, and in history."""
    shot = shot or {}
    if not shot:
        return ''
    person = ' · '.join(x for x in (shot.get('contact_person'), shot.get('phone')) if x)
    lines = [shot.get('name', ''), headline(shot), person]
    if shot.get('kind') == 'transporter':
        lines += ['Pickup: ' + shot['pickup_point'] if shot.get('pickup_point') else '',
                  'Drop: ' + shot['drop_point'] if shot.get('drop_point') else '',
                  'Usual bus: ' + shot['vehicle_number'] if shot.get('vehicle_number') else '']
    else:
        lines.append(place(shot))
        if shot.get('kind') == 'centre':
            lines.append(' · '.join(filter(None, [
                'Warranty jobs accepted' if shot.get('warranty_service') else '',
                'Pickup available' if shot.get('pickup') else '',
                f"Usual turnaround {shot['turnaround_days']} days" if shot.get('turnaround_days') else ''])))
    return '\n'.join(x for x in lines if x)


def secondary(shot):
    """Second line in a search result: where they are and how to reach them."""
    shot = shot or {}
    first = headline(shot) if shot.get('kind') == 'transporter' else place(shot)
    return ' · '.join(x for x in (first, shot.get('phone')) if x)


def _digits(value):
    digits = re.sub(r'\D', '', value or '')
    return digits[-10:] if len(digits) >= 10 else digits


def _tokens(value):
    return {t for t in re.split(r'[^\w]+', norm(value or '')) if len(t) > 2}


class Contacts:
    """Read and write reusable contacts through the existing master-data service."""

    def __init__(self, service):
        self.s, self.db = service, service.db

    # ---- reads ----------------------------------------------------------
    def get(self, master_id):
        with self.db.read() as c:
            row = _row(c.execute('SELECT * FROM masters WHERE id=?', (master_id,)).fetchone())
            if not row:
                return None
            row['supports'] = [r['target_id'] for r in c.execute(
                'SELECT target_id FROM master_supports WHERE master_id=?', (master_id,)).fetchall()]
            row['snapshot'] = snapshot(c, master_id)
        return row

    def snapshot(self, master_id):
        with self.db.read() as c:
            return snapshot(c, master_id)

    def directory(self, kind, search='', include_inactive=False):
        """Rows for the Contacts & Services screen: friendly columns, newest data."""
        self.s.require()
        where, args = ['m.kind=?'], [kind]
        if not include_inactive:
            where.append('m.active=1')
        if search.strip():
            term = '%' + search.strip() + '%'
            where.append('(m.name LIKE ? OR m.contact LIKE ? OR m.alternate LIKE ? OR m.contact_person LIKE ? '
                         'OR m.city LIKE ? OR m.district LIKE ? OR m.specialization LIKE ? '
                         'OR m.route_from LIKE ? OR m.route_to LIKE ?)')
            args += [term] * 9
        rows = self.db.rows('SELECT m.* FROM masters m WHERE ' + ' AND '.join(where) + ' ORDER BY m.active DESC,m.name', args)
        with self.db.read() as c:
            for row in rows:
                shot = snapshot(c, row['id'])
                row['mobile'] = row.get('contact', '')
                row['location'] = place(shot)
                row['works_on'] = headline(shot)
                row['status'] = 'Active' if row['active'] else 'Inactive'
        return rows

    def context(self, job_id):
        """The product facts used to recommend partners for one repair."""
        if not job_id:
            return {}
        row = self.db.one('''SELECT j.category_id,j.service_id,j.lifecycle_data,d.brand,
                cat.name AS category,svc.name AS service
            FROM jobs j LEFT JOIN devices d ON d.id=j.device_id
            LEFT JOIN masters cat ON cat.id=j.category_id LEFT JOIN masters svc ON svc.id=j.service_id
            WHERE j.id=?''', (job_id,)) or {}
        try:
            data = json.loads(row.get('lifecycle_data') or '{}')
        except ValueError:
            data = {}
        return dict(category_id=row.get('category_id'), service_id=row.get('service_id'),
                    brand=row.get('brand') or '', category=row.get('category') or '',
                    service=row.get('service') or '', diagnosis=data.get('diagnosis', ''),
                    under_warranty=data.get('warranty_status') == 'under_warranty')

    def options(self, kind, job_id=None, search=''):
        """Active contacts of one kind, the relevant ones first.

        Ranking only reorders: every active contact stays selectable, because the shop may
        know something the recorded product data does not.
        """
        self.s.require()
        ctx = self.context(job_id)
        rows = self.db.rows('SELECT id FROM masters WHERE kind=? AND active=1 ORDER BY name', (kind,))
        brand = norm(ctx.get('brand', ''))
        words = _tokens(' '.join([ctx.get('brand', ''), ctx.get('category', ''), ctx.get('service', ''), ctx.get('diagnosis', '')]))
        result = []
        with self.db.read() as c:
            for row in rows:
                shot = snapshot(c, row['id'])
                links = {r['target_id']: r for r in (dict(x) for x in c.execute(
                    '''SELECT s.target_id,m.kind,m.name,m.normalized FROM master_supports s JOIN masters m ON m.id=s.target_id
                       WHERE s.master_id=?''', (row['id'],)).fetchall())}
                reasons, score = [], 0
                same_brand = [l['name'] for l in links.values() if l['kind'] == 'brand' and l['normalized'] == brand]
                if brand and same_brand:
                    score += 4
                    reasons.append(same_brand[0])
                if ctx.get('category_id') in links:
                    score += 2
                    reasons.append(ctx['category'])
                if ctx.get('service_id') in links:
                    score += 1
                    reasons.append(ctx['service'])
                # Free-text specialization still counts, so older records and quick adds rank too.
                matched = words & _tokens(shot.get('specialization', '') + ' ' + shot.get('name', ''))
                if matched and not reasons:
                    score += 1
                    reasons.append(', '.join(sorted(matched)))
                if kind == 'centre' and ctx.get('under_warranty') and shot.get('warranty_service') and score:
                    score += 1
                if search and norm(search) not in norm(shot['name'] + ' ' + secondary(shot) + ' ' + headline(shot)):
                    continue
                result.append(dict(id=row['id'], name=shot['name'], secondary=secondary(shot),
                                   headline=headline(shot), summary=summary(shot), snapshot=shot,
                                   score=score, recommended=score > 0, reasons=reasons))
        result.sort(key=lambda r: (-r['score'], norm(r['name'])))
        return result

    def duplicates(self, kind, name, mobile='', city=''):
        """Probable existing contacts for a new entry: same mobile, or a very similar name."""
        self.s.require()
        found = []
        digits, words, normalized = _digits(mobile), _tokens(name), norm(name or '')
        for row in self.db.rows('SELECT * FROM masters WHERE kind=?', (kind,)):
            reasons = []
            if normalized and row['normalized'] == normalized:
                reasons.append('same name')
            if digits and len(digits) >= 8 and digits in {_digits(row['contact']), _digits(row.get('alternate', ''))}:
                reasons.append('same mobile')
            elif words and not reasons:
                theirs = _tokens(row['name'])
                overlap = len(words & theirs) / max(1, min(len(words), len(theirs)))
                same_place = city and norm(city) in (norm(row.get('city') or ''), norm(row.get('district') or ''))
                if overlap >= 1 or (overlap >= 0.5 and same_place):
                    reasons.append('similar name' + (' in ' + city if same_place else ''))
            if reasons:
                row['reasons'] = reasons
                row['exact'] = 'same name' in reasons
                row['secondary'] = secondary(self.snapshot(row['id']))
                found.append(row)
        found.sort(key=lambda r: (not r['exact'], 'same mobile' not in r['reasons'], r['name']))
        return found

    def activity(self, master_id):
        """Simple totals for one contact, from the ids recorded on repairs and dispatches."""
        self.s.require()
        row = self.db.one('SELECT kind FROM masters WHERE id=?', (master_id,)) or {}
        if row.get('kind') == 'transporter':
            totals = self.db.one('''SELECT count(*) AS dispatches,COALESCE(sum(amount),0) AS transport
                FROM dispatches WHERE transporter_id=? AND current=1''', (master_id,))
            return dict(dispatches=totals['dispatches'], transport_total=totals['transport'])
        jobs = self.db.rows('''SELECT j.id,j.stage,j.lifecycle_data,j.assignment_id,a.id AS attempt,a.route
            FROM assignments a JOIN jobs j ON j.id=a.job_id WHERE a.contact_id=?''', (master_id,))
        current = [j for j in jobs if j['assignment_id'] == j['attempt']]
        unable = sum(1 for j in current if json.loads(j['lifecycle_data'] or '{}').get('unrepaired'))
        closed = [j for j in current if j['stage'] in ('collected', 'closed')]
        turnaround = self.db.one('''SELECT avg(julianday(r.created)-julianday(d.actual_dispatch_at)) AS days
            FROM dispatches d JOIN return_verifications r ON r.dispatch_id=d.id
            WHERE d.contact_id=? AND d.actual_dispatch_at IS NOT NULL''', (master_id,))
        return dict(jobs=len({j['id'] for j in jobs}), open=len(current) - len(closed),
                    completed=len(closed) - sum(1 for j in closed if json.loads(j['lifecycle_data'] or '{}').get('unrepaired')),
                    unable=unable, replaced_by_other=len({j['id'] for j in jobs}) - len(current),
                    warranty_jobs=sum(1 for j in current if j['route'] == 'warranty_centre'
                                      and json.loads(j['lifecycle_data'] or '{}').get('warranty_covered')),
                    turnaround_days=round(turnaround['days'], 1) if turnaround and turnaround['days'] is not None else None)

    # ---- writes ---------------------------------------------------------
    def save(self, kind, values, ident=None, job_id=None):
        """Create or update one contact from the Contacts & Services form or a quick add.

        Only name and mobile are required. Everything else can be completed later.
        """
        if kind not in CONTACT_KINDS:
            raise RuleError('Choose a contact type.')
        values = dict(values)
        name = str(values.pop('name', '') or '').strip()
        mobile = str(values.pop('mobile', values.pop('contact', '')) or '').strip()
        if not name:
            raise RuleError('Enter the ' + label(kind).lower() + ' name.')
        if not mobile:
            raise RuleError('Enter a mobile number for this ' + label(kind).lower() + '.')
        try:
            mobile = phone(mobile)
            if values.get('alternate'):
                values['alternate'] = phone(values['alternate'])
        except RuleError:
            raise RuleError('Enter a valid mobile number, including the country code when needed.') from None
        address = {k: values.pop(k) for k in addresses.FIELDS if k in values}
        if kind == 'transporter':
            address = {}
        profile = {k: values.pop(k) for k in PROFILE_FIELDS[kind] if k in values}
        support_ids = values.pop('supports', None)
        brands = values.pop('brands', None)
        active = values.pop('active', True)
        photo_id = values.pop('photo_id', None)
        if values:
            raise RuleError('Unknown contact detail: ' + ', '.join(sorted(values)))
        if brands is not None:
            support_ids = list(support_ids or []) + self._brand_ids(brands)
        return self.s.save_master(kind, name, contact=mobile, ident=ident, active=active, photo_id=photo_id,
                                  profile=profile, supports=support_ids, address_required=False,
                                  workflow_job_id=job_id, **({k: v for k, v in address.items()} if any(address.values()) else {}))

    def quick_create(self, kind, name, mobile, allow_duplicate=False, job_id=None, **extra):
        """The lightweight add used inside a workflow: create, then hand back the id to select.

        A probable duplicate is refused unless the user chose "Create anyway", so the shop
        does not end up with two records for the same business.
        """
        if not allow_duplicate:
            matches = self.duplicates(kind, name, mobile, extra.get('city', ''))
            if matches:
                raise DuplicateContact(matches)
        elif self.db.one('SELECT 1 FROM masters WHERE kind=? AND normalized=?', (kind, norm(name or ''))):
            raise RuleError('A ' + label(kind).lower() + ' with exactly this name already exists. Use the existing record.')
        return self.save(kind, dict(extra, name=name, mobile=mobile), job_id=job_id)

    def set_active(self, master_id, active):
        row = self.db.one('SELECT kind,name FROM masters WHERE id=?', (master_id,))
        if not row:
            raise RuleError('Select a contact.')
        return self.s.save_master(row['kind'], row['name'], ident=master_id, active=active, keep_profile=True)

    def _brand_ids(self, text):
        """Find or create the brand records for a comma-separated list typed by the owner."""
        ids = []
        for name in dict.fromkeys(x.strip() for x in str(text or '').split(',') if x.strip()):
            row = self.db.one("SELECT id FROM masters WHERE kind='brand' AND normalized=?", (norm(name),))
            ids.append(row['id'] if row else self.s.save_master('brand', name))
        return ids


class DuplicateContact(RuleError):
    """A probable existing contact was found; the caller decides to reuse or create anyway."""

    def __init__(self, matches):
        self.matches = matches
        first = matches[0]
        super().__init__('Possible existing contact: ' + first['name']
                         + (' · ' + first['secondary'] if first.get('secondary') else '')
                         + ' (' + ', '.join(first['reasons']) + ').')
