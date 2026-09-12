"""Issued event snapshots; holdings and movements remain the custody ledger."""
import json
from .domain import now, RuleError
from .persistence import insert


class JobCards:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def rows(self, job_id):
        self.s.require()
        return self.db.rows("SELECT c.*,j.number || ' / CARD-' || printf('%02d',c.sequence) AS number FROM job_cards c JOIN jobs j ON j.id=c.job_id WHERE c.job_id=? ORDER BY sequence", (job_id,))

    def issue(self, job_id, kind, event_key, payload=None, items=None):
        self.s.require('owner', 'counter')
        p = payload or {}
        with self.db.transaction() as c:
            old = c.execute('SELECT id FROM job_cards WHERE event_key=?', (event_key,)).fetchone()
            if old:
                return old[0]
            j = self.s.job(job_id)
            shop = {k: self.db.setting(k, '') for k in ('shop_name', 'address', 'phone', 'email')}
            shop['name'] = shop.pop('shop_name') or 'Repair shop'
            customer = dict(c.execute('SELECT id,name,phone,email,address FROM customers WHERE id=?', (j['customer_id'],)).fetchone())
            assignment = self.db.one('SELECT a.*,m.name,m.contact,m.details,u.name technician FROM assignments a LEFT JOIN masters m ON m.id=a.contact_id LEFT JOIN users u ON u.id=a.technician_id WHERE a.id=?', (j['assignment_id'],)) or {}
            external = kind.startswith(('third_party', 'service_center', 'carrier'))
            if external:
                movement_ids=p.get('movement_ids',[])
                if not movement_ids:
                    raise RuleError('An external card requires actual recorded custody movements.')
                for movement_id in movement_ids:
                    movement=c.execute('SELECT m.*,i.job_id FROM movements m JOIN items i ON i.id=m.item_id WHERE m.id=? AND i.job_id=?',(movement_id,job_id)).fetchone()
                    if not movement or kind.endswith('return') and not movement['to_location'].startswith('shop:') or kind.endswith('dispatch') and not movement['from_location'].startswith('shop:'):
                        raise RuleError('The card must match the recorded custody event.')
            party = {'id': assignment.get('contact_id'), 'name': assignment.get('name'), 'contact': assignment.get('contact'), 'details': assignment.get('details')}
            if kind == 'customer_receiving':
                sender, receiver = customer, shop
            elif kind == 'customer_delivery':
                sender, receiver = shop, customer
            elif kind == 'in_house_assignment':
                sender, receiver = shop, {'id': assignment.get('technician_id'), 'name': assignment.get('technician')}
            elif external:
                if not party['id']:
                    raise RuleError('Select the external repairer before issuing a card.')
                sender, receiver = (party, shop) if kind.endswith('return') else (shop, party)
            else:
                raise RuleError('Unknown job card type.')
            sequence = c.execute('SELECT COALESCE(max(sequence),0)+1 FROM job_cards WHERE job_id=?', (job_id,)).fetchone()[0]
            stamp = now()
            device = self.db.one('SELECT * FROM devices WHERE id=?', (j['device_id'],)) or {}
            snapshot = {'master_job': j['number'], 'card_number': f'CARD-{sequence:02d}', 'kind': kind, 'shop_name':shop['name'],
                'from': sender, 'to': receiver, 'device_id': j['device_id'], 'device': j['device'],
                'brand': device.get('brand',''), 'model': device.get('model',''), 'serial': j['serial'],
                'device_type': (self.db.one('SELECT name FROM masters WHERE id=?',(j['category_id'],)) or {}).get('name','Not specified'),
                'requested_service': (self.db.one('SELECT name FROM masters WHERE id=?',(j['service_id'],)) or {}).get('name','Not specified'),
                'complaint': j['complaint'], 'condition': p.get('condition',j['damage']),
                'items': items if items is not None else self.db.rows('SELECT id,type,description,quantity,serial,condition FROM items WHERE job_id=?', (job_id,)),
                'device_photo_references': [r['id'] for r in self.db.rows("SELECT id FROM attachments WHERE device_id=? AND kind='product_photo'", (j['device_id'],))],
                'effective': stamp, 'completed': stamp, 'status': 'Completed', 'staff': self.s.user['name'],
                'expected_return': j['return_due'], 'reference': p.get('reference',assignment.get('reference','')),
                'notes': p.get('notes',''), 'acknowledgment': p.get('acknowledgment',''), 'movement_ids': p.get('movement_ids',[])}
            # Never copy a whole customer/job/attachment record to an external card.
            ident = insert(c, 'job_cards', job_id=job_id, sequence=sequence, kind=kind, event_key=event_key,
                from_name=sender['name'], to_name=receiver['name'], effective=stamp, created=stamp,
                actor=self.s.user['id'], snapshot=json.dumps(snapshot))
            self.s.audit(c,'job',job_id,'job_card_created',{'card':f'CARD-{sequence:02d}','type':kind,'from':sender['name'],'to':receiver['name']})
            return ident

    def print(self, card_id):
        from .documents import Documents
        from .lifecycle import local_time
        self.s.require('owner','counter')
        card = self.db.one('SELECT * FROM job_cards WHERE id=?',(card_id,))
        if not card:
            raise RuleError('Select a job card.')
        p=json.loads(card['snapshot'])
        def party(v):
            return '\n'.join(str(x) for k,x in v.items() if k!='id' and x)
        sections=[('From',party(p['from'])),('To',party(p['to'])),('Device',f"DEV-{p['device_id']:06d} · {p['device']}\nType: {p.get('device_type','Not specified')} · Service: {p.get('requested_service','Not specified')}\nBrand: {p['brand'] or 'Not recorded'} · Model: {p['model'] or 'Not recorded'}\nSerial / IMEI: {p['serial'] or 'Not recorded'}"),
            ('Complaint and condition',p['complaint']+'\n'+p['condition']),
            ('Items handed over',[{k:r.get(k,'') for k in ('description','quantity','serial','condition')} for r in p['items']]),
            ('Receipt details',f"Effective: {local_time(p['effective'])} IST\nReceived / recorded by: {p['staff']}\nExpected return: {p['expected_return'] or 'Not specified'}\nReference: {p['reference'] or 'Not recorded'}\nAcknowledgment: {p['acknowledgment'] or 'Not recorded'}\nDevice photo references: {', '.join(str(i) for i in p['device_photo_references']) or 'None at issue time'}\n{p['notes']}")]
        path=Documents(self.s).snapshot(p['kind'].replace('_',' ').title()+' · '+p['master_job']+' / '+p['card_number'],sections,card['job_id'],shop_name=p.get('shop_name'))
        with self.db.transaction() as c:
            self.s.audit(c,'job',card['job_id'],'job_card_printed',{'card_id':card_id,'card':p['card_number']})
        return path
