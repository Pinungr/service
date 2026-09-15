"""Physical handovers over the existing holdings/movements ledger."""
import uuid
from .domain import RuleError, now, in_shop, staff_custody, sql_in_shop


class DeviceCustody:
    def __init__(self,service):self.s,self.db=service,service.db

    def technician(self,c,j,data,p,returning=False):
        self.s.require_permission('handover')
        if j['route']!='in_house':raise RuleError('This handover requires the in-house route.')
        a=self.db.one("SELECT a.*,COALESCE(tm.name,u.name) name FROM assignments a LEFT JOIN users u ON u.id=a.technician_id LEFT JOIN masters tm ON tm.id=a.technician_master_id WHERE a.id=?",(j['assignment_id'],))
        if not a:raise RuleError('Assign a technician first.')
        if not p.get('condition') or not p.get('acknowledgment'):raise RuleError('Record the physical condition and handover acknowledgment.')
        tech_location='technician:master-'+str(a['technician_master_id']) if a.get('technician_master_id') else 'technician:'+str(a['technician_id'])
        # A device coming back from the bench returns to the person recording the return.
        destination=self.s.receiving_custody() if returning else tech_location
        rows=self.db.rows('SELECT i.*,h.quantity held,h.location FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND h.quantity>0',(j['id'],))
        rows=[h for h in rows if h['location']==tech_location] if returning else [h for h in rows if in_shop(h['location'])]
        if 'items' in p:rows=[h for h in rows if h['id'] in p['items']]
        if not any(h['type']=='device' for h in rows):raise RuleError('Include the physical device currently held by this sender.')
        # Different shop bins are separate actual handovers and therefore cards.
        origins=sorted({h['location'] for h in rows})
        from .job_cards import JobCards
        for origin in origins:
            items=[h for h in rows if h['location']==origin];movements=[]
            for h in items:
                movements.append(self.s.move(h['id'],h['held'],origin,destination,p.get('counterparty') or (self.s.user['name'] if returning else a['name']),uuid.uuid4().hex,
                    condition=p['condition'],acknowledgment=p['acknowledgment'],notes=p.get('notes','')))
            JobCards(self.s).issue(j['id'],'in_house_return' if returning else 'in_house_handover','movement:'+str(movements[0]),dict(p,movement_ids=movements),
                [dict(description=h['description'],quantity=h['held'],serial=h['serial'],condition=p['condition']) for h in items])
        if returning:data['technician_returned']=now()
        else:
            if not p.get('bench','').strip():raise RuleError('Record the technician work area / bench.')
            data['technician_bench']=p['bench'];data['technician_handed']=now()

    def handover(self,c,j,data,p):
        """Hand the product to another authorized person inside the shop.

        This is a physical transfer only: it never changes who the repair is assigned to,
        because being responsible for a repair and actually holding the product are
        different things. The previous custodian stays in the ledger.
        """
        self.s.require_permission('handover')
        target=p.get('to_user_id')
        person=self.db.one('SELECT id,name,role FROM users WHERE id=? AND active=1',(target,))
        if not person:
            raise RuleError('Choose an active member of staff to hand the product to.')
        if not p.get('condition') or not p.get('acknowledgment'):
            raise RuleError('Record the physical condition and handover acknowledgment.')
        destination=staff_custody(person['id'])
        rows=[h for h in self.db.rows('''SELECT i.*,h.quantity held,h.location FROM items i
            JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND h.quantity>0''',(j['id'],))
            if in_shop(h['location']) and h['location']!=destination]
        if 'items' in p:rows=[h for h in rows if h['id'] in p['items']]
        if not any(h['type']=='device' for h in rows):
            raise RuleError('The product is not currently held by anyone in the shop.')
        from .job_cards import JobCards
        for origin in sorted({h['location'] for h in rows}):
            items=[h for h in rows if h['location']==origin];movements=[]
            for h in items:
                movements.append(self.s.move(h['id'],h['held'],origin,destination,person['name'],uuid.uuid4().hex,
                    condition=p['condition'],acknowledgment=p['acknowledgment'],
                    notes=p.get('notes','') or 'Internal handover'))
            JobCards(self.s).issue(j['id'],'in_house_handover','movement:'+str(movements[0]),
                dict(p,movement_ids=movements),
                [dict(description=h['description'],quantity=h['held'],serial=h['serial'],condition=p['condition']) for h in items])
        self.s.audit(c,'job',j['id'],'custody_handed_over',
            {'to_user_id':person['id'],'to':person['name'],'role':person['role'],
             'by':self.s.user['name'],'reason':p.get('notes','') or 'Internal handover'})
        data['custodian_handed']=now()

    def external(self,c,j,data,v,action,p):
        self.s.require_permission('handover')
        if not p.get('counterparty') or not p.get('condition') or not p.get('acknowledgment'):
            raise RuleError('Record the receiving person, condition and handover acknowledgment.')
        party=v['assignment'].get('party')
        destination=('centre:' if j['route']=='warranty_centre' else 'vendor:')+(party or '')
        final=party or '';stage=j['stage']
        if action=='dispatch':
            manifest=data.get('dispatch',{})
            if not manifest:raise RuleError('Create the dispatch record first.')
            rows=[h for h in v['holdings'] if h['id'] in manifest['items'] and in_shop(h['location'])]
            if not any(h['type']=='device' for h in rows):raise RuleError('The selected device is no longer at the shop; review dispatch.')
            carrier=p.get('carrier','').strip()
            if carrier:destination='transit:'+carrier
            data['transit_direction']='outbound';data['transit_destination']=party
            data['dispatched']=now();stage='external_diagnosis'
            from .dispatch import Dispatches
            data['dispatch_id']=Dispatches(self.s).confirm(c,j,data['dispatched'])
        elif action=='arrive':
            if data.get('transit_direction')=='return':raise RuleError('This courier is returning to the shop. Record shop receipt.')
            rows=[h for h in v['holdings'] if h['location'].startswith('transit:')]
            stage='external_diagnosis'
        elif action=='return_dispatch':
            carrier=p.get('carrier','').strip()
            if not carrier:raise RuleError('Identify the courier receiving the returned device.')
            rows=[h for h in v['holdings'] if h['location'].startswith(('vendor:','centre:'))]
            destination='transit:'+carrier;final=self.db.setting('shop_name','Repair shop')
            data['transit_direction']='return';data['transit_destination']=final
        elif action=='receive':
            rows=[h for h in v['holdings'] if h['location'].startswith(('centre:','vendor:','transit:'))]
            if not c.execute("SELECT 1 FROM job_cards WHERE job_id=? AND kind IN ('third_party_dispatch','service_center_dispatch','carrier_dispatch')",(j['id'],)).fetchone() and not data.get('legacy_review'):
                raise RuleError('An outbound Job Card is required before a return can be recorded.')
            if not rows or not c.execute("SELECT 1 FROM movements m JOIN items i ON i.id=m.item_id WHERE i.job_id=? AND "+sql_in_shop('m.from_location')+" AND (m.to_location LIKE 'vendor:%' OR m.to_location LIKE 'centre:%' OR m.to_location LIKE 'transit:%')",(j['id'],)).fetchone():raise RuleError('Only a previously dispatched device can be received from a repairer.')
            # The signed-in person receiving the item from the repairer becomes its custodian.
            destination=self.s.receiving_custody();final=self.db.setting('shop_name','Repair shop')
            # The returned items are checked against the outbound manifest before custody
            # moves. A missing item must be reported, never silently ticked off.
            if not p.get('skip_verification'):
                from .returns import Returns
                counts={h['id']:p.get('quantities',{}).get(str(h['id']),h['quantity']) for h in rows}
                if 'items' in p:counts={k:v for k,v in counts.items() if k in set(p['items'])}
                p['verification_id']=Returns(self.s).verify(j['id'],counts,
                    p.get('operation_id') or 'receive:'+str(j['id'])+':'+now(),
                    notes=p.get('notes',''),discrepancies=p.get('discrepancies',()))
            result=p.get('repair_result')
            if result and result not in ('REPAIRED','PARTIALLY REPAIRED','NOT REPAIRABLE','REPAIR DECLINED','RETURNED WITHOUT REPAIR','REPLACED'):raise RuleError('Select a supported repair return result.')
            if result in ('REPAIRED','REPLACED') and data.get('unrepaired'):raise RuleError('This job records a declined or unsuccessful repair. Resolve that outcome before reporting a repaired return.')
            if result=='REPLACED' and not data.get('replacement'):raise RuleError('Record the replacement device and its serial before reporting a replacement return.')
            if result in ('NOT REPAIRABLE','REPAIR DECLINED','RETURNED WITHOUT REPAIR','PARTIALLY REPAIRED'):
                data['unrepaired']=result+': '+p.get('notes','')
            if p.get('work_performed'):data['repair_summary']=p['work_performed']
            data['return_result']=result or ('RETURNED WITHOUT REPAIR' if data.get('unrepaired') else 'REPAIRED' if data.get('repair_completed') else 'NOT RECORDED')
            data['returned']=now();stage='final_qc'
        else:raise RuleError('Unknown external handover.')
        if 'items' in p:rows=[h for h in rows if h['id'] in p['items']]
        if not rows:raise RuleError('No matching items are available for this handover.')
        if action in ('dispatch','return_dispatch') and not any(h['type']=='device' for h in rows):raise RuleError('Include the physical device in this dispatch.')
        from .job_cards import JobCards
        prefix='service_center_' if j['route']=='warranty_centre' else 'third_party_'
        kind='carrier_dispatch' if action=='dispatch' and destination.startswith('transit:') else 'carrier_return_pickup' if action=='return_dispatch' else prefix+('return' if action=='receive' else 'arrival' if action=='arrive' else 'dispatch')
        for origin in sorted({h['location'] for h in rows}):
            moves=[];items=[]
            for h in (h for h in rows if h['location']==origin):
                qty=p.get('quantities',{}).get(str(h['id']),h['quantity'])
                moves.append(self.s.move(h['id'],qty,origin,destination,p['counterparty'],uuid.uuid4().hex,reference=p.get('reference',''),condition=p['condition'],notes=p.get('notes',''),acknowledgment=p['acknowledgment']))
                items.append(dict(h,quantity=qty,condition=p['condition']))
            JobCards(self.s).issue(j['id'],kind,'movement:'+str(moves[0]),dict(p,movement_ids=moves,final_destination=final),items)
        data['in_transit']=bool(c.execute("SELECT 1 FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND i.type='device' AND h.quantity>0 AND h.location LIKE 'transit:%'",(j['id'],)).fetchone())
        if action=='receive':
            remaining=c.execute("SELECT 1 FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND i.type='device' AND h.quantity>0 AND NOT "+sql_in_shop('h.location')+" AND h.location NOT LIKE 'exception:%'",(j['id'],)).fetchone()
            if remaining:stage=j['stage'];data.pop('returned',None)
            else:
                from .dispatch import Dispatches
                Dispatches(self.s).close(c,j,'RETURNED')
        return stage
