from PyQt6.QtWidgets import QWidget,QVBoxLayout,QLabel
from .costing import JobCosts
from .ui_widgets import Grid,Form,button
from .domain import money,rupees


class CostPanel(QWidget):
    def __init__(self,workspace):
        super().__init__();self.ws=workspace;self.costs=JobCosts(workspace.window.s)
        layout=QVBoxLayout(self);self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.grid=Grid();layout.addWidget(self.grid,1)
        self.edit_button=button('Record vendor labour / internal expenses',lambda:workspace.support(self.edit));layout.addWidget(self.edit_button)
        self.edit_button.setEnabled(not workspace.window.db.readonly)
        hint=QLabel('Part costs come from the Parts tab. Vendor labour, transport and other costs are separate. This is an internal budget; posted vendor bills and payments remain in Vendor accounts. Customer quotations use selling prices.');hint.setWordWrap(True);layout.addWidget(hint)

    def reload(self):
        self.data=self.costs.summary(self.ws.ident);d=self.data
        self.summary.setText('INTERNAL COSTING · OWNER ONLY\nTotal internal cost: '+rupees(d['total_internal'])+'\nCustomer estimate: '+(rupees(d['customer_total']) if d['customer_total'] is not None else 'Not issued')+' · '+d['quote_state']+'\nExpected margin: '+(rupees(d['expected_margin']) if d['expected_margin'] is not None else 'Issue customer estimate first')+'\nPrevious approved amount: '+(rupees(d['previous_approved']) if d['previous_approved'] is not None else 'Not approved'))
        self.grid.fill([{'component':k.replace('_',' ').title(),'amount':rupees(d[k])} for k in ('stock_parts','supplier_parts','vendor_parts','other_parts','in_house_cost','vendor_labour','service_center_charge','transport_cost','other_cost')],['component','amount'])

    def edit(self):
        d=Form('Internal repair budget',self,'Record labour separately. Record each supplied part and its purchase cost in the Parts tab; those costs are included automatically.')
        for k in JobCosts.FIELDS:d.text(k,k.replace('_',' ').title()+' (INR)',str(self.data[k]/100))
        d.text('vendor_invoice','Vendor invoice',self.data['vendor_invoice']);d.text('reason','Budget / invoice reference and reason',multiline=True)
        def save(p):
            reason=p.pop('reason')
            for k in JobCosts.FIELDS:p[k]=money(p[k])
            self.costs.save(self.ws.ident,p,reason)
        d.submit(save)
