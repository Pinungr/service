"""Counter-friendly views and dialogs; all transition decisions live in Lifecycle."""
import json
import uuid
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QLineEdit,QScrollArea,QTabWidget,QCheckBox,QMessageBox,QDialogButtonBox,QSpinBox,QSplitter)
from .ui_widgets import Form,Grid,button,combo,panel,FlowLayout,Cancelled
from repairshop.lifecycle import Lifecycle,ACTIONS,ROUTE_LABELS,local_time
from repairshop.domain import rupees, money, RuleError, in_shop
from .customer_ui import DevicePhotos,show_photo

COLUMNS=['number','customer','phone','device','stage_age','route','status','responsible','next_action','attention']
ZERO_INPUT_ACTIONS=frozenset(('inspect','start_repair','notify'))


def label(text, large=False):
    w=QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    if large:
        w.setStyleSheet('font-size:18px;font-weight:750;color:#102a43;padding:4px;background:transparent')
    return w


class JobWorkspace(QDialog):
    def __init__(self,window,ident,embedded=False):
        super().__init__(window)
        self.window,self.ident,self.embedded=window,ident,embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.life=Lifecycle(window.s)
        self.resize(1220,840)
        self.setMinimumSize(720,520)
        shell=QVBoxLayout(self);shell.setContentsMargins(0,0,0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True);shell.addWidget(scroll)
        content=QWidget();scroll.setWidget(content)
        outer=QVBoxLayout(content)
        outer.setContentsMargins(18,18,18,16)
        outer.setSpacing(12)
        self.heading=label('',True)
        outer.addWidget(self.heading)
        context=QWidget();context.setObjectName('card')
        self.metrics=QGridLayout(context)
        self.metrics.setContentsMargins(12,9,12,9)
        self.metrics.setHorizontalSpacing(18)
        self.metrics.setVerticalSpacing(6)
        self.values={}
        for n,(key,title) in enumerate([('route_label','REPAIR ROUTE'),('current_status','REPAIR STATUS'),('received_by_name','RECEIVED BY'),('assigned_technician','ASSIGNED TO'),('currently_with','CURRENTLY WITH'),('final_destination','FINAL DESTINATION')]):
            title_label=label(title.title());title_label.setObjectName('muted')
            self.values[key]=label('')
            self.metrics.addWidget(title_label,n//2,(n%2)*2)
            self.metrics.addWidget(self.values[key],n//2,(n%2)*2+1)
        self.metrics.setColumnStretch(1,1);self.metrics.setColumnStretch(3,1)
        outer.addWidget(context)
        from .repair_journey import RepairJourney
        self.splitter=QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setMinimumHeight(700)
        self.journey=RepairJourney(self)
        self.journey.action_requested.connect(self.act)
        self.journey.inline_action_requested.connect(self.act_inline)
        self.tracker=self.journey  # Readable compatibility view, backed by the same nodes.
        self.primary=self.journey.primary
        self.splitter.addWidget(self.journey)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(360)
        self.splitter.addWidget(self.tabs);self.splitter.setSizes([380,420])
        outer.addWidget(self.splitter,1)
        route_scroll=QScrollArea();route_scroll.setWidgetResizable(True)
        route=QWidget();route_layout=QVBoxLayout(route)
        self.actions_caption=label('Other actions for this stage')
        route_layout.addWidget(self.actions_caption)
        self.buttons=FlowLayout();route_layout.addLayout(self.buttons)
        self.tools_caption=label('Tools');self.tools_caption.setObjectName('muted')
        route_layout.addWidget(self.tools_caption)
        self.tools=FlowLayout();route_layout.addLayout(self.tools)
        self.record_meta=label('')
        self.record_meta.setObjectName('muted')
        route_layout.addWidget(self.record_meta)
        from .repair_details import RepairDetails
        self.summary=RepairDetails();route_layout.addWidget(self.summary);route_layout.addStretch()
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
        self.dispatch_tab=None
        self.party_quote_tab=None
        self.cost_panel=None
        if window.s.may('view_internal_cost'):
            from .costing_ui import CostPanel
            self.cost_panel=CostPanel(self);self.tabs.addTab(self.cost_panel,'Internal costing')
        utility_toggle=button('Utilities && administrative actions',lambda:self.utilities.setVisible(not self.utilities.isVisible()))
        outer.addWidget(utility_toggle)
        self.utilities=QWidget();utility_layout=QVBoxLayout(self.utilities);utility_layout.setContentsMargins(0,0,0,0)
        footer=FlowLayout();utility_layout.addLayout(footer)
        for text,fn in [('Full records',lambda:window.job_records(ident)),('Same visit',lambda:window.visit_jobs(ident)),('Documents',lambda:window.document_form(ident)),('Expected dates',lambda:window.date_form(ident)),('Hold / release',lambda:window.hold_form(ident))]:
            b=button(text,lambda checked=False,f=fn:self.support(f));footer.addWidget(b)
            b.setEnabled(not window.db.readonly or text=='Full records')
        self.exception_buttons=FlowLayout();utility_layout.addLayout(self.exception_buttons)
        outer.addWidget(self.utilities);self.utilities.hide()
        shell.addWidget(button('Back to repairs' if embedded else 'Close window',
                               self.close_workspace))
        self.reload()

    def close_workspace(self):
        if self.embedded:
            self.window.navigate(self.window.previous_page)
        else:
            self.accept()

    def resizeEvent(self,event):
        super().resizeEvent(event)

    def support(self,fn):
        self.window.safe(fn)
        self.reload()

    def reload(self):
        self.view=self.life.snapshot(self.ident);v=self.view
        self.setWindowTitle(v['number']+' · Repair lifecycle')
        self.heading.setText(f"{v['number']}  ·  {v['device']}\n{v['customer']}  ·  {v['phone']}"
                             + (f"  ·  DEV-{v['device_id']:06d}" if v['device_id'] else ''))
        # Who took the product in, who is responsible for the repair and who is holding it
        # are three different answers and are shown as three different fields.
        v=dict(v,received_by_name=(v.get('received_by') or {}).get('name') or 'Not recorded',
            currently_with=(v['current_custodian'] or 'Not recorded')
            +(' · '+v['custodian_role'] if v.get('custodian_role') else '')
            +('\nSince '+local_time(v['custodian_since']) if v.get('custodian_since') else '')
            +('\n'+v['current_location'] if v.get('current_location') else ''))
        for key,w in self.values.items():
            w.setText(str(v[key] or '—').replace('_',' '))
        self.journey.set_snapshot(v,readonly=self.window.db.readonly)
        self.next=self.journey.current_action
        self.record_meta.setText(f"Visit: {v['visit_number'] or 'Not recorded'}  ·  "
                                 f"Current card: {v['current_card']}  ·  {v['warranty_indicator']}")
        self.summary.set_snapshot(v)
        for group in (self.buttons,self.tools,self.exception_buttons):
            while group.count():
                item=group.takeAt(0)
                if item.widget():item.widget().hide();item.widget().deleteLater()
        actions=v['actions'][:]
        for index,action in enumerate(actions):
            if action==v['primary']:continue
            b=button(ACTIONS[action],lambda checked=False,a=action:self.act(a))
            b.setEnabled(not self.window.db.readonly)
            group=(self.exception_buttons if action in ('adopt','change_route','decline','repair_failed','rework','resolve_item','details')
                   else self.tools if action in ('parts','manual_warranty','costing','hand_over') else self.buttons)
            group.addWidget(b)
        if self.window.s.may('vendor_accounts') and v['route']!='in_house':
            self.tools.addWidget(button('Third-party invoice / payment',lambda:self.support(lambda:self.payment('vendor'))))
        # A caption with no buttons under it reads as a missing feature.
        self.actions_caption.setVisible(self.buttons.count()>0)
        self.tools_caption.setVisible(self.tools.count()>0)
        self.timeline.fill(v['timeline'],['time','event','actor','details'])
        self.custody.fill(v['holdings'],['description','type','serial','location','quantity'])
        for tab in self.record_tabs:tab.reload()
        # The dispatch record belongs to this job only; it appears once a route sends it out.
        if self.dispatch_tab is None and (v['route']!='in_house' or v['dispatch']):
            from .dispatch_ui import DispatchPanel
            self.dispatch_tab=DispatchPanel(self)
            wrapper=QScrollArea();wrapper.setWidgetResizable(True);wrapper.setWidget(self.dispatch_tab)
            self.tabs.addTab(wrapper,'Third-party dispatch')
            if self.window.s.may('view_internal_cost'):
                from .party_quotes_ui import PartyQuotePanel
                self.party_quote_tab=PartyQuotePanel(self)
                quotes=QScrollArea();quotes.setWidgetResizable(True);quotes.setWidget(self.party_quote_tab)
                self.tabs.addTab(quotes,'Third-party quotation')
        else:
            if self.dispatch_tab is not None:self.dispatch_tab.reload()
            if self.party_quote_tab is not None:self.party_quote_tab.reload()
        if self.cost_panel:self.cost_panel.reload()

    def act(self,action):
        if not action:return
        try:
            self._act(action)
        except Exception as exc:
            self.journey.show_error(str(exc))
        else:
            self.reload()

    def act_inline(self, action, payload):
        try:
            self.life.execute(self.ident, action, payload, self.view['version'])
        except Exception as exc:
            self.journey.show_error(str(exc))
        else:
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
        if action=='bill':return self.review_billing(v)
        if action in ZERO_INPUT_ACTIONS:
            return self.life.execute(self.ident,action,{},v['version'])
        if action=='close':
            prompt=QMessageBox(self)
            prompt.setWindowTitle('Close job')
            prompt.setText('Close this delivered job?')
            prompt.setInformativeText('The job and its history will remain available in Repair History.')
            close_button=prompt.addButton('Close job',QMessageBox.ButtonRole.AcceptRole)
            cancel_button=prompt.addButton('Cancel',QMessageBox.ButtonRole.RejectRole)
            prompt.setDefaultButton(cancel_button)
            prompt.exec()
            if prompt.clickedButton() is close_button:
                return self.life.execute(self.ident,action,{},v['version'])
            return
        d=Form(ACTIONS[action],self,v['next_action'])
        if action=='adopt':
            d.check('confirmed','I reviewed the saved status, location, quotation and history')
            d.text('notes','Review findings / reason',multiline=True)
        elif action=='verify_warranty':
            d.select('warranty_status','Warranty status',[('Unknown / requires verification','unknown'),('Under manufacturer warranty','under_warranty'),('Out of warranty','out_of_warranty')])
            d.text('notes','Purchase proof / warranty dates / verification notes',multiline=True)
        elif action=='prepare_dispatch':
            partner=v['assignment']
            d.layout.addRow('Sending to',label(partner.get('summary') or partner.get('party') or 'External repairer'))
            # The same conditional transport block as the dispatch tab, which corrects
            # this record later: one builder, so the two screens cannot drift apart.
            from .dispatch_ui import MODE_LABELS, PAYER_LABELS, transport_fields
            usual='BUS' if self.window.s.masters('transporter') else 'COURIER'
            gather=transport_fields(d, d.select('transport_mode','Transport method',MODE_LABELS,usual), service=self.window.s)
            d.text('transport_amount','Transport charge (INR)','0')
            d.select('paid_by','Transport paid by',PAYER_LABELS,'shop')
            d.text('condition','Device condition at dispatch',v['damage'],multiline=True)
            d.date('expected_return','Expected return date',v['return_due'])
            d.text('reference','Service centre ticket / external job number',partner.get('reference',''))
            checks=[]
            for h in v['holdings']:
                if in_shop(h['location']):
                    box=QCheckBox(h['description']+f" · {h['quantity']} unit(s)")
                    box.setChecked(h['type']=='device');d.layout.addRow('Send item',box);checks.append((h['id'],box))
            d.check('consent','Customer consent to dispatch and assessment recorded',v['assessment_consent'])
            d.text('notes','Dispatch notes',multiline=True)
            def prepare(p):
                p=dict(p,items=[i for i,w in checks if w.isChecked()],amount=money(p.pop('transport_amount') or '0'))
                p['transport_mode'],p['transport'],p['transporter_id']=gather(p)
                self.life.execute(self.ident,action,p,v['version'])
            return d.submit(prepare)
        elif action=='hand_over':
            holders=' / '.join(dict.fromkeys(h['name']+' ('+h['role']+')' for h in v['custodians'])) or 'Not recorded'
            d.layout.addRow(label('Currently with: '+holders
                +'\nHanding the product over does not change who the repair is assigned to.'))
            people=[(f"{r['name']} · {r['role'].title()}",r['id']) for r in self.window.db.rows(
                "SELECT id,name,role FROM users WHERE active=1 AND id!=? ORDER BY name",(self.window.s.user['id'],))]
            if not people:raise RuleError('There is no other active staff member to hand this product to.')
            d.select('to_user_id','Hand over to',people)
            d.text('condition','Condition at handover',v['damage'],multiline=True)
            d.text('acknowledgment','Handover acknowledgment')
            d.text('notes','Reason / notes',multiline=True)
        elif action in ('hand_technician','return_technician'):
            d.text('condition','Device condition',v['damage'],multiline=True)
            d.text('acknowledgment','Physical handover acknowledgment')
            if action=='hand_technician':d.text('bench','Technician work area / bench',v['data'].get('technician_bench',''))
            else:d.layout.addRow(label('Taken back by: '+self.window.s.user['name']+' (you)'))
            d.text('notes','Handover notes',multiline=True)
        elif action in ('dispatch','arrive','receive','return_dispatch'):
            manifest=v['data'].get('dispatch',{})
            from repairshop.dispatch import carrier, tracking
            record=(v.get('dispatch') or {}) if action=='dispatch' else {}
            # What the dispatch record already says is offered, not asked for again.
            sender=((record.get('transport') or {}).get('person_name') or (record.get('transporter_snapshot') or {}).get('contact_person')
                    or (record.get('transport') or {}).get('courier_name') or '')
            d.layout.addRow(label('Current custodian: '+v['current_custodian']+'\nDestination: '+(v['final_destination'] or v['assignment'].get('party') or 'Shop')))
            d.text('counterparty','Person receiving the items',sender)
            d.text('condition','Condition at handover',manifest.get('condition',''),multiline=True)
            d.text('reference','Tracking / external job reference',tracking(record) if record else manifest.get('reference',''))
            d.text('acknowledgment','Acknowledgment / receipt reference',multiline=True)
            if action in ('dispatch','return_dispatch'):d.text('carrier','Carrier (blank = direct handover)' if action=='dispatch' else 'Courier receiving the return',carrier(record) if action=='dispatch' else '')
            if action=='receive':d.layout.addRow(label('Received by: '+self.window.s.user['name']+' (you)'))
            d.text('notes','Notes',multiline=True)
            if action=='receive':
                return self.receive_from_external(v,d)
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
        elif action=='details':
            details=v['data'].get('route_details',{})
            if v['data'].get('legacy_review'):
                d.select('warranty_status','Verified legacy warranty status',[('Unknown','unknown'),('Under warranty','under_warranty'),('Out of warranty','out_of_warranty')],v['warranty_status'])
            if v['route']!='in_house':
                d.layout.addRow('Repair partner',label((v['assignment'].get('summary') or v['assignment'].get('party') or 'Not selected')
                    +'\nContact details are kept in Contacts & Services.'))
                for key,title in [('external_reference','Service centre ticket / external job number'),('claim_number','Warranty claim number'),('vendor_status','External repair status')]:
                    d.text(key,title,details.get(key,'') or (v['assignment'].get('reference','') if key=='external_reference' else ''))
                d.date('expected_return','Expected return',v['return_due'])
                if self.window.s.may('view_internal_cost'):
                    for k,title in [('vendor_parts','Vendor parts cost'),('vendor_labour','Vendor labour cost'),('transport_cost','Transport cost'),('other_cost','Other cost'),('customer_price','Proposed customer price')]:
                        d.text(k,title+' (INR)',str(details.get(k,0)/100))
            elif self.window.s.may('view_internal_cost'):
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
        else:
            d.text('notes','Findings / notes',multiline=True)
        def save(p):
            for key in ('vendor_parts','vendor_labour','transport_cost','other_cost','customer_price'):
                if key in p:p[key]=money(p[key])
            self.life.execute(self.ident,action,p,v['version'])
        return d.submit(save)

    def confirm_route_change(self,parent,v,route,p):
        """Ask before an existing repair assignment is replaced. True means proceed."""
        if route=='in_house':
            chosen=self.window.db.one('SELECT name FROM masters WHERE id=?',(p.get('technician_master_id'),))
        else:
            chosen=self.window.db.one('SELECT name FROM masters WHERE id=?',(p.get('contact_id'),))
        target=ROUTE_LABELS[route]+((' · '+chosen['name']) if chosen else '')
        current=v['route_label']+((' · '+v['responsible']) if v.get('responsible') else '')
        box=QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle('Change repair route?')
        box.setText('The repair is currently assigned to:\n'+current+'\n\nYou are changing it to:\n'+target)
        box.setInformativeText('The current repair assignment will be replaced.')
        change=box.addButton('Change Route',QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Cancel',QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(change)
        box.exec()
        return box.clickedButton() is change

    def route_choice(self,action,v):
        d=QDialog(self);d.setWindowTitle('Choose repair route');d.resize(620,430)
        layout=QVBoxLayout(d)
        layout.addWidget(label('HOW WILL THIS DEVICE BE REPAIRED?',True))
        layout.addWidget(label('Warranty: '+v['warranty_status'].replace('_',' ')))
        def choose(route):
            f=Form(ROUTE_LABELS[route],d,'Assign responsibility here. Physical location changes only when you record an actual handover.')
            if route!='in_house':
                from .contacts_ui import ContactSelector
                centre=route=='warranty_centre'
                picker=f.add('contact_id','Service centre' if centre else 'Third-party repairer',
                             ContactSelector(self.window.s,'centre' if centre else 'vendor',job_id=self.ident))
            else:
                opts = [(r['name'],r['id']) for r in self.window.db.rows("SELECT id,name FROM masters WHERE kind='technician' AND active=1 ORDER BY name")]
                if not opts:
                    opts = [("Unassigned", None)]
                f.select('technician_master_id','Assigned technician', opts)
                handed=f.check('handed_over','Device physically handed to this technician now',False)
                for key,title in [('bench','Technician work area / bench'),('condition','Condition at handover'),('acknowledgment','Physical handover acknowledgment')]:
                    field=f.text(key,title);field.setEnabled(False);handed.toggled.connect(field.setEnabled)
            # The job itself identifies the work; the owner never types an internal reference.
            f.layout.addRow('Internal job reference', label(f"{v['number']} | {v['device']} | "
                + ('SN-' + v['serial'] if v['serial'] else 'No serial recorded')))
            if route!='in_house':
                # Only what is unique to this repair; the partner's details come from the directory.
                f.text('reference','Service centre ticket / RMA' if centre else 'External job / ticket no.')
                expected=f.date('expected_return','Expected return',v['return_due'])
                f.text('instructions','Special instructions / notes',multiline=True)
                def turnaround(option):
                    days=((option or {}).get('snapshot') or {}).get('turnaround_days')
                    if days and expected.date()==expected.minimumDate():
                        from PyQt6.QtCore import QDate
                        expected.setDate(QDate.currentDate().addDays(int(days)))
                picker.on_change=turnaround
                turnaround(picker.selected_option())
            def save(p):
                # Saving is the confirmation for a first assignment. Replacing an
                # existing one asks explicitly, because it discards the current party.
                if action=='change_route' and not self.confirm_route_change(f,v,route,p):
                    raise Cancelled
                self.life.execute(self.ident,action,dict(p,route=route,confirmed=True),v['version'])
            if f.submit(save):d.accept()
        from repairshop.lifecycle import route_choices
        titles={'warranty_centre':'SEND TO AUTHORIZED SERVICE CENTER','in_house':'REPAIR IN OUR SHOP','third_party':'SEND TO THIRD PARTY'}
        for choice in route_choices(v):
            b=button(titles[choice['route']],lambda checked=False,r=choice['route']:choose(r),True);b.setMinimumHeight(68)
            b.setEnabled(choice['available']);b.setToolTip(choice['reason'] or titles[choice['route']])
            layout.addWidget(b)
        layout.addWidget(button('Cancel',d.reject));d.exec()

    def receive_from_external(self,v,d):
        """Check the returned items against the outbound dispatch manifest before custody moves."""
        from repairshop.returns import Returns,DISCREPANCIES
        expected=Returns(self.window.s).expected(self.ident)
        d.resize(860,860)
        d.layout.addRow(label('RECEIVE FROM '+('SERVICE CENTER' if v['route']=='warranty_centre' else 'THIRD PARTY')
            +f"\nJob: {v['number']}\nProduct: {v['device']}\nSent to: {expected['party'] or v['assignment'].get('party') or 'External repairer'}"))
        d.text('work_performed','Work performed',v['data'].get('repair_summary',''),multiline=True)
        d.text('parts_reported','Parts / replacements reported by repairer',v['data'].get('parts_used',''),multiline=True)
        d.text('vendor_invoice','Third-party / service centre invoice',v['data'].get('route_details',{}).get('vendor_invoice',''))
        d.select('repair_result','Repair result',[('Use recorded repair outcome',None)]+[(x,x) for x in ('REPAIRED','PARTIALLY REPAIRED','NOT REPAIRABLE','REPAIR DECLINED','RETURNED WITHOUT REPAIR','REPLACED')])
        d.layout.addRow(label('Received by: '+self.window.s.user['name']+' (you)'))
        d.layout.addRow(label('OUTBOUND ITEM  ·  units actually received now'))
        controls,reports=[],[]
        for row in expected['items']:
            if not row['available']:continue
            quantity=QSpinBox();quantity.setRange(0,row['expected']);quantity.setValue(row['expected'])
            d.layout.addRow(f"{row['description']} · sent {row['expected']}",quantity)
            controls.append((row['item_id'],row['expected'],quantity))
            kind=combo([('No problem',''),*[(k.replace('_',' ').title(),k) for k in DISCREPANCIES]])
            note=QLineEdit();note.setPlaceholderText('Explain the discrepancy')
            d.layout.addRow('   Discrepancy',kind);d.layout.addRow('   Discrepancy note',note)
            reports.append((row['item_id'],row['expected'],quantity,kind,note))
        verified=d.check('verified','I physically checked the returned product and accessories against the dispatch manifest')
        d.text('notes','Return notes',multiline=True)
        operation=uuid.uuid4().hex
        def save(p):
            if not p.get('verified'):
                raise RuleError('Confirm that you physically checked the returned items against the dispatch manifest.')
            discrepancies=[dict(item_id=item,kind=k.currentData(),expected=sent,received=q.value(),notes=n.text())
                           for item,sent,q,k,n in reports if k.currentData()]
            p=dict(p,items=[i for i,_,q in controls if q.value()],
                   quantities={str(i):q.value() for i,_,q in controls},
                   discrepancies=discrepancies,operation_id=operation,
                   received_by=p.get('counterparty',''))
            p.pop('verified',None)
            self.life.execute(self.ident,'receive',p,v['version'])
        return d.submit(save)

    def review_billing(self,v):
        """Initial estimate, approved quote, final bill and balance, side by side."""
        from repairshop.billing import Billing,CATEGORIES
        billing=Billing(self.window.s)
        s=billing.summary(self.ident)
        d=Form('Review billing and mark ready',self,
               'Check the figures below before issuing the applicable bill. The initial estimate is kept '
               'for reference only; the customer is billed against the approved quotation.')
        d.resize(780,780)
        approved_label='APPROVED QUOTE'+(' V'+str(s['approved_version']) if s['approved_version'] else '')
        approved_value=rupees(s['approved_total']) if s['approved_total'] is not None else 'Not approved'
        block=[f"{'INITIAL ESTIMATE':<30}{rupees(s['initial_estimate']):>14}",
               f"{approved_label:<30}{approved_value:>14}",
               f"{'FINAL BILL':<30}{(rupees(s['final_bill']) if s['final_bill'] else 'Not billed yet'):>14}",
               f"{'ADVANCE PAID':<30}{rupees(s['advance']):>14}",
               f"{'OTHER PAYMENTS':<30}{rupees(s['other_payments']):>14}",
               '-'*44,
               f"{'BALANCE DUE':<30}{rupees(s['balance_due']):>14}",
               '-'*44,'','APPROVED BREAKDOWN']
        for key in CATEGORIES:
            block.append(f"{key.title():<30}{rupees(s['approved_breakdown']['totals'][key]):>14}")
        if s['installed_parts']:
            block+=['','SHOP INVENTORY PARTS INSTALLED']
            block+=[f"{(p['name']+' x'+str(p['quantity']))[:28]:<30}{rupees(p['amount']):>14}" for p in s['installed_parts']]
        if s['third_party_customer_lines']:
            block+=['','THIRD-PARTY PARTS CHARGED TO CUSTOMER']
            block+=[f"{p['description'][:28]:<30}{rupees(p['amount']):>14}" for p in s['third_party_customer_lines']]
        view=label('\n'.join(block))
        view.setStyleSheet('font-family:Consolas,monospace;padding:12px;background:white;border:1px solid #dce5ee;border-radius:8px;')
        d.layout.addRow(view)
        d.layout.addRow(label('QC result: '+v['data'].get('qc',{}).get('result','Pending')))
        outstanding=self.window.db.rows("""SELECT d.kind,d.notes,i.description FROM return_discrepancies d
            JOIN return_verifications rv ON rv.id=d.verification_id LEFT JOIN items i ON i.id=d.item_id
            WHERE rv.job_id=? AND d.resolved=''""",(self.ident,))
        if outstanding:
            d.layout.addRow(label('Unresolved return discrepancies:\n'+'\n'.join(
                f"· {r['description'] or 'Item'} — {r['kind'].replace('_',' ')}: {r['notes']}" for r in outstanding)))
        d.check('confirmed','Charges and advances reviewed; issue the applicable bill and mark ready')
        d.layout.addRow(label('A positive balance remains payable at collection. Returning without repair uses only the agreed return charges.'))
        return d.submit(lambda p:self.life.execute(self.ident,'bill',p,v['version']))

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
        if self.window.s.may('release_with_balance'):d.text('credit_reason','Owner-approved credit reason (only if balance remains)',multiline=True)
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
