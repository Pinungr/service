"""Structured parts, stock movements and customer-approved part revisions."""
import json
from .domain import RuleError, now, day
from .persistence import insert


class Parts:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def rows(self, job_id):
        self.s.require()
        return self.db.rows('SELECT p.*,w.expiry warranty_expiry,(p.customer_price-p.purchase_cost)*p.quantity margin FROM repair_parts p LEFT JOIN part_warranties w ON w.part_id=p.id WHERE p.job_id=? ORDER BY p.id',(job_id,))

    def stock(self):
        self.s.require()
        return self.db.rows('SELECT s.*,COALESCE(sum(m.delta),0) available FROM stock_items s LEFT JOIN stock_movements m ON m.stock_id=s.id GROUP BY s.id ORDER BY s.name')

    def stock_item(self, name, purchase_cost=0, customer_price=0, **fields):
        self.s.require('owner')
        if not name.strip() or any(type(v)!=int or v<0 for v in (purchase_cost,customer_price)) or not set(fields)<={'brand','model','part_number'}:
            raise RuleError('Enter a stock name and nonnegative prices in paise.')
        with self.db.transaction() as c:
            ident=insert(c,'stock_items',name=name.strip(),purchase_cost=purchase_cost,customer_price=customer_price,**fields)
            self.s.audit(c,'stock',ident,'stock_item_created',{'name':name})
            return ident

    def adjust_stock(self, stock_id, quantity, reference, notes=''):
        self.s.require('owner')
        if type(quantity)!=int or not quantity or not reference.strip():
            raise RuleError('Enter a nonzero whole quantity and purchase/correction reference.')
        with self.db.transaction() as c:
            if not c.execute('SELECT 1 FROM stock_items WHERE id=? AND active=1',(stock_id,)).fetchone():
                raise RuleError('Select an active stock item.')
            balance=c.execute('SELECT COALESCE(sum(delta),0) FROM stock_movements WHERE stock_id=?',(stock_id,)).fetchone()[0]
            if balance+quantity<0:
                raise RuleError('Stock cannot become negative.')
            ident=insert(c,'stock_movements',stock_id=stock_id,delta=quantity,reference=reference,notes=notes,created=now(),actor=self.s.user['id'])
            self.s.audit(c,'stock',stock_id,'stock_adjusted',{'quantity':quantity,'reference':reference,'notes':notes})
            return ident

    def save(self, job_id, values, part_id=None):
        self.s.require('owner','counter')
        defaults=dict(name='',part_type='',brand='',model='',part_number='',serial='',quantity=1,source='supplier',inventory_id=None,supplier_id=None,
            invoice='',purchase_date=None,purchase_cost=0,customer_price=0,warranty_duration=0,warranty_unit='months',warranty_provider='',warranty_terms='',notes='')
        if not set(values)<=set(defaults):
            raise RuleError('Unknown part field.')
        with self.db.transaction() as c:
            j=self.s._job(c,job_id)
            self._editable(j)
            old=self.db.one('SELECT * FROM repair_parts WHERE id=? AND job_id=?',(part_id,job_id)) if part_id else None
            if part_id and (not old or old['status']!='planned'):
                raise RuleError('Only an uninstalled planned part may be edited.')
            if old:
                defaults.update({k:old[k] for k in defaults})
            p=dict(defaults,**values)
            if not p['name'].strip() or p['source'] not in ('stock','supplier','technician','other'):
                raise RuleError('Enter the part name and source.')
            if any(type(p[k])!=int or p[k]<0 for k in ('purchase_cost','customer_price','warranty_duration')) or type(p['quantity'])!=int or p['quantity']<1:
                raise RuleError('Use a positive whole quantity and nonnegative whole-paise costs / warranty duration.')
            if p['serial'] and p['quantity']!=1:
                raise RuleError('Record each serialized part separately.')
            if p['warranty_unit'] not in ('days','months','years') or (p['warranty_duration'] and not p['warranty_provider'].strip()):
                raise RuleError('Select a warranty unit and identify its provider.')
            p['purchase_date']=day(p['purchase_date'])
            if p['source']=='stock':
                if not c.execute('SELECT 1 FROM stock_items WHERE id=? AND active=1',(p['inventory_id'],)).fetchone():
                    raise RuleError('Select the shop stock item.')
            else:
                p['inventory_id']=None
            supplier=c.execute("SELECT * FROM masters WHERE id=? AND kind IN ('vendor','supplier') AND active=1",(p['supplier_id'],)).fetchone()
            if p['source'] in ('supplier','technician') and not supplier:
                raise RuleError('Identify the supplier or supplying technician in the vendor/supplier directory.')
            if p['source']=='other' and not p['notes'].strip():
                raise RuleError('Explain the other part source in notes.')
            p['supplier_snapshot']=json.dumps(dict(supplier)) if supplier else ''
            if part_id:
                p['revision']=old['revision']+1
                c.execute('UPDATE repair_parts SET '+','.join(k+'=?' for k in p)+' WHERE id=?',(*p.values(),part_id))
            else:
                part_id=insert(c,'repair_parts',job_id=job_id,device_id=j['device_id'],created=now(),actor=self.s.user['id'],**p)
            self._revise(c,j)
            self.s.audit(c,'job',job_id,'part_planned' if not old else 'part_revised',{'part_id':part_id,'name':p['name'],'source':p['source'],'quantity':p['quantity'],'purchase_cost':p['purchase_cost'],'customer_price':p['customer_price']})
            return part_id

    def remove(self, part_id, reason):
        self.s.require('owner','counter')
        if not reason.strip():
            raise RuleError('Record why this planned part is removed.')
        with self.db.transaction() as c:
            p=self.db.one('SELECT * FROM repair_parts WHERE id=?',(part_id,))
            if not p or p['status']!='planned':
                raise RuleError('Installed parts remain in repair history and cannot be removed.')
            j=self.s._job(c,p['job_id']);self._editable(j)
            c.execute("UPDATE repair_parts SET status='removed',revision=revision+1 WHERE id=?",(part_id,))
            self._revise(c,j)
            self.s.audit(c,'job',j['id'],'part_removed',{'part_id':part_id,'reason':reason})

    @staticmethod
    def _editable(j):
        if j['stage'] in ('collected','closed','ready_repaired','ready_unrepaired'):
            raise RuleError('Use a new linked job after delivery; reopen diagnosis before changing parts on a ready device.')

    def _revise(self,c,j):
        # Issued amounts stay immutable; approval must explicitly cover the new version.
        quoted=c.execute('SELECT 1 FROM quotes WHERE job_id=?',(j['id'],)).fetchone()
        if quoted or j['stage'] in ('approved','under_repair','technician_testing','final_qc','testing','billing'):
            c.execute("UPDATE quotes SET state='superseded' WHERE job_id=? AND state IN ('issued','approved')",(j['id'],))
            c.execute("UPDATE jobs SET stage='awaiting_estimate',version=version+1 WHERE id=?",(j['id'],))
            data=json.loads(j['lifecycle_data'])
            for key in ('qc','billing_checked','notified'):
                data.pop(key,None)
            c.execute('UPDATE jobs SET lifecycle_data=? WHERE id=?',(json.dumps(data),j['id']))
        else:
            self.s._touch(c,j['id'])

    def quote_lines(self,job_id):
        return [dict(part_id=p['id'],revision=p['revision'],description=f"{p['name']} · {p['brand']} {p['model']} · Qty {p['quantity']} · Warranty {p['warranty_duration']} {p['warranty_unit']} ({p['warranty_provider']})",amount=p['quantity']*p['customer_price']) for p in self.rows(job_id) if p['status']!='removed']

    def validate_approval(self,c,j):
        parts=self.quote_lines(j['id'])
        if not parts:
            return
        q=c.execute('SELECT * FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1',(j['id'],)).fetchone()
        if not q or q['state']!='approved':
            raise RuleError('The parts and customer prices require an approved current estimate, including zero-charge warranty parts.')
        actual={x['part_id']:(x.get('revision'),x['amount']) for x in json.loads(q['lines']) if 'part_id' in x}
        if actual!={p['part_id']:(p['revision'],p['amount']) for p in parts}:
            raise RuleError('Parts changed. Issue a revised estimate and record customer approval.')

    def install(self,part_id,installed_by,installed_date=None):
        self.s.require()
        if not installed_by.strip():
            raise RuleError('Record who installed the part.')
        stamp=day(installed_date) if installed_date else now()[:10]
        if stamp>now()[:10]:
            raise RuleError('Installation cannot be in the future.')
        with self.db.transaction() as c:
            p=self.db.one('SELECT * FROM repair_parts WHERE id=?',(part_id,))
            if not p or p['status']!='planned':
                raise RuleError('Select an uninstalled planned part.')
            j=self.s._job(c,p['job_id'])
            if j['stage']!='under_repair':
                raise RuleError('Start the approved repair before recording parts installed.')
            self.s._authorize_repair(c,j)
            self.validate_approval(c,j)
            if p['source']=='stock':
                available=c.execute('SELECT COALESCE(sum(delta),0) FROM stock_movements WHERE stock_id=?',(p['inventory_id'],)).fetchone()[0]
                if available<p['quantity']:
                    raise RuleError('Insufficient shop stock. Receive stock or revise the part source first.')
                insert(c,'stock_movements',stock_id=p['inventory_id'],delta=-p['quantity'],part_id=part_id,job_id=j['id'],reference=j['number'],notes='Installed on device',created=now(),actor=self.s.user['id'])
            card=c.execute('SELECT id FROM job_cards WHERE job_id=? ORDER BY sequence DESC LIMIT 1',(j['id'],)).fetchone()
            q=c.execute('SELECT id FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1',(j['id'],)).fetchone()
            c.execute("UPDATE repair_parts SET status='installed',installed_by=?,installed_at=?,estimate_id=?,card_id=? WHERE id=?",(installed_by,stamp,q[0],card[0] if card else None,part_id))
            if p['warranty_duration']:
                from .warranties import warranty_expiry
                insert(c,'part_warranties',device_id=j['device_id'],job_id=j['id'],part_id=part_id,name=p['name'],installed_at=stamp,duration=p['warranty_duration'],unit=p['warranty_unit'],start_date=stamp,
                    expiry=warranty_expiry(stamp,p['warranty_duration'],p['warranty_unit']),source=p['source'],provider=p['warranty_provider'],terms=p['warranty_terms'],created=now(),actor=self.s.user['id'])
            self.s._touch(c,j['id'])
            self.s.audit(c,'job',j['id'],'part_installed',{'part_id':part_id,'name':p['name'],'installed_by':installed_by,'date':stamp})
