"""Calendar warranties and separate future repair claims on stable devices."""
import calendar
from datetime import date,timedelta
from .domain import RuleError,now,day
from .persistence import insert


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
            r['effective_status']='EXPIRED' if r['status']=='ACTIVE' and r['expiry']<date.today().isoformat() else r['status']
        return rows

    def claims(self,device_id):
        self.s.require()
        return self.db.rows('SELECT c.*,j.number claim_job,o.number original_job,w.name part FROM warranty_claims c JOIN jobs j ON j.id=c.new_job_id JOIN jobs o ON o.id=c.original_job_id JOIN part_warranties w ON w.id=c.warranty_id WHERE c.device_id=? ORDER BY c.id DESC',(device_id,))

    def repair_warranty(self,job_id,name,start_date,duration,unit,provider,terms=''):
        self.s.require('owner','counter')
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

    def edit(self,warranty_id,reason,**values):
        self.s.require('owner')
        if not reason.strip() or not values or not set(values)<={'duration','unit','start_date','provider','terms','status','notes'}:
            raise RuleError('Record an edit reason and supported warranty details.')
        with self.db.transaction() as c:
            old=self.db.one('SELECT * FROM part_warranties WHERE id=?',(warranty_id,))
            if not old:
                raise RuleError('Warranty not found.')
            updated=dict(old,**values)
            if updated['status'] not in ('ACTIVE','VOID','CLAIMED','REPLACED') or not updated['provider'].strip():
                raise RuleError('Choose a valid warranty status and provider.')
            values['expiry']=warranty_expiry(updated['start_date'],updated['duration'],updated['unit'])
            c.execute('UPDATE part_warranties SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),warranty_id))
            self.s.audit(c,'job',old['job_id'],'warranty_edited',{'warranty_id':warranty_id,'previous':old,'changes':values,'reason':reason})

    def claim(self,new_job_id,warranty_id,complaint,override_reason=''):
        self.s.require('owner','counter')
        if not complaint.strip():
            raise RuleError('Record the warranty complaint.')
        with self.db.transaction() as c:
            j=self.s._job(c,new_job_id)
            w=self.db.one('SELECT * FROM part_warranties WHERE id=?',(warranty_id,))
            if not w or w['job_id']==new_job_id or w['device_id']!=j['device_id'] or j['stage'] in ('closed','collected'):
                raise RuleError('A warranty claim requires a new active job for the same physical device.')
            if w['status']!='ACTIVE':
                raise RuleError('Only an active, unclaimed warranty can start a claim.')
            if w['expiry']<date.today().isoformat():
                self.s.require('owner')
                if not override_reason.strip():
                    raise RuleError('This warranty expired. The owner must record an explicit override reason.')
            if c.execute('SELECT 1 FROM warranty_claims WHERE new_job_id=? AND warranty_id=?',(new_job_id,warranty_id)).fetchone():
                raise RuleError('This job already has a claim against that warranty.')
            ident=insert(c,'warranty_claims',new_job_id=new_job_id,original_job_id=w['job_id'],device_id=w['device_id'],part_id=w['part_id'],warranty_id=warranty_id,complaint=complaint,notes=override_reason,created=now(),actor=self.s.user['id'])
            c.execute("UPDATE part_warranties SET status='CLAIMED' WHERE id=?",(warranty_id,))
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
            c.execute('UPDATE warranty_claims SET status=?,resolution=?,replacement_part_id=? WHERE id=?',(status,resolution,replacement_part_id,claim_id))
            if status=='REPLACED':
                c.execute("UPDATE part_warranties SET status='REPLACED' WHERE id=?",(old['warranty_id'],))
            if status=='REJECTED' or status=='COMPLETED' and not replacement_part_id:
                c.execute("UPDATE part_warranties SET status='ACTIVE' WHERE id=?",(old['warranty_id'],))
            self.s.audit(c,'job',old['new_job_id'],'warranty_claim_updated',{'claim_id':claim_id,'previous_status':old['status'],'status':status,'resolution':resolution,'replacement_part_id':replacement_part_id})
