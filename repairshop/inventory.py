"""Inventory catalog and immutable stock ledger shared with repair parts.

Owned stock includes reserved and issued units until installation. Availability is
owned minus reservations and issues; physical transfers do not consume ownership.
"""
import json
import uuid
from .domain import RuleError, now, day
from .persistence import insert


PRIVATE_FIELDS={'purchase_cost','margin','markup_basis_points','internal_cost','vendor_parts','vendor_labour',
    'transport_cost','other_cost','service_center_charge','in_house_cost','total_internal','vendor_total','expected_margin','costs','estimated_parts','estimated_labour',
    'cost','estimate','stock_parts','supplier_parts','other_parts','legacy_parts_budget'}


def public_values(value):
    if isinstance(value,dict):
        out={}
        for k,v in value.items():
            if k in PRIVATE_FIELDS:continue
            if k in ('snapshot','payload','lifecycle_data') and isinstance(v,str):
                try:v=json.dumps(public_values(json.loads(v)))
                except (ValueError,TypeError):pass
            out[k]=public_values(v)
        return out
    if isinstance(value,list):return [public_values(v) for v in value]
    return value


class Inventory:
    def __init__(self,service):self.s,self.db=service,service.db

    def rows(self,search='',view='all'):
        self.s.require()
        rows=self.db.rows('''SELECT s.*,m.name supplier,COALESCE(b.stock,0) stock,
            COALESCE(b.reserved,0) reserved,COALESCE(b.issued,0) issued,
            COALESCE(b.stock-b.reserved-b.issued,0) available,(s.customer_price-s.purchase_cost) margin
            FROM stock_items s LEFT JOIN masters m ON m.id=s.supplier_id LEFT JOIN
            (SELECT stock_id,sum(delta) stock,sum(reserved_delta) reserved,sum(issued_delta) issued
             FROM stock_movements GROUP BY stock_id) b ON b.stock_id=s.id ORDER BY s.name,s.id''')
        term=search.casefold().strip()
        rows=[r for r in rows if not term or term in ' '.join(str(r.get(k) or '') for k in ('name','sku','brand','model','part_number','compatibility','supplier','serial','batch')).casefold()]
        if view=='low':rows=[r for r in rows if r['active'] and r['available']<=r['minimum_stock']]
        if view=='out':rows=[r for r in rows if r['active'] and r['available']==0]
        for r in rows:
            r['warranty']=f"{r['warranty_duration']} {r['warranty_unit']}" if r['warranty_duration'] else 'Not recorded'
        return rows if self.s.may('view_internal_cost') else public_values(rows)

    def balance(self,c,ident):
        r=c.execute('SELECT COALESCE(sum(delta),0),COALESCE(sum(reserved_delta),0),COALESCE(sum(issued_delta),0) FROM stock_movements WHERE stock_id=?',(ident,)).fetchone()
        return dict(stock=r[0],reserved=r[1],issued=r[2],available=r[0]-r[1]-r[2])

    def save(self,values,ident=None):
        self.s.require_permission('manage_inventory')
        defaults=dict(name='',sku='',category_id=None,brand='',model='',compatibility='',part_number='',serialized=False,serial='',batch='',
            purchase_cost=0,customer_price=0,supplier_id=None,invoice='',purchase_date=None,storage='Stock shelf',minimum_stock=0,
            warranty_duration=0,warranty_unit='months',warranty_provider='',warranty_terms='',markup_basis_points=None,notes='',active=True)
        if not set(values)<=set(defaults):raise RuleError('Unknown inventory field.')
        with self.db.transaction() as c:
            old=self.db.one('SELECT * FROM stock_items WHERE id=?',(ident,)) if ident else None
            if ident and not old:raise RuleError('Inventory item not found.')
            if old:defaults.update({k:old[k] for k in defaults})
            p=dict(defaults,**values)
            if not p['name'].strip():raise RuleError('Enter a part name.')
            if not p['sku'].strip():p['sku']='STK-'+uuid.uuid4().hex[:10].upper()
            p['sku']=p['sku'].strip()
            if c.execute('SELECT 1 FROM stock_items WHERE sku=? COLLATE NOCASE AND id!=?',(p['sku'],ident or 0)).fetchone():raise RuleError('This SKU already exists.')
            for key in ('purchase_cost','customer_price','minimum_stock','warranty_duration'):
                if type(p[key])!=int or p[key]<0:raise RuleError('Prices, minimum stock and warranty duration must be nonnegative whole values.')
            markup=p['markup_basis_points']
            if markup is not None:
                if type(markup)!=int or markup<0:raise RuleError('Markup must be a nonnegative percentage.')
                if 'customer_price' not in values:p['customer_price']=(p['purchase_cost']*(10000+markup)+5000)//10000
            if p['warranty_unit'] not in ('days','months','years') or (p['warranty_duration'] and not p['warranty_provider'].strip()):raise RuleError('Identify the warranty unit and provider, or use zero duration for no recorded warranty.')
            if p['serialized'] and not p['serial'].strip():raise RuleError('Enter the serial for an individually serialized stock unit.')
            if p['serialized'] and c.execute('SELECT 1 FROM stock_items WHERE serialized=1 AND serial=? COLLATE NOCASE AND id!=?',(p['serial'],ident or 0)).fetchone():raise RuleError('This inventory serial already exists.')
            if old and (old['serialized']!=p['serialized'] or old['serial']!=p['serial']) and c.execute('SELECT 1 FROM stock_movements WHERE stock_id=?',(ident,)).fetchone():raise RuleError('Keep the serial identity after stock movements; create a separate item for a different serial.')
            if p['category_id'] and not c.execute("SELECT 1 FROM masters WHERE id=? AND kind='category' AND active=1",(p['category_id'],)).fetchone():raise RuleError('Select an active product category.')
            if p['supplier_id'] and not c.execute("SELECT 1 FROM masters WHERE id=? AND kind IN ('supplier','vendor') AND active=1",(p['supplier_id'],)).fetchone():raise RuleError('Select an active supplier.')
            if not p['storage'].strip():raise RuleError('Enter the stock shelf / bin.')
            p['purchase_date']=day(p['purchase_date'])
            if old:
                if not p['active'] and any(self.balance(c,ident)[k] for k in ('reserved','issued')):raise RuleError('Return or release committed stock before deactivating it.')
                c.execute('UPDATE stock_items SET '+','.join(k+'=?' for k in p)+' WHERE id=?',(*p.values(),ident))
            else:ident=insert(c,'stock_items',**p)
            self.s.audit(c,'stock',ident,'inventory_updated' if old else 'stock_item_created',{'previous':old,'values':p})
            return ident

    def _movement(self,c,stock,kind,quantity,delta=0,reserved=0,issued=0,part=None,source='',destination='',reference='',reason='',notes='',party_id=None,technician_id=None,technician_master_id=None,operation_id=None):
        if type(quantity)!=int or quantity<1:raise RuleError('Enter a positive whole stock quantity.')
        balance=self.balance(c,stock['id'])
        result=dict(stock=balance['stock']+delta,reserved=balance['reserved']+reserved,issued=balance['issued']+issued)
        if min(result.values())<0 or result['stock']<result['reserved']+result['issued']:raise RuleError('Insufficient available stock. Stock, reservations and issues cannot become negative.')
        if stock['serialized'] and (quantity!=1 or result['stock']>1):raise RuleError('Serialized inventory holds one unit per serial.')
        stamp=now();job_id=part['job_id'] if part else None
        snapshot={k:stock[k] for k in ('name','sku','serial','purchase_cost','customer_price','supplier_id','invoice','purchase_date','warranty_duration','warranty_unit','warranty_provider','warranty_terms')}
        snapshot['supplier']=(self.db.one('SELECT name FROM masters WHERE id=?',(stock['supplier_id'],)) or {}).get('name','Not recorded')
        if part:
            for key in ('name','serial','purchase_cost','customer_price','supplier_id','warranty_duration','warranty_unit','warranty_provider','warranty_terms'):snapshot[key]=part[key]
            snapshot['supplier']=json.loads(part.get('supplier_snapshot') or '{}').get('name',snapshot['supplier'])
        ident=insert(c,'stock_movements',stock_id=stock['id'],kind=kind,quantity=quantity,delta=delta,reserved_delta=reserved,issued_delta=issued,
            part_id=part['id'] if part else None,job_id=job_id,from_location=source,to_location=destination,party_id=party_id,technician_id=technician_id,technician_master_id=technician_master_id,
            reference=reference,reason=reason,notes=notes,snapshot=json.dumps(snapshot),operation_id=operation_id or uuid.uuid4().hex,created=stamp,actor=self.s.user['id'])
        evidence=dict(movement_id=ident,inventory_id=stock['id'],part_id=part['id'] if part else None,part=stock['name'],quantity=quantity,kind=kind,
            from_location=source,to_location=destination,reference=reference,reason=reason,notes=notes)
        self.s.audit(c,'stock',stock['id'],'stock_movement',evidence)
        if job_id:self.s.audit(c,'job',job_id,'stock_movement',evidence)
        return ident

    def adjust(self,stock_id,quantity,reference,notes='',kind=None,operation_id=None):
        self.s.require_permission('manage_inventory')
        if type(quantity)!=int or not quantity or not reference.strip():raise RuleError('Enter a nonzero whole quantity and purchase/correction reference.')
        if kind is None:kind='STOCK_RECEIVED' if quantity>0 else 'STOCK_ADJUSTMENT'
        if kind not in ('STOCK_RECEIVED','STOCK_ADJUSTMENT','DAMAGED','SCRAPPED','WARRANTY_REPLACEMENT','CUSTOMER_RETURN'):raise RuleError('Select a supported stock movement.')
        if kind in ('DAMAGED','SCRAPPED') and quantity>0:raise RuleError('Loss movements reduce stock.')
        if kind in ('STOCK_RECEIVED','WARRANTY_REPLACEMENT','CUSTOMER_RETURN') and quantity<0:raise RuleError('Receipt movements add stock.')
        with self.db.transaction() as c:
            if operation_id:
                old=c.execute('SELECT * FROM stock_movements WHERE operation_id=?',(operation_id,)).fetchone()
                if old:
                    if old['stock_id']!=stock_id or old['delta']!=quantity or old['reference']!=reference:raise RuleError('This stock operation reference was already used for a different receipt.')
                    return old['id']
            stock=self.db.one('SELECT * FROM stock_items WHERE id=? AND active=1',(stock_id,))
            if not stock:raise RuleError('Select an active stock item.')
            if stock['serialized'] and quantity>0 and kind!='CUSTOMER_RETURN' and c.execute("SELECT 1 FROM stock_movements WHERE stock_id=? AND kind='INSTALLED'",(stock_id,)).fetchone():
                raise RuleError('This serial was already installed. Use a new stock item for a replacement serial, or an explicit customer return for the same physical part.')
            return self._movement(c,stock,kind,abs(quantity),delta=quantity,source='Supplier / adjustment' if quantity>0 else 'stock:'+stock['storage'],
                destination='stock:'+stock['storage'] if quantity>0 else kind,reference=reference,reason=reference,notes=notes,operation_id=operation_id)

    def transfer(self,part_id,action,reference,notes=''):
        self.s.require_permission('manage_inventory')
        if not reference.strip():raise RuleError('Record the handover acknowledgment or reservation reference.')
        with self.db.transaction() as c:
            p=self.db.one('SELECT * FROM repair_parts WHERE id=?',(part_id,))
            if not p or p['source']!='stock' or p['status']!='planned':raise RuleError('Select a planned shop-stock part.')
            j=self.s._job(c,p['job_id'])
            from .parts import Parts
            Parts._editable(j)
            stock=self.db.one('SELECT * FROM stock_items WHERE id=? AND active=1',(p['inventory_id'],))
            if not stock:raise RuleError('Select an active inventory item.')
            qty=p['quantity'];state=p['stock_state'];kwargs={};destination='stock:'+stock['storage'];source=p['stock_location'] or destination
            if action=='reserve':
                if state not in ('none','returned'):raise RuleError('This part is already reserved or issued.')
                kind='RESERVED_FOR_JOB';newstate='reserved';kwargs['reserved']=qty
            elif action=='issue':
                if state!='reserved':raise RuleError('Reserve this part before issuing it.')
                a=self.db.one("SELECT a.*,m.name party,COALESCE(tm.name,u.name) technician FROM assignments a LEFT JOIN masters m ON m.id=a.contact_id LEFT JOIN users u ON u.id=a.technician_id LEFT JOIN masters tm ON tm.id=a.technician_master_id WHERE a.id=?",(j['assignment_id'],)) or {}
                if j['route']=='in_house':
                    if not (a.get('technician_master_id') or a.get('technician_id')):raise RuleError('Assign a technician before issuing stock.')
                    if a.get('technician_master_id'):
                        destination='technician:master-'+str(a['technician_master_id']);kwargs['technician_master_id']=a['technician_master_id']
                    else:
                        destination='technician:'+str(a['technician_id']);kwargs['technician_id']=a['technician_id']
                    kind='ISSUED_TO_TECHNICIAN'
                elif j['route']=='third_party':
                    if not a.get('contact_id'):raise RuleError('Assign the third-party repairer before issuing stock.')
                    destination='vendor:'+a['party'];kwargs['party_id']=a['contact_id'];kind='ISSUED_TO_VENDOR'
                else:raise RuleError('Shop stock may be issued to an in-house technician or the assigned third-party repairer.')
                newstate='issued';kwargs.update(reserved=-qty,issued=qty)
            elif action in ('release','return'):
                if action=='release' and state!='reserved' or action=='return' and state!='issued':raise RuleError('Select a matching reserved or issued part.')
                kind='RETURNED_UNUSED' if action=='return' else 'RESERVATION_RELEASED';newstate='returned'
                kwargs['reserved' if state=='reserved' else 'issued']=-qty
            elif action in ('damaged','scrapped'):
                self.s.require_permission('manage_inventory')
                if state not in ('reserved','issued'):raise RuleError('Select the reserved or issued stock being written off.')
                kind=action.upper();newstate='returned';kwargs.update(delta=-qty)
                kwargs['reserved' if state=='reserved' else 'issued']=-qty;destination=kind
            else:raise RuleError('Unknown stock transfer.')
            movement=self._movement(c,stock,kind,qty,part=p,source=source,destination=destination,reference=reference,reason=reference,notes=notes,**kwargs)
            c.execute('UPDATE repair_parts SET stock_state=?,stock_location=? WHERE id=?',(newstate,destination,p['id']))
            self.s._touch(c,j['id'])
            if action in ('issue','return'):
                from .job_cards import JobCards
                JobCards(self.s).issue(j['id'],'part_transfer','stock:'+str(movement),{'stock_movement_id':movement,'reference':reference,'acknowledgment':reference,'notes':notes},
                    [dict(description=p['name'],quantity=qty,serial=p['serial'],condition='See acknowledgment')])
            return movement

    def installed(self,c,p):
        stock=self.db.one('SELECT * FROM stock_items WHERE id=?',(p['inventory_id'],))
        if self.balance(c,stock['id'])['stock']<p['quantity']:raise RuleError('Insufficient shop stock.')
        if p['stock_state']!='issued':raise RuleError('Reserve the stock and record its physical issue to the repairer before installation.')
        self._movement(c,stock,'INSTALLED',p['quantity'],delta=-p['quantity'],issued=-p['quantity'],part=p,
            source=p['stock_location'],destination='device:'+str(p['device_id']),reference='Installed part #'+str(p['id']),reason='Installed in device')
        c.execute("UPDATE repair_parts SET stock_state='installed',stock_location=? WHERE id=?",('device:'+str(p['device_id']),p['id']))

    def movements(self,stock_id=None,job_id=None):
        self.s.require()
        rows=self.db.rows('''SELECT m.*,s.name part,s.sku,u.name staff,j.number job FROM stock_movements m JOIN stock_items s ON s.id=m.stock_id
            JOIN users u ON u.id=m.actor LEFT JOIN jobs j ON j.id=m.job_id WHERE (? IS NULL OR m.stock_id=?) AND (? IS NULL OR m.job_id=?) ORDER BY m.id DESC''',(stock_id,stock_id,job_id,job_id))
        if not self.s.may('view_internal_cost'):
            for r in rows:r['snapshot']=json.dumps(public_values(json.loads(r['snapshot'])))
        for r in rows:
            snapshot=json.loads(r['snapshot']);r['supplier']=snapshot.get('supplier','Legacy: not recorded');r['invoice']=snapshot.get('invoice','');r['purchase_date']=snapshot.get('purchase_date')
            if self.s.may('view_internal_cost'):r['purchase_cost']=snapshot.get('purchase_cost')
        return rows
