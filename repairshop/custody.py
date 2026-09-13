"""Physical handovers over the existing holdings/movements ledger."""
import uuid
from .domain import RuleError,now


class DeviceCustody:
    def __init__(self,service):self.s,self.db=service,service.db

    def technician(self,c,j,data,p,returning=False):
        self.s.require('owner','counter')
        if j['route']!='in_house':raise RuleError('This handover requires the in-house route.')
        a=self.db.one('SELECT a.*,u.name FROM assignments a JOIN users u ON u.id=a.technician_id WHERE a.id=?',(j['assignment_id'],))
        if not a:raise RuleError('Assign a technician first.')
        if not p.get('condition') or not p.get('acknowledgment'):raise RuleError('Record the physical condition and handover acknowledgment.')
        destination=p.get('storage','shop:QC Area') if returning else 'technician:'+str(a['technician_id'])
        if returning and (not destination.startswith('shop:') or not destination[5:].strip()):raise RuleError('Choose the shop QC / storage destination.')
        rows=self.db.rows('SELECT i.*,h.quantity held,h.location FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND h.quantity>0',(j['id'],))
        rows=[h for h in rows if h['location']=='technician:'+str(a['technician_id'])] if returning else [h for h in rows if h['location'].startswith('shop:')]
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

    def external(self,c,j,data,v,action,p):
        self.s.require('owner','counter')
        if not p.get('counterparty') or not p.get('condition') or not p.get('acknowledgment'):
            raise RuleError('Record the receiving person, condition and handover acknowledgment.')
        party=v['assignment'].get('party')
        destination=('centre:' if j['route']=='warranty_centre' else 'vendor:')+(party or '')
        final=party or '';stage=j['stage']
        if action=='dispatch':
            manifest=data.get('dispatch',{})
            if not manifest:raise RuleError('Create the dispatch record first.')
            rows=[h for h in v['holdings'] if h['id'] in manifest['items'] and h['location'].startswith('shop:')]
            if not any(h['type']=='device' for h in rows):raise RuleError('The selected device is no longer at the shop; review dispatch.')
            carrier=p.get('carrier','').strip()
            if carrier:destination='transit:'+carrier
            data['transit_direction']='outbound';data['transit_destination']=party
            data['dispatched']=now();stage='external_diagnosis'
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
            if not rows or not c.execute("SELECT 1 FROM movements m JOIN items i ON i.id=m.item_id WHERE i.job_id=? AND m.from_location LIKE 'shop:%' AND (m.to_location LIKE 'vendor:%' OR m.to_location LIKE 'centre:%' OR m.to_location LIKE 'transit:%')",(j['id'],)).fetchone():raise RuleError('Only a previously dispatched device can be received from a repairer.')
            destination=p.get('storage','shop:Front desk');final=self.db.setting('shop_name','Repair shop')
            if not destination.startswith('shop:') or not destination[5:].strip():raise RuleError('Choose a shop storage location for the return.')
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
            remaining=c.execute("SELECT 1 FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND i.type='device' AND h.quantity>0 AND h.location NOT LIKE 'shop:%' AND h.location NOT LIKE 'exception:%'",(j['id'],)).fetchone()
            if remaining:stage=j['stage'];data.pop('returned',None)
        return stage
