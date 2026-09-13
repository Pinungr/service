"""Counter-friendly views and dialogs; all transition decisions live in Lifecycle."""
import json
import uuid
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QScrollArea,QTabWidget,QCheckBox,QMessageBox,QDialogButtonBox,QSpinBox)
from .ui_widgets import Form,Grid,button,MasterSelector,panel,FlowLayout
from .lifecycle import Lifecycle,ACTIONS,ROUTE_LABELS,local_time
from .domain import rupees,money,RuleError
from .customer_ui import DevicePhotos,show_photo

COLUMNS=['number','customer','device','visit','route','current_card','status','location','current_custodian','final_destination','responsible','pending_since','expected_date','estimate','balance','warranty_indicator','next_action']


def label(text, large=False):
    w=QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    if large:
        w.setStyleSheet('font-size:18px;font-weight:750;color:#102a43;padding:4px;background:transparent')
    return w


class JobWorkspace(QDialog):
    def __init__(self,window,ident):
        super().__init__(window)
        self.window,self.ident=window,ident
        self.life=Lifecycle(window.s)
        self.resize(1220,840)
        self.setMinimumSize(860,560)
        shell=QVBoxLayout(self);shell.setContentsMargins(0,0,0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True);shell.addWidget(scroll)
        content=QWidget();scroll.setWidget(content)
        outer=QVBoxLayout(content)
        outer.setContentsMargins(18,18,18,16)
        outer.setSpacing(12)
        self.heading=label('',True)
        outer.addWidget(self.heading)
        self.metrics=QGridLayout()
        self.metrics.setHorizontalSpacing(12)
        self.metrics.setVerticalSpacing(12)
        self.values={}
        for n,(key,title) in enumerate([('route_label','REPAIR ROUTE'),('current_status','REPAIR STATUS'),('current_location','PHYSICAL LOCATION'),('current_custodian','CURRENT CUSTODIAN'),('final_destination','FINAL DESTINATION'),('assigned_technician','ASSIGNED TECHNICIAN')]):
            box=QWidget(); box.setObjectName('card'); layout=QVBoxLayout(box);layout.setContentsMargins(14,12,14,12);layout.setSpacing(4)
            title_label=label(title);title_label.setObjectName('muted')
            layout.addWidget(title_label); self.values[key]=label('',True); layout.addWidget(self.values[key])
            self.metrics.addWidget(box,n//3,n%3)
        outer.addLayout(self.metrics)
        nextrow=QHBoxLayout()
        next_card,next_layout=panel('Next action')
        self.next=label('',True); next_layout.addWidget(self.next)
        nextrow.addWidget(next_card,1)
        self.primary=button('Continue',lambda:self.act(self.view['primary']),True)
        nextrow.addWidget(self.primary)
        outer.addLayout(nextrow)
        self.attention=label(''); self.attention.setStyleSheet('color:#9b4521;font-weight:600')
        outer.addWidget(self.attention)
        body=QHBoxLayout()
        tracker_scroll=QScrollArea();tracker_scroll.setWidgetResizable(True);tracker_scroll.setFixedWidth(215)
        self.tracker=label(''); self.tracker.setStyleSheet('font-size:14px;padding:10px;line-height:1.8')
        tracker_scroll.setWidget(self.tracker);body.addWidget(tracker_scroll)
        self.tabs=QTabWidget();body.addWidget(self.tabs,1);outer.addLayout(body,1)
        route_scroll=QScrollArea();route_scroll.setWidgetResizable(True)
        route=QWidget();route_layout=QVBoxLayout(route)
        self.buttons=FlowLayout();route_layout.addLayout(self.buttons)
        self.summary=label('');route_layout.addWidget(self.summary);route_layout.addStretch()
        route_scroll.setWidget(route);self.tabs.addTab(route_scroll,'Repair workspace')
        j=window.s.job(ident)
        if j['device_id']:
            self.tabs.addTab(DevicePhotos(window,j['device_id'],ident),'Device photos')
        self.timeline=Grid();self.tabs.addTab(self.timeline,'Repair timeline')
        self.custody=Grid();self.tabs.addTab(self.custody,'Items and location')
        from .parts_ui import RepairRecords
        self.record_tabs=[]
        for kind,title in [('cards','Job Cards'),('parts','Parts'),('warranty','Warranty')]:
            tab=RepairRecords(self,kind);self.record_tabs.append(tab)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(tab);self.tabs.addTab(scroll,title)
        self.cost_panel=None
        if window.s.user['role']=='owner':
            from .costing_ui import CostPanel
            self.cost_panel=CostPanel(self);self.tabs.addTab(self.cost_panel,'Internal costing')
        footer=FlowLayout()
        for text,fn in [('Full records',lambda:window.job_records(ident)),('Same visit',lambda:window.visit_jobs(ident)),('Documents',lambda:window.document_form(ident)),('Expected dates',lambda:window.date_form(ident)),('Hold / release',lambda:window.hold_form(ident))]:
            b=button(text,lambda checked=False,f=fn:self.support(f));footer.addWidget(b)
            b.setEnabled(not window.db.readonly or text=='Full records')
        footer.addWidget(button('Close window',self.accept));outer.addLayout(footer)
        self.reload()

    def support(self,fn):
        self.window.safe(fn)
        self.reload()

    def reload(self):
        self.view=self.life.snapshot(self.ident);v=self.view
        self.setWindowTitle(v['number']+' · Repair lifecycle')
        self.heading.setText(f"{v['number']}  ·  {v['device']}\n{v['customer']}  ·  {v['phone']}  ·  DEV-{v['device_id']:06d}  ·  Serial: {v['serial'] or 'Not recorded'}" if v['device_id'] else f"{v['number']} · {v['device']} · {v['customer']}")
        for key,w in self.values.items():
            w.setText(str(v[key] or '—').replace('_',' '))
        self.next.setText(v['next_action'])
        self.primary.setText(ACTIONS.get(v['primary'],'Review history'))
        self.primary.setEnabled(bool(v['primary']) and not self.window.db.readonly)
        self.attention.setText('ATTENTION: '+' · '.join(v['attention']) if v['attention'] else '')
        self.tracker.setText('REPAIR LIFECYCLE\n\n'+'\n\n'.join(r['state']+'  '+r['step'] for r in v['tracker'])+ ('\n\nLegacy steps are not assumed complete.' if not v['lifecycle_version'] or v['data'].get('legacy_review') else ''))
        d=v['data'];a=v['assignment'];quote=v['quote']
        lines=[('Responsible for work',v['responsible']),('Pending since',v['pending_since']),('Warranty route',v['warranty_status']),('Reported fault',v['complaint']),('Intake condition',v['damage']),('Confirmed diagnosis',d.get('diagnosis')),
            ('Repair performed',d.get('repair_summary')),('Parts required',d.get('parts_required')),('Parts availability','Available' if d.get('parts_available') else 'Pending' if 'parts_available' in d else 'Not recorded'),
            ('Parts used',d.get('parts_used')),('Assigned technician',a.get('technician')),('Repairer',a.get('party')),('Repairer contact',a.get('contact')),('Repairer details',a.get('details')),
            ('Dispatch date',local_time(d.get('dispatched'))),('Expected return',v['return_due']),('Expected collection',v['collection_due']),('Returned to shop',local_time(d.get('returned'))),
            ('Customer estimate',rupees(quote.get('total')) if quote else 'Not issued'),('Approval',quote.get('state','Not recorded')),('Advance / payments retained',rupees(v['paid'])),('Balance due',rupees(v['balance'])),
            ('Repair started',local_time(d.get('repair_started'))),('Repair completed',local_time(d.get('repair_completed'))),('QC result',d.get('qc',{}).get('result','Pending')),
            ('Repair warranty',d.get('repair_warranty')),('Warranty until',d.get('warranty_until')),('Unrepaired outcome',d.get('unrepaired'))]
        details=d.get('route_details',{})
        from .inventory import PRIVATE_FIELDS
        lines += [(k.replace('_',' ').title(),val) for k,val in details.items() if k not in PRIVATE_FIELDS|{'customer_price'}]
        self.summary.setText('\n'.join(f'{k}: {val if val not in (None,"") else "Not recorded"}' for k,val in lines))
        while self.buttons.count():
            item=self.buttons.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        actions=v['actions'][:]
        for index,action in enumerate(actions):
            b=button(ACTIONS[action],lambda checked=False,a=action:self.act(a))
            b.setEnabled(not self.window.db.readonly)
            self.buttons.addWidget(b)
        if self.window.s.user['role']=='owner' and v['route']!='in_house':
            self.buttons.addWidget(button('Vendor invoice / payment',lambda:self.support(lambda:self.payment('vendor'))))
        self.timeline.fill(v['timeline'],['time','event','actor','details'])
        self.custody.fill(v['holdings'],['description','type','serial','location','quantity'])
        self.heading.setText(self.heading.text()+'\nCurrent card: '+v['current_card']+'  ·  '+v['warranty_indicator'])
        for tab in self.record_tabs:tab.reload()
        if self.cost_panel:self.cost_panel.reload()

    def act(self,action):
        if not action:return
        self.window.safe(lambda:self._act(action))
        self.reload()

    def _act(self,action):
        v=self.life.snapshot(self.ident)
        if action=='parts':
            self.tabs.setCurrentIndex(next(i for i in range(self.tabs.count()) if self.tabs.tabText(i)=='Parts'));return
        if action=='manual_warranty':
            tab=next(t for t in self.record_tabs if t.kind=='warranty');self.tabs.setCurrentIndex(next(i for i in range(self.tabs.count()) if self.tabs.tabText(i)=='Warranty'));tab.manual_warranty();return
        if action=='costing':
            self.tabs.setCurrentWidget(self.cost_panel);return
        if action=='claim':
            self.tabs.setCurrentIndex(next(i for i in range(self.tabs.count()) if self.tabs.tabText(i)=='Warranty'))
            return
        if action=='quote':return self.window.quote_form(self.ident)
        if action=='decision':return self.window.decision_form(v['quote'])
        if action=='payment':return self.payment('customer')
        if action in ('select_route','change_route'):return self.route_choice(action,v)
        if action=='qc':return self.qc(v)
        if action=='handover':return self.handover(v)
        d=Form(ACTIONS[action],self,v['next_action'])
        if action=='adopt':
            d.check('confirmed','I reviewed the saved status, location, quotation and history')
            d.text('notes','Review findings / reason',multiline=True)
        elif action=='verify_warranty':
            d.select('warranty_status','Warranty status',[('Unknown / requires verification','unknown'),('Under manufacturer warranty','under_warranty'),('Out of warranty','out_of_warranty')])
            d.text('notes','Purchase proof / warranty dates / verification notes',multiline=True)
        elif action=='prepare_dispatch':
            d.text('condition','Device condition at dispatch',v['damage'],multiline=True)
            d.date('expected_return','Expected return date',v['return_due'])
            d.text('reference','Service center job / vendor ticket number')
            d.text('carrier','Courier / transport information')
            checks=[]
            for h in v['holdings']:
                if h['location'].startswith('shop:'):
                    box=QCheckBox(h['description']+f" · {h['quantity']} unit(s)")
                    box.setChecked(h['type']=='device');d.layout.addRow('Send item',box);checks.append((h['id'],box))
            d.check('consent','Customer consent to dispatch and assessment recorded',v['assessment_consent'])
            d.text('notes','Dispatch notes',multiline=True)
            return d.submit(lambda p:self.life.execute(self.ident,action,dict(p,items=[i for i,w in checks if w.isChecked()]),v['version']))
        elif action in ('hand_technician','return_technician'):
            d.text('condition','Device condition',v['damage'],multiline=True)
            d.text('acknowledgment','Physical handover acknowledgment')
            if action=='hand_technician':d.text('bench','Technician work area / bench',v['data'].get('technician_bench',''))
            else:d.select('storage','Shop QC / storage',[('QC Area','shop:QC Area')]+[(r['name'],'shop:'+r['name']) for r in self.window.s.masters('storage')],'shop:QC Area')
            d.text('notes','Handover notes',multiline=True)
        elif action in ('dispatch','arrive','receive','return_dispatch'):
            manifest=v['data'].get('dispatch',{})
            d.layout.addRow(label('Current custodian: '+v['current_custodian']+'\nDestination: '+(v['final_destination'] or v['assignment'].get('party') or 'Shop')))
            d.text('counterparty','Person receiving the items')
            d.text('condition','Condition at handover',manifest.get('condition',''),multiline=True)
            d.text('reference','Tracking / external job reference',manifest.get('reference',''))
            d.text('acknowledgment','Acknowledgment / receipt reference',multiline=True)
            if action in ('dispatch','return_dispatch'):d.text('carrier','Carrier (blank = direct handover)' if action=='dispatch' else 'Courier receiving the return',manifest.get('carrier','') if action=='dispatch' else '')
            if action=='receive':d.select('storage','Shop storage',[('Shop: '+r['name'],'shop:'+r['name']) for r in self.window.s.masters('storage')])
            d.text('notes','Notes',multiline=True)
            if action=='receive':
                d.select('repair_result','Repair result',[('Use recorded repair outcome',None)]+[(x,x) for x in ('REPAIRED','PARTIALLY REPAIRED','NOT REPAIRABLE','REPAIR DECLINED','RETURNED WITHOUT REPAIR','REPLACED')])
                d.text('work_performed','Work performed',v['data'].get('repair_summary',''),multiline=True)
                d.text('parts_reported','Parts / replacements reported by repairer',v['data'].get('parts_used',''),multiline=True)
                d.text('vendor_invoice','Vendor / service center invoice',v['data'].get('route_details',{}).get('vendor_invoice',''))
                controls=[]
                for h in v['holdings']:
                    if h['location'].startswith(('centre:','vendor:','transit:')):
                        quantity=QSpinBox();quantity.setRange(0,h['quantity']);quantity.setValue(h['quantity'])
                        d.layout.addRow(h['description']+' · returning units',quantity);controls.append((h['id'],quantity))
                return d.submit(lambda p:self.life.execute(self.ident,action,dict(p,items=[i for i,w in controls if w.value()],quantities={str(i):w.value() for i,w in controls}),v['version']))
        elif action=='diagnose':
            d.text('notes','Confirmed fault / diagnosis',multiline=True)
            d.check('repairable','Device is repairable',True)
            d.text('parts','Required parts',multiline=True)
            d.check('parts_available','Required parts available',True)
        elif action=='warranty_result':
            d.select('decision','Service center decision',['pending','accepted','rejected','partial'])
            for key,title in [('rma','Claim / RMA number'),('notes','Findings / rejection reason'),('covered','Covered work'),('excluded','Excluded work'),('terms','Warranty evidence / terms')]:d.text(key,title,multiline=key!='rma')
        elif action in ('complete_repair','replacement'):
            d.text('notes','Repair performed / replacement evidence',multiline=True)
            d.text('parts','Parts used',multiline=True)
            if action=='replacement':
                d.text('description','Replacement device');d.text('serial','New serial number');d.text('terms','Replacement warranty',multiline=True)
        elif action=='test':
            d.select('result','Technician test result',[('Passed','passed'),('Failed — re-diagnose','failed')])
            d.text('notes','Test observations',multiline=True)
        elif action in ('decline','repair_failed'):
            d.select('reason','Outcome',['Customer declined repair','Not repairable','Repair failed','Cancelled'])
            d.text('notes','Reason and customer conversation',multiline=True)
        elif action=='bill':
            d.layout.addRow(label('QC: '+v['data'].get('qc',{}).get('result','Pending')))
            d.layout.addRow(label('Estimate: '+rupees(v['quote'].get('total'))+'\nAdvance / retained payments: '+rupees(v['paid'])+'\nPosted balance: '+rupees(v['balance'])))
            d.check('confirmed','Charges and advances reviewed; issue the applicable bill and mark ready')
            d.layout.addRow(label('A positive balance remains payable at collection. Returning without repair uses only the agreed return charges.'))
        elif action=='details':
            details=v['data'].get('route_details',{})
            if v['data'].get('legacy_review'):
                d.select('warranty_status','Verified legacy warranty status',[('Unknown','unknown'),('Under warranty','under_warranty'),('Out of warranty','out_of_warranty')],v['warranty_status'])
            if v['route']!='in_house':
                for key,title in [('external_reference','Service center / vendor job number'),('claim_number','Warranty claim number'),('contact_person','Contact person'),('address','Address'),('phone','Phone'),('specialization','Brand / specialization'),('transport','Courier / transport'),('vendor_status','External repair status')]:
                    d.text(key,title,details.get(key,''))
                d.date('expected_return','Expected return',v['return_due'])
                if self.window.s.user['role']=='owner':
                    for k,title in [('vendor_parts','Vendor parts cost'),('vendor_labour','Vendor labour cost'),('transport_cost','Transport cost'),('other_cost','Other cost'),('customer_price','Proposed customer price')]:
                        d.text(k,title+' (INR)',str(details.get(k,0)/100))
            elif self.window.s.user['role']=='owner':
                d.text('estimated_parts','Estimated parts cost (INR)',details.get('estimated_parts',''))
                d.text('estimated_labour','Estimated labour cost (INR)',details.get('estimated_labour',''))
            d.text('notes','Progress notes',details.get('notes',''),multiline=True)
        elif action=='resolve_item':
            rows=[h for h in v['holdings'] if h['location']!='customer' and not h['location'].startswith('exception:')]
            d.select('selection','Outstanding item',[(h['description']+' · '+h['location'],index) for index,h in enumerate(rows)])
            d.text('quantity','Units to resolve','1')
            d.text('counterparty','Responsible party / person authorizing resolution')
            d.text('reference','Evidence reference')
            d.text('notes','Owner explanation (lost, retained, replacement or other resolution)',multiline=True)
            def resolve(p):
                index=p.pop('selection')
                if index is None:raise RuleError('Select an outstanding item.')
                h=rows[index]
                self.life.execute(self.ident,action,dict(p,item_id=h['id'],source=h['location'],quantity=int(p['quantity'])),v['version'])
            return d.submit(resolve)
        elif action=='notify':
            d.layout.addRow(label('Queues an update using existing consent and channel settings. Sending is subject to the configured provider; the Messages screen shows delivery status.'))
        elif action=='close':
            d.layout.addRow(label('The delivered job and its full history will remain accessible in Repair History.'))
        elif action!='inspect' and action!='start_repair':
            d.text('notes','Findings / notes',multiline=True)
        def save(p):
            for key in ('vendor_parts','vendor_labour','transport_cost','other_cost','customer_price'):
                if key in p:p[key]=money(p[key])
            self.life.execute(self.ident,action,p,v['version'])
        return d.submit(save)

    def route_choice(self,action,v):
        d=QDialog(self);d.setWindowTitle('Choose repair route');d.resize(620,430)
        layout=QVBoxLayout(d)
        layout.addWidget(label('HOW WILL THIS DEVICE BE REPAIRED?',True))
        layout.addWidget(label('Warranty: '+v['warranty_status'].replace('_',' ')))
        def choose(route):
            f=Form(ROUTE_LABELS[route],d,'Assign responsibility here. Physical location changes only when you record an actual handover.')
            if route!='in_house':f.add('contact_id','Service center' if route=='warranty_centre' else 'Vendor / technician',MasterSelector(self.window.s,'centre' if route=='warranty_centre' else 'vendor'))
            else:
                f.select('technician_id','Assigned technician',[(r['name'],r['id']) for r in self.window.db.rows('SELECT id,name FROM users WHERE active=1')])
                handed=f.check('handed_over','Device physically handed to this technician now',False)
                for key,title in [('bench','Technician work area / bench'),('condition','Condition at handover'),('acknowledgment','Physical handover acknowledgment')]:
                    field=f.text(key,title);field.setEnabled(False);handed.toggled.connect(field.setEnabled)
            f.text('reference','Assignment reference')
            f.check('confirmed','Confirm this repair route and responsible party')
            if f.submit(lambda p:self.life.execute(self.ident,action,dict(p,route=route),v['version'])):d.accept()
        for route,title in [('warranty_centre','SEND TO AUTHORIZED SERVICE CENTER'),('in_house','REPAIR IN OUR SHOP'),('third_party','SEND TO THIRD-PARTY TECHNICIAN')]:
            b=button(title,lambda checked=False,r=route:choose(r),True);b.setMinimumHeight(68)
            under=v['warranty_status']=='under_warranty'
            b.setEnabled((route=='warranty_centre' and under) or (route!='warranty_centre' and (not under or v['warranty'].get('decision') in ('rejected','partial'))))
            layout.addWidget(b)
        layout.addWidget(button('Cancel',d.reject));d.exec()

    def qc(self,v):
        d=Form('Final shop QC' if not v['data'].get('unrepaired') else 'Unrepaired return condition check',self)
        d.resize(850,760)
        self.context(d,v)
        if v['data'].get('unrepaired'):
            d.check('condition_checked','Device condition checked against intake; unrepaired outcome explained')
        else:
            for key,title in [('functional','Functional test'),('power','Power test'),('charging','Charging test'),('display','Display test'),('connectivity','Connectivity test'),('complaint','Original customer complaint resolved')]:
                d.select(key,title,[('Not checked',''),('Passed','passed'),('Failed','failed')]+([('Not applicable','not_applicable')] if key in ('charging','display','connectivity') else []))
            d.select('result','QC result',[('Choose result',''),('PASS QC','passed'),('FAIL QC — return to diagnosis','failed')])
        d.text('notes','QC findings / return condition',multiline=True)
        d.text('repair_warranty','Repair warranty terms',multiline=True)
        d.date('warranty_until','Repair warranty valid until')
        def save(p):
            p['checks']={k:p.pop(k) for k in ('functional','power','charging','display','connectivity','complaint') if k in p}
            self.life.execute(self.ident,'qc',p,v['version'])
        d.submit(save)

    def context(self,d,v,customer=False):
        d.layout.addRow(label(f"{v['customer']} · {v['phone']}\n{v['number']} · {v['device']}\nComplaint: {v['complaint']}\nDiagnosis: {v['data'].get('diagnosis','See saved repair records')}\nRepair: {v['data'].get('repair_summary',v['data'].get('unrepaired','Not recorded'))}\nParts: {v['data'].get('parts_used','None recorded')}\nRoute: {v['route_label']} · {v['assignment'].get('party') or v['assignment'].get('technician') or 'Shop'}"))
        photos=self.window.db.rows("SELECT * FROM attachments WHERE job_id=? AND kind='product_photo' ORDER BY id",(self.ident,))
        if customer and v.get('photo_id'):
            photo=self.window.db.one('SELECT * FROM attachments WHERE id=?',(v['photo_id'],))
            if photo:photos=[photo]+photos
        for photo in photos[:3]:
            w=QLabel();show_photo(w,self.window.db,photo,140);d.layout.addRow(photo['title'],w)
        if not photos:d.layout.addRow(label('No device photo on this job. Use Device Photos to capture before / after evidence.'))

    def handover(self,v):
        d=Form('Device handover',self,'Complete this only when the customer actually receives the device and listed accessories.')
        d.resize(850,780);self.context(d,v,True)
        items=self.window.db.rows("SELECT description,quantity FROM items WHERE job_id=? AND type='accessory'",(self.ident,))
        d.layout.addRow(label('Accessories originally received: '+('; '.join(f"{r['description']} × {r['quantity']}" for r in items) or 'None')))
        d.layout.addRow(label('Items to return now: '+('; '.join(f"{h['description']} × {h['quantity']} ({h['location']})" for h in v['holdings'] if h['location']!='customer' and not h['location'].startswith('exception:')))))
        d.layout.addRow(label('Payments retained: '+rupees(v['paid'])+' · Balance: '+rupees(v['balance'])+'\nRepair warranty: '+(v['data'].get('repair_warranty') or 'None supplied')))
        for key,title in [('demonstrated','Device / unrepaired condition demonstrated to customer'),('accepted','Customer accepted the device'),('accessories_returned','All listed accessories returned'),('payment_checked','Payment completed or owner-approved credit reviewed')]:d.check(key,title)
        d.text('received_by','Received by',v['customer'])
        d.text('acknowledgment','Customer confirmation / signed receipt reference',multiline=True)
        if self.window.s.user['role']=='owner':d.text('credit_reason','Owner-approved credit reason (only if balance remains)',multiline=True)
        d.text('notes','Final notes',multiline=True)
        d.buttons.button(QDialogButtonBox.StandardButton.Save).setText('COMPLETE HANDOVER')
        if d.submit(lambda p:self.life.execute(self.ident,'handover',p,v['version'])):
            self.window.run(lambda:self.window.docs.generate('collection_receipt',self.ident),'Creating collection receipt…',refresh=False)

    def payment(self,kind):
        v=self.life.snapshot(self.ident)
        d=Form('Record customer payment / refund' if kind=='customer' else 'Record vendor invoice / payment',self,'Records an actual transaction already made. Does not transfer money.')
        d.layout.addRow(label('Customer balance: '+rupees(v['balance'])))
        choices=['receipt'] if self.window.s.user['role']=='counter' else ['receipt','refund'] if kind=='customer' else ['charge','payment','refund','credit']
        d.select('kind','Entry type',choices)
        d.text('amount','Amount (INR)')
        d.text('method','Payment method')
        d.text('reference','Invoice / UPI / bank / receipt reference')
        d.text('notes','Notes',multiline=True)
        operation=uuid.uuid4().hex
        def save(p):
            account=v['customer_id'] if kind=='customer' else v['assignment'].get('contact_id')
            if not account:raise RuleError('Select the vendor / service center first.')
            self.window.s.post(kind,account,operation_id=operation,job_id=self.ident,**dict(p,amount=money(p['amount'])))
        d.submit(save)
