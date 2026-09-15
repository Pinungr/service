"""Calendar warranties and separate future repair claims on stable devices."""
import calendar
from datetime import date,timedelta
from .domain import RuleError,now,day
from .persistence import insert


def sale_warranty(sale, on=None):
    """Describe recorded sale dates, without granting repair coverage."""
    sale = dict(sale)
    today = on or date.today()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    start, expiry = sale.get('warranty_start'), sale.get('warranty_end')
    status = 'UNKNOWN'
    duration = None
    if expiry:
        end = date.fromisoformat(expiry)
        begin = date.fromisoformat(start) if start else None
        if begin and begin > end:
            status = 'UNKNOWN'
        elif end < today:
            status = 'EXPIRED'
        elif begin and begin > today:
            status = 'NOT_STARTED'
        else:
            status = 'VALID'
        if begin and end >= begin:
            duration = (end - begin).days
    return dict(source='shop', status=status, sale_id=sale['id'],
                sale_date=sale.get('sale_date'), start_date=start, expiry=expiry,
                provider=sale.get('provider', ''), terms=sale.get('warranty_terms', ''),
                duration_days=duration, checked_on=today.isoformat(),
                verification='sale_dates_only')


def reported_intake_warranty(values):
    """Validate a customer's report; it never substitutes for a verified claim."""
    allowed = {'source', 'status', 'expiry', 'provider', 'notes'}
    if not isinstance(values, dict) or not set(values) <= allowed:
        raise RuleError('Enter supported intake warranty details.')
    if values.get('source') != 'external' or values.get('status') not in ('VALID', 'EXPIRED', 'NONE', 'UNKNOWN'):
        raise RuleError('Choose the reported external warranty status.')
    result = dict(source='external', status=values['status'], expiry=None, provider='', notes='',
                  checked_on=date.today().isoformat(), verification='customer_reported')
    # Hidden valid-warranty fields must not leak into another status.
    if result['status'] == 'VALID':
        for key in ('provider', 'notes'):
            value = values.get(key) or ''
            if not isinstance(value, str):
                raise RuleError('Warranty provider and notes must be text.')
            result[key] = value.strip()
        try:
            result['expiry'] = date.fromisoformat(values['expiry']).isoformat() if values.get('expiry') else None
        except (ValueError, TypeError):
            raise RuleError('Enter a valid warranty expiry date.')
        if result['expiry'] and result['expiry'] < result['checked_on']:
            raise RuleError('This warranty expiry has passed. Choose Expired or correct the expiry date.')
    return result


def warranty_expiry(start,duration,unit):
    d=date.fromisoformat(start)
    if type(duration)!=int or duration<0 or unit not in ('days','months','years'):
        raise RuleError('Invalid warranty duration.')
    try:
        if unit=='days':
            return (d+timedelta(days=duration)).isoformat()
        months=d.year*12+d.month-1+duration*(12 if unit=='years' else 1)
        year,month=divmod(months,12);month+=1
        return date(year,month,min(d.day,calendar.monthrange(year,month)[1])).isoformat()
    except (ValueError,OverflowError):
        raise RuleError('Warranty expiry is outside the supported date range.')


class Warranties:
    def __init__(self,service):
        self.s,self.db=service,service.db

    def rows(self,device_id):
        self.s.require()
        rows=self.db.rows('SELECT w.*,j.number original_job FROM part_warranties w JOIN jobs j ON j.id=w.job_id WHERE w.device_id=? ORDER BY w.expiry DESC,w.id DESC',(device_id,))
        for r in rows:
            claim=self.active_claim(r['id'])
            r['claim_id']=claim['id'] if claim else None
            r['claim_state']=claim['status'] if claim else ''
            r['effective_status']='CLAIM IN PROGRESS' if claim else 'EXPIRED' if r['status']=='ACTIVE' and r['expiry']<date.today().isoformat() else r['status']
        return rows

    def active_claim(self,warranty_id):
        return self.db.one("SELECT * FROM warranty_claims WHERE warranty_id=? AND status!='CLOSED' ORDER BY id DESC LIMIT 1",(warranty_id,))

    def claims(self,device_id):
        self.s.require()
        return self.db.rows('SELECT c.*,j.number claim_job,o.number original_job,w.name part FROM warranty_claims c JOIN jobs j ON j.id=c.new_job_id JOIN jobs o ON o.id=c.original_job_id JOIN part_warranties w ON w.id=c.warranty_id WHERE c.device_id=? ORDER BY c.id DESC',(device_id,))

    def repair_warranty(self,job_id,name,start_date,duration,unit,provider,terms=''):
        self.s.require_permission('manage_warranty')
        if not name.strip() or not provider.strip() or duration<=0:
            raise RuleError('Enter repair warranty name, provider and positive duration.')
        expiry=warranty_expiry(start_date,duration,unit)
        with self.db.transaction() as c:
            j=self.s._job(c,job_id)
            if j['stage'] not in ('final_qc','billing','ready_repaired'):
                raise RuleError('Register a repair warranty after completed repair and testing.')
            ident=insert(c,'part_warranties',device_id=j['device_id'],job_id=job_id,name=name,installed_at=start_date,duration=duration,unit=unit,start_date=start_date,expiry=expiry,source='repair',provider=provider,terms=terms,created=now(),actor=self.s.user['id'])
            self.s.audit(c,'job',job_id,'repair_warranty_registered',{'warranty_id':ident,'name':name,'expiry':expiry,'provider':provider})
            return ident

    def edit(self,warranty_id,reason,privileged_override=False,**values):
        self.s.require('owner')
        if not reason.strip() or not values or not set(values)<={'duration','unit','start_date','provider','terms','status','notes'}:
            raise RuleError('Record an edit reason and supported warranty details.')
        with self.db.transaction() as c:
            old=self.db.one('SELECT * FROM part_warranties WHERE id=?',(warranty_id,))
            if not old:
                raise RuleError('Warranty not found.')
            claim=self.active_claim(warranty_id)
            if claim and not privileged_override:
                raise RuleError(f"WARRANTY STATUS MANAGED BY ACTIVE CLAIM WC-{claim['id']:06d} ({claim['status']}). Use the claim workflow or the dedicated owner override.")
            updated=dict(old,**values)
            if updated['status'] not in ('ACTIVE','VOID','REPLACED') or not updated['provider'].strip():
                raise RuleError('Choose a valid warranty status and provider.')
            values['expiry']=warranty_expiry(updated['start_date'],updated['duration'],updated['unit'])
            c.execute('UPDATE part_warranties SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),warranty_id))
            self.s.audit(c,'job',old['job_id'],'warranty_admin_override' if privileged_override else 'warranty_edited',{'warranty_id':warranty_id,'previous':old,'changes':values,'reason':reason,'active_claim':claim['id'] if claim else None})

    def claim(self,new_job_id,warranty_id,complaint,override_reason=''):
        self.s.require_permission('manage_warranty')
        if not complaint.strip():
            raise RuleError('Record the warranty complaint.')
        with self.db.transaction() as c:
            j=self.s._job(c,new_job_id)
            w=self.db.one('SELECT * FROM part_warranties WHERE id=?',(warranty_id,))
            if not w or w['job_id']==new_job_id or w['device_id']!=j['device_id'] or j['stage'] in ('closed','collected'):
                raise RuleError('A warranty claim requires a new active job for the same physical device.')
            if w['status']!='ACTIVE' or self.active_claim(warranty_id):
                raise RuleError('Only an active, unclaimed warranty can start a claim.')
            if w['expiry']<date.today().isoformat():
                self.s.require('owner')
                if not override_reason.strip():
                    raise RuleError('This warranty expired. The owner must record an explicit override reason.')
            if c.execute('SELECT 1 FROM warranty_claims WHERE new_job_id=? AND warranty_id=?',(new_job_id,warranty_id)).fetchone():
                raise RuleError('This job already has a claim against that warranty.')
            ident=insert(c,'warranty_claims',new_job_id=new_job_id,original_job_id=w['job_id'],device_id=w['device_id'],part_id=w['part_id'],warranty_id=warranty_id,complaint=complaint,notes=override_reason,original_status=w['status'],created=now(),actor=self.s.user['id'])
            self.s._touch(c,new_job_id)
            self.s.audit(c,'job',new_job_id,'warranty_claim_opened',{'claim_id':ident,'original_job':w['job_id'],'part_id':w['part_id'],'warranty_id':warranty_id,'complaint':complaint,'override_reason':override_reason})
            return ident

    def update_claim(self,claim_id,status,resolution, replacement_part_id=None):
        self.s.require('owner','counter')
        transitions={'OPEN':{'ACCEPTED','REJECTED'},'ACCEPTED':{'IN_REPAIR','REJECTED'},'IN_REPAIR':{'REPLACED','COMPLETED'},'REPLACED':{'COMPLETED'},'COMPLETED':{'CLOSED'},'REJECTED':{'CLOSED'},'CLOSED':set()}
        with self.db.transaction() as c:
            old=self.db.one('SELECT * FROM warranty_claims WHERE id=?',(claim_id,))
            if not old or status not in transitions[old['status']] or not resolution.strip():
                raise RuleError('Choose the next claim status and record the decision or resolution.')
            j=self.s._job(c,old['new_job_id'])
            if status=='CLOSED' and j['stage'] not in ('collected','closed'):
                raise RuleError('Deliver the device before closing its warranty claim.')
            replacement_part_id=replacement_part_id or old['replacement_part_id']
            if status=='REPLACED' and not c.execute("SELECT 1 FROM repair_parts WHERE id=? AND job_id=? AND device_id=? AND status='installed'",(replacement_part_id,old['new_job_id'],old['device_id'])).fetchone():
                raise RuleError('Select the replacement part installed on this claim job.')
            c.execute('UPDATE warranty_claims SET status=?,resolution=?,replacement_part_id=?,outcome=? WHERE id=?',(status,resolution,replacement_part_id,status if status in ('REJECTED','REPLACED','COMPLETED') else old['outcome'],claim_id))
            if status=='REPLACED':
                c.execute("UPDATE part_warranties SET status='REPLACED' WHERE id=?",(old['warranty_id'],))
            # Opening a claim no longer overwrites the base warranty state. A
            # rejection/completion therefore preserves an explicit admin void.
            self.s.audit(c,'job',old['new_job_id'],'warranty_claim_updated',{'claim_id':claim_id,'previous_status':old['status'],'status':status,'resolution':resolution,'replacement_part_id':replacement_part_id})

    def manual_checks(self,job_id):
        self.s.require()
        with self.db.read() as c:self.s._job(c,job_id)
        return self.db.rows('SELECT m.*,u.name checked_by FROM manual_warranty_checks m JOIN users u ON u.id=m.actor WHERE job_id=? ORDER BY m.id DESC',(job_id,))

    def manual_check(self,job_id,result,evidence_type,reference,provider,coverage,notes,attachment_id=None):
        self.s.require_permission('manage_warranty')
        if result not in ('VALID','INVALID','UNVERIFIED') or coverage not in ('manufacturer','shop_part','shop_repair','supplier','vendor'):
            raise RuleError('Select a verification result and warranty coverage.')
        if evidence_type not in ('Shop invoice','Warranty slip','Supplier invoice','Manufacturer warranty','Vendor confirmation','Other'):
            raise RuleError('Select the evidence type.')
        if not notes.strip() or (result=='VALID' and (not reference.strip() or not provider.strip())):
            raise RuleError('Record verification notes; accepted warranty needs its evidence reference and provider.')
        with self.db.transaction() as c:
            j=self.s._job(c,job_id)
            if j['stage'] in ('collected','closed'):raise RuleError('Use a new intake for warranty service after delivery.')
            if attachment_id and not c.execute('SELECT 1 FROM attachments WHERE id=? AND (job_id=? OR device_id=?)',(attachment_id,job_id,j['device_id'])).fetchone():raise RuleError('Select evidence attached to this job or device.')
            ident=insert(c,'manual_warranty_checks',job_id=job_id,device_id=j['device_id'],result=result,evidence_type=evidence_type,reference=reference,
                provider=provider,coverage=coverage,notes=notes,attachment_id=attachment_id,checked_at=now(),actor=self.s.user['id'])
            import json
            data=json.loads(j['lifecycle_data']);data['manual_warranty_check']=ident
            data['manual_warranty_result']=result;data['manual_warranty_coverage']=coverage
            if j['stage']=='warranty_check' and result=='VALID':
                data['warranty_status']='under_warranty' if coverage=='manufacturer' else 'shop_warranty'
                c.execute("UPDATE jobs SET stage='route_selection' WHERE id=?",(job_id,))
            c.execute('UPDATE jobs SET lifecycle_data=?,version=version+1 WHERE id=?',(json.dumps(data),job_id))
            self.s.audit(c,'job',job_id,'manual_warranty_verified',{'check_id':ident,'result':result,'evidence_type':evidence_type,'reference':reference,'provider':provider,'coverage':coverage,'notes':notes,'attachment_id':attachment_id})
            return ident
