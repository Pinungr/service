"""Owner-only repair budgets. Customer prices come from versioned quotations."""
import json
from .domain import RuleError


class JobCosts:
    FIELDS=('vendor_labour','transport_cost','other_cost','service_center_charge','in_house_cost')

    def __init__(self,service):self.s,self.db=service,service.db

    def save(self,job_id,values,reason):
        self.s.require_permission('view_internal_cost')
        if not reason.strip() or not set(values)<=set(self.FIELDS)|{'vendor_invoice'}:raise RuleError('Record a costing reference and supported cost fields.')
        if any(type(v)!=int or v<0 for k,v in values.items() if k in self.FIELDS):raise RuleError('Internal costs must be nonnegative whole paise.')
        with self.db.transaction() as c:
            j=self.s._job(c,job_id)
            if j['stage'] in ('closed','collected'):raise RuleError('Closed repair costing remains in history.')
            data=json.loads(j['lifecycle_data']);before=data.get('route_details',{}).copy()
            data.setdefault('route_details',{}).update(values)
            c.execute('UPDATE jobs SET lifecycle_data=?,version=version+1 WHERE id=?',(json.dumps(data),job_id))
            self.s.audit(c,'job',job_id,'internal_cost_updated',{'previous':before,'changes':values,'reason':reason})

    def summary(self,job_id):
        self.s.require_permission('view_internal_cost')
        self.s.require_job_access(job_id)
        return self._summary(job_id)

    def _summary(self,job_id):
        j=self.s.job(job_id);d=json.loads(j['lifecycle_data']).get('route_details',{})
        parts=self.db.rows("SELECT * FROM repair_parts WHERE job_id=? AND status!='removed'",(job_id,))
        buckets={source:sum(p['purchase_cost']*p['quantity'] for p in parts if p['source']==source) for source in ('stock','supplier','technician','other')}
        vendor_parts=buckets['technician'] if any(p['source']=='technician' for p in parts) else d.get('vendor_parts',0)
        costs={k:d.get(k,0) for k in self.FIELDS}
        internal=sum(costs.values())+buckets['stock']+buckets['supplier']+buckets['other']+vendor_parts
        quote=self.db.one('SELECT * FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1',(job_id,)) or {}
        approved=self.db.one("SELECT q.total FROM quotes q JOIN decisions d ON d.quote_id=q.id WHERE q.job_id=? AND d.decision='approved' ORDER BY q.version DESC LIMIT 1",(job_id,))
        return dict(costs,stock_parts=buckets['stock'],supplier_parts=buckets['supplier'],other_parts=buckets['other'],vendor_parts=vendor_parts,
            total_internal=internal,vendor_total=costs['vendor_labour']+vendor_parts+costs['transport_cost']+costs['other_cost'],
            customer_total=quote.get('total'),expected_margin=quote['total']-internal if quote else None,quote_state=quote.get('state','Not issued'),
            previous_approved=approved['total'] if approved else None,vendor_invoice=d.get('vendor_invoice',''),
            legacy_parts_budget=d.get('vendor_parts',0),part_cost_basis='Structured parts replace a legacy vendor parts budget; it is not added twice.')
