"""Issued event snapshots; holdings and movements remain the custody ledger."""
import json
from .domain import now, RuleError
from .persistence import insert


class JobCards:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def rows(self, job_id):
        self.s.require()
        with self.db.read() as c:self.s._job(c,job_id)
        rows=self.db.rows("SELECT c.*,j.number || ' / CARD-' || printf('%02d',c.sequence) AS number FROM job_cards c JOIN jobs j ON j.id=c.job_id WHERE c.job_id=? ORDER BY sequence", (job_id,))
        if self.s.user['role']!='owner':
            from .inventory import public_values
            for r in rows:r['snapshot']=json.dumps(public_values(json.loads(r['snapshot'])))
        return rows

    def _party(self,location,shop):
        kind,_,name=location.partition(':')
        if kind=='shop':return dict(shop,location=name)
        if kind=='stock':return dict(shop,location='Stock: '+name)
        if kind=='technician':
            if name.startswith('master-'):
                user=self.db.one("SELECT id,name FROM masters WHERE id=? AND kind='technician'",(name[7:],))
            else:
                user=self.db.one('SELECT id,name FROM users WHERE id=?',(name,))
            return user or {'name':name,'location':'Technician work area'}
        return {'name':name or location,'location':kind}

    def return_details(self,j,p):
        data=json.loads(j['lifecycle_data']);details=data.get('route_details',{})
        parts=self.db.rows("SELECT name,source,quantity,serial,installed_by,installed_at,warranty_duration,warranty_unit,warranty_provider,warranty_terms,supplier_snapshot FROM repair_parts WHERE job_id=? AND status='installed'",(j['id'],))
        for part in parts:
            part['supplier']=(json.loads(part.pop('supplier_snapshot') or '{}')).get('name','Shop stock' if part['source']=='stock' else '')
        warranty=self.db.one('SELECT decision,rma,findings,covered,excluded,terms FROM warranty WHERE job_id=? ORDER BY id DESC LIMIT 1',(j['id'],)) or {}
        result=p.get('repair_result') or ('RETURNED WITHOUT REPAIR' if data.get('unrepaired') else 'REPLACED' if data.get('replacement') else 'REPAIRED' if data.get('repair_completed') else 'NOT RECORDED')
        from .costing import JobCosts
        repairer=self.db.one('SELECT m.name,m.contact FROM assignments a JOIN masters m ON m.id=a.contact_id WHERE a.id=?',(j['assignment_id'],)) or {}
        remaining=self.db.one("SELECT h.location FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND i.type='device' AND h.quantity>0 AND h.location NOT LIKE 'shop:%' AND h.location NOT LIKE 'exception:%'",(j['id'],))
        return dict(result=result,repair_status='Partial return; device remains away from shop' if remaining else 'Received at shop; final quality check pending',repairer=repairer.get('name','Not recorded'),repairer_contact=repairer.get('contact',''),work_performed=p.get('work_performed') or data.get('repair_summary',''),
            diagnosis=data.get('diagnosis',''),parts_installed=parts,parts_reported=p.get('parts_reported') or data.get('parts_used',''),
            vendor_invoice=p.get('vendor_invoice') or details.get('vendor_invoice',''),service_reference=details.get('external_reference',''),
            claim_number=details.get('claim_number') or warranty.get('rma',''),warranty_decision=warranty,
            chargeable_repair=bool(warranty.get('decision') in ('rejected','partial')),
            replacement=data.get('replacement',{}),condition=p.get('condition',''),notes=p.get('notes',''),
            receiver=p.get('counterparty',self.s.user['name']),acknowledgment=p.get('acknowledgment',''),costs=JobCosts(self.s)._summary(j['id']))

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
            assignment = self.db.one("SELECT a.*,m.name,m.contact,m.details,COALESCE(tm.name,u.name) technician FROM assignments a LEFT JOIN masters m ON m.id=a.contact_id LEFT JOIN users u ON u.id=a.technician_id LEFT JOIN masters tm ON tm.id=a.technician_master_id WHERE a.id=?", (j['assignment_id'],)) or {}
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
                sender, receiver = shop, {'id': assignment.get('technician_master_id') or assignment.get('technician_id'), 'name': assignment.get('technician')}
            elif external:
                if not party['id']:
                    raise RuleError('Select the external repairer before issuing a card.')
                sender, receiver = (party, shop) if kind.endswith('return') else (shop, party)
            elif kind in ('in_house_handover','in_house_return','part_transfer'):
                sender,receiver=shop,shop
            else:
                raise RuleError('Unknown job card type.')
            if p.get('movement_ids'):
                moves=self.db.rows('SELECT m.*,i.job_id FROM movements m JOIN items i ON i.id=m.item_id WHERE m.id IN ('+','.join('?' for _ in p['movement_ids'])+')',p['movement_ids'])
                if len(moves)!=len(p['movement_ids']) or any(m['job_id']!=job_id for m in moves):raise RuleError('All custody movements must belong to this master job.')
                if len({(m['from_location'],m['to_location']) for m in moves})!=1:raise RuleError('One custody card must describe one sender and receiver. Record separate handovers for different holders.')
                sender=self._party(moves[0]['from_location'],shop);receiver=self._party(moves[0]['to_location'],shop)
            if kind=='part_transfer':
                movement=self.db.one('SELECT * FROM stock_movements WHERE id=? AND job_id=?',(p.get('stock_movement_id'),job_id))
                if not movement or movement['kind'] not in ('ISSUED_TO_VENDOR','ISSUED_TO_TECHNICIAN','RETURNED_UNUSED'):raise RuleError('A part transfer card requires a matching stock custody event.')
                sender=self._party(movement['from_location'],shop);receiver=self._party(movement['to_location'],shop)
            sequence = c.execute('SELECT COALESCE(max(sequence),0)+1 FROM job_cards WHERE job_id=?', (job_id,)).fetchone()[0]
            stamp = now()
            device = self.db.one('SELECT * FROM devices WHERE id=?', (j['device_id'],)) or {}
            snapshot = {'master_job': j['number'], 'card_number': f'CARD-{sequence:02d}', 'kind': kind, 'shop_name':shop['name'],
                'from': sender, 'to': receiver, 'device_id': j['device_id'], 'device': j['device'],
                'brand': device.get('brand',''), 'model': device.get('model',''), 'serial': j['serial'],
                'device_type': (self.db.one('SELECT name FROM masters WHERE id=?',(j['category_id'],)) or {}).get('name','Not specified'),
                'requested_service': (self.db.one('SELECT name FROM masters WHERE id=?',(j['service_id'],)) or {}).get('name','Not specified'),
                'complaint': j['complaint'], 'condition': p.get('condition',j['damage']),
                'items': items if items is not None else self.db.rows('SELECT id,type,description,quantity,serial,condition,notes FROM items WHERE job_id=?', (job_id,)),
                'visit': (self.db.one('SELECT number FROM visits WHERE id=?', (j['visit_id'],)) or {}).get('number', j['intake_ref']),
                'initial_estimate': j['initial_estimate'], 'advance_at_intake': self.db.one("""SELECT -COALESCE(sum(amount),0) n
                    FROM entries WHERE account_type='customer' AND job_id=? AND kind='receipt' AND notes='Intake advance'""", (job_id,))['n'],
                'customer_requirement': j['customer_requirement'],
                'intake_warranty': json.loads(j['lifecycle_data']).get('intake_warranty', {}),
                'device_photo_references': [r['id'] for r in self.db.rows("SELECT id FROM attachments WHERE device_id=? AND kind='product_photo'", (j['device_id'],))],
                'effective': stamp, 'completed': stamp, 'status': 'Completed', 'staff': self.s.user['name'],
                'expected_return': j['return_due'], 'reference': p.get('reference',assignment.get('reference','')),
                'notes': p.get('notes',''), 'acknowledgment': p.get('acknowledgment',''), 'movement_ids': p.get('movement_ids',[])}
            snapshot['final_destination']=p.get('final_destination','')
            snapshot['current_custodian']=receiver['name']
            snapshot['custody_status']='IN TRANSIT' if receiver.get('location')=='transit' else 'Received by '+receiver['name']
            if kind=='in_house_assignment':snapshot['custody_status']='Assignment only; physical handover recorded separately'
            if kind in ('third_party_return','service_center_return'):
                snapshot['return_details']=self.return_details(j,p)
            if kind=='part_transfer':snapshot['stock_movement_id']=p['stock_movement_id']
            # Never copy a whole customer/job/attachment record to an external card.
            ident = insert(c, 'job_cards', job_id=job_id, sequence=sequence, kind=kind, event_key=event_key,
                from_name=sender['name'], to_name=receiver['name'], effective=stamp, created=stamp,
                actor=self.s.user['id'], snapshot=json.dumps(snapshot))
            self.s.audit(c,'job',job_id,'job_card_created',{'card':f'CARD-{sequence:02d}','type':kind,'from':sender['name'],'to':receiver['name']})
            return ident

    def print(self, card_id, internal=False, paper=None):
        from .documents import Documents
        from .lifecycle import local_time
        self.s.require('owner','counter')
        if internal:self.s.require('owner')
        card = self.db.one('SELECT * FROM job_cards WHERE id=?',(card_id,))
        if not card:
            raise RuleError('Select a job card.')
        p=json.loads(card['snapshot'])
        if not internal:
            from .inventory import public_values
            p=public_values(p)
        def party(v):
            return '\n'.join(str(x) for k,x in v.items() if k!='id' and x)
        from .domain import rupees
        sections=[('Repair job',f"Job: {p['master_job']}\nVisit: {p.get('visit') or 'Not recorded'}\nCard: {p['card_number']}"),
            ('From',party(p['from'])),('To',party(p['to'])),('Device',f"DEV-{p['device_id']:06d} · {p['device']}\nType: {p.get('device_type','Not specified')} · Service: {p.get('requested_service','Not specified')}\nBrand: {p['brand'] or 'Not recorded'} · Model: {p['model'] or 'Not recorded'}\nSerial / IMEI: {p['serial'] or 'Not recorded'}"),
            ('Complaint and condition',p['complaint']+'\n'+p['condition']),
            ('Items handed over',[{k:r.get(k,'') for k in ('description','quantity','serial','condition')} for r in p['items']]),
            ('Receipt details',f"Effective: {local_time(p['effective'])} IST\nReceived / recorded by: {p['staff']}\nExpected return: {p['expected_return'] or 'Not specified'}\nReference: {p['reference'] or 'Not recorded'}\nAcknowledgment: {p['acknowledgment'] or 'Not recorded'}\nDevice photo references: {', '.join(str(i) for i in p['device_photo_references']) or 'None at issue time'}\n{p['notes']}")]
        if p.get('initial_estimate') is not None:
            warranty=p.get('intake_warranty') or {}
            sections.append(('Initial estimate given at collection',
                'Initial estimate: ' + rupees(p['initial_estimate'])
                + '\nAdvance received at intake: ' + rupees(p.get('advance_at_intake') or 0)
                + '\nThis is the estimate given when the product was received. It is not the final '
                'repair quotation; chargeable repair is quoted after diagnosis and started only '
                'after recorded customer approval.'))
            if p.get('customer_requirement'):
                sections.append(('Additional customer requirement',p['customer_requirement']))
            if warranty:
                sections.append(('Warranty reported at collection',
                    'Status: ' + str(warranty.get('status','Not recorded'))
                    + '\nExpiry: ' + str(warranty.get('expiry') or 'Not recorded')
                    + '\nProvider: ' + str(warranty.get('provider') or 'Not recorded')))
        if p.get('current_custodian'):
            sections.append(('Physical custody',f"Custodian: {p['current_custodian']}\n{p['custody_status']}\nFinal destination: {p.get('final_destination') or 'Direct handover'}"))
        if p.get('return_details'):
            r=p['return_details']
            sections.append(('Repair result', '\n'.join(k.replace('_',' ').title()+': '+str(r.get(k) or 'Not recorded') for k in ('result','repair_status','repairer','repairer_contact','work_performed','diagnosis','parts_reported','vendor_invoice','service_reference','claim_number','condition','receiver','acknowledgment','notes'))))
            sections.append(('Installed parts',[{'part':x['name'],'source':x['source']+' / '+x['supplier'],'quantity':x['quantity'],'serial':x['serial'],'warranty':f"{x['warranty_duration']} {x['warranty_unit']} · {x['warranty_provider']}" if x['warranty_duration'] else 'Not recorded'} for x in r['parts_installed']]))
            warranty_lines=[]
            for title,values in [('Warranty',r['warranty_decision']),('Replacement',r['replacement'])]:
                if values:warranty_lines.append(title+'\n'+'\n'.join(k.replace('_',' ').title()+': '+str(value) for k,value in values.items() if value not in (None,'')))
            sections.append(('Warranty / replacement result','\n\n'.join(warranty_lines) or 'No manufacturer warranty or replacement result recorded.'))
            if internal:
                from .domain import rupees
                sections.append(('INTERNAL COPY · repair costs',[dict(component=k.replace('_',' ').title(),amount=rupees(v)) for k,v in r['costs'].items() if k in ('stock_parts','supplier_parts','other_parts','vendor_parts','vendor_labour','in_house_cost','transport_cost','other_cost','service_center_charge','total_internal')]))
        path=Documents(self.s).snapshot(('INTERNAL COPY · ' if internal else '')+p['kind'].replace('_',' ').title()+' · '+p['master_job']+' / '+p['card_number'],sections,card['job_id'],shop_name=p.get('shop_name'),paper=paper)
        with self.db.transaction() as c:
            self.s.audit(c,'job',card['job_id'],'job_card_printed',{'card_id':card_id,'card':p['card_number']})
        return path
