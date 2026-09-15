"""Parts, issued cards and warranties inside the existing repair workspace."""
import json
from datetime import date
from PyQt6.QtCore import QUrl,Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QDialog
from .ui_widgets import Grid,Form,button,panel,FlowLayout
from .domain import money,rupees,RuleError, today
from .parts import Parts
from .job_cards import JobCards
from .warranties import Warranties


class RepairRecords(QWidget):
    def __init__(self,workspace,kind):
        super().__init__()
        self.ws,self.w,self.kind=workspace,workspace.window,kind
        self.s,self.ident=self.w.s,workspace.ident
        self.parts,self.cards,self.warranties=Parts(self.s),JobCards(self.s),Warranties(self.s)
        layout=QVBoxLayout(self);layout.setSpacing(12)
        info_panel,info_layout=panel({'cards':'Issued job cards','parts':'Parts and stock','warranty':'Warranty control'}[kind])
        self.info=QLabel();self.info.setWordWrap(True);info_layout.addWidget(self.info);layout.addWidget(info_panel)
        if kind=='warranty':
            self.intake_warranty_info=QLabel()
            self.intake_warranty_info.setWordWrap(True)
            self.intake_warranty_info.setTextFormat(Qt.TextFormat.PlainText)
            info_layout.addWidget(self.intake_warranty_info)
        actions_panel,actions_layout=panel('Actions')
        bar=FlowLayout();actions_layout.addLayout(bar);layout.addWidget(actions_panel);self.action_buttons={}
        actions={'cards':[('View card',self.view_card),('Print selected card',self.print_card),('Print receiving receipt',self.print_receipt),('Final invoice',self.print_invoice)],
            'parts':[('Add required part',self.add_part),('Edit planned',lambda:self.add_part(self.selected())),('Remove planned',self.remove),('Mark installed',self.install),('Shop inventory',self.stock),
                ('Reserve stock',lambda:self.transfer('reserve')),('Issue to repairer',lambda:self.transfer('issue')),('Return unused',lambda:self.transfer('return')),('Release reservation',lambda:self.transfer('release')),
                ('Order external part',lambda:self.procurement('order')),('Receive external part',lambda:self.procurement('receive'))],
            'warranty':[('Repair warranty',self.repair_warranty),('Create claim',self.claim),('Edit warranty (owner)',self.edit_warranty),('Update claim',self.update_claim),
                ('Manual warranty check',self.manual_warranty),('Manual check history',self.manual_history),('Privileged override (owner)',lambda:self.edit_warranty(True))]}
        if kind=='cards' and self.s.user['role']=='owner':actions['cards'].append(('Print internal copy (owner)',lambda:self.print_card(True)))
        if kind=='parts' and self.s.user['role']=='owner':actions['parts'].append(('Write off part (owner)',self.writeoff))
        for i,(title,fn) in enumerate(actions[kind]):
            b=button(title,lambda checked=False,f=fn:self.ws.support(f),i==0);bar.addWidget(b);self.action_buttons[title]=b
            b.setEnabled(not self.w.db.readonly or title=='View card')
            if 'owner' in title and self.s.user['role']!='owner':b.hide()
        self.grid=Grid();self.grid.setMinimumHeight(140);layout.addWidget(self.grid,1)
        self.claim_grid=Grid()
        self.detail=QLabel();self.detail.setWordWrap(True);layout.addWidget(self.detail)
        self.grid.itemSelectionChanged.connect(self.show_selected)
        if kind=='warranty':
            layout.addWidget(QLabel('CLAIM HISTORY · select a claim below to update it'));layout.addWidget(self.claim_grid,1)

    def selected(self):
        return self.w.selected(self.grid)

    def reload(self):
        if self.kind=='cards':
            rows=self.cards.rows(self.ident)
            self.info.setText('One Master Job · cards are issued snapshots of actual events. Select a card to view or print its saved details.' if rows else 'LEGACY RECORD · no historical cards have been invented.')
            self.grid.fill([dict(r,card=f"CARD-{r['sequence']:02d}",type=r['kind'].replace('_',' ').title(),sender=r['from_name'],receiver=r['to_name'],status='Completed') for r in rows],['card','type','sender','receiver','effective','status'])
        elif self.kind=='parts':
            rows=self.parts.rows(self.ident)
            for r in rows:
                supplier=json.loads(r['supplier_snapshot']) if r['supplier_snapshot'] else {}
                r['supplier']=supplier.get('name','Shop stock' if r['source']=='stock' else 'See source notes')
                r['warranty']=f"{r['warranty_duration']} {r['warranty_unit']}"
            self.info.setText('Search inventory first. Reserve stock, record its physical issue, then install it after customer approval. External parts keep their own supplier and receipt record.')
            columns=['name','quantity','source','customer_price','stock_state','stock_location','procurement_status','status','warranty_expiry','supplier','installed_by','installed_at','warranty','brand','model','part_number','serial']
            if self.s.user['role']=='owner':columns[3:3]=['purchase_cost','margin']
            self.grid.fill(rows,columns)
        else:
            job=self.s.job(self.ident)
            device=job['device_id']
            intake=json.loads(job['lifecycle_data']).get('intake_warranty')
            self.intake_warranty_info.setVisible(bool(intake))
            if intake:
                source='Recorded shop sale dates' if intake['source']=='shop' else 'Customer-reported external warranty'
                details=[f"{source} at intake: {intake['status']}", 'Coverage must be verified before repair authorization.']
                for key,label in (('checked_on','Recorded'),('sale_date','Sale date'),('start_date','Starts'),('expiry','Expires'),('provider','Provider'),('terms','Sale terms'),('notes','Customer notes')):
                    if intake.get(key):details.append(f"{label}: {intake[key]}")
                self.intake_warranty_info.setText('\n'.join(details))
            self.info.setText('Warranties follow this physical device across repair jobs. Create a new intake for a returning device, then claim its original warranty here. No previous repair is overwritten.')
            checks=self.warranties.manual_checks(self.ident)
            if checks:
                latest=checks[0]
                self.info.setText(self.info.text()+f"\nMANUAL WARRANTY CHECK #{latest['id']}: {latest['result']} · {latest['coverage']} · {latest['evidence_type']} {latest['reference']} · {latest['provider']} · Checked by {latest['checked_by']}")
            self.grid.fill(self.warranties.rows(device),['name','original_job','installed_at','duration','unit','expiry','effective_status','provider','terms'])
            self.claim_grid.fill(self.warranties.claims(device),['id','claim_job','original_job','part','complaint','status','resolution','replacement_part_id'])
        self.show_selected()

    def show_selected(self):
        r=self.grid.selected()
        if self.kind=='warranty':
            locked=bool(r and r.get('claim_id'))
            self.action_buttons['Edit warranty (owner)'].setEnabled(bool(r) and not locked and self.s.user['role']=='owner' and not self.w.db.readonly)
            self.detail.setText(f"WARRANTY STATUS MANAGED BY ACTIVE CLAIM · WC-{r['claim_id']:06d} · {r['claim_state']}" if locked else '')
            return
        if not r or self.kind!='parts':
            self.detail.setText('');return
        internal=f"Purchase cost: {rupees(r['purchase_cost'])} / unit · Margin: {rupees(r['margin'])} · " if self.s.user['role']=='owner' else ''
        self.detail.setText(f"{r['name']} · {r['status'].upper()} · Qty {r['quantity']} · {r.get('supplier','')}\n{internal}Customer price: {rupees(r['customer_price'])} / unit\nInstalled: {r['installed_at'] or 'Pending'} by {r['installed_by'] or 'Not recorded'} · Warranty: {r['warranty_duration']} {r['warranty_unit']} · Expires: {r.get('warranty_expiry') or 'Starts on installation'} · Provider: {r['warranty_provider'] or 'No warranty'}")

    def view_card(self):
        p=json.loads(self.selected()['snapshot'])
        d=QDialog(self);d.setWindowTitle(p['master_job']+' / '+p['card_number']);d.resize(750,650)
        from PyQt6.QtWidgets import QTextEdit
        def party(v):return '\n'.join(str(x) for k,x in v.items() if k!='id' and x)
        content=[p['kind'].replace('_',' ').upper(),'From: '+party(p['from']),'To: '+party(p['to']),f"Device: {p['device']} · DEV-{p['device_id']:06d}\nSerial / IMEI: {p['serial']}",
            'Complaint: '+p['complaint'],'Condition: '+p['condition'],'Items: '+'; '.join(f"{r['description']} × {r['quantity']}" for r in p['items']),
            'Received: '+p['effective'],'Recorded by: '+p['staff'],'Expected return: '+str(p['expected_return'] or 'Not specified'),'Reference: '+str(p['reference']), 'Acknowledgment: '+p['acknowledgment'],p['notes']]
        content += ['Current custodian: '+p.get('current_custodian','See historical sender / receiver'),'Final destination: '+p.get('final_destination','')]
        if p.get('return_details'):content.append('RETURN RESULT\n'+json.dumps(p['return_details'],ensure_ascii=False,indent=2))
        layout=QVBoxLayout(d);text=QTextEdit();text.setReadOnly(True);text.setPlainText('\n\n'.join(content));layout.addWidget(text);layout.addWidget(button('Close',d.accept));d.exec()

    def open_pdf(self,fn):
        self.w.run(fn,'Generating printable document…',callback=lambda p:QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))),refresh=False)

    def print_card(self,internal=False):
        ident=self.selected()['id'];self.open_pdf(lambda:self.cards.print(ident,internal=internal))

    def print_receipt(self):
        self.open_pdf(lambda:self.w.docs.generate('intake_receipt',self.ident))

    def print_invoice(self):
        self.open_pdf(lambda:self.w.docs.generate('final_invoice',self.ident))

    def add_part(self,row=None):
        from .part_editor import choose_and_plan
        choose_and_plan(self,row)

    def remove(self):
        row=self.selected();d=Form('Remove planned part',self);d.text('reason','Reason',multiline=True)
        d.submit(lambda p:self.parts.remove(row['id'],p['reason']))

    def install(self):
        row=self.selected();d=Form('Record part installed',self,row['name']);d.text('installed_by','Installed by',self.ws.view['responsible']);d.date('installed_date','Installation date',today())
        d.submit(lambda p:self.parts.install(row['id'],**p))

    def stock(self):
        from .inventory_ui import InventoryPage
        d=QDialog(self);d.setWindowTitle('Shop inventory');d.resize(1200,740)
        layout=QVBoxLayout(d);layout.addWidget(InventoryPage(self.w));layout.addWidget(button('Close',d.accept));d.exec()

    def transfer(self,action):
        from .inventory import Inventory
        row=self.selected();d=Form(action.title()+' shop part',self,row['name']+' · Qty '+str(row['quantity']))
        d.text('reference','Reservation / handover acknowledgment');d.text('notes','Notes',multiline=True)
        d.submit(lambda p:Inventory(self.s).transfer(row['id'],action,**p))

    def procurement(self,action):
        row=self.selected();d=Form(action.title()+' external part',self,row['name']);d.text('reference','Order / receipt reference')
        d.submit(lambda p:self.parts.procure(row['id'],action,**p))

    def writeoff(self):
        from .inventory import Inventory
        row=self.selected();d=Form('Write off reserved / issued part',self,row['name'])
        d.select('action','Reason type',[('Damaged','damaged'),('Scrapped','scrapped')]);d.text('reference','Write-off reference / reason');d.text('notes','Details',multiline=True)
        d.submit(lambda p:Inventory(self.s).transfer(row['id'],**p))

    def claim(self):
        row=self.selected();d=Form('Open warranty claim',self,'This job must be a new repair for the same device. The original job remains unchanged.')
        d.text('complaint','Complaint',self.s.job(self.ident)['complaint'],multiline=True)
        d.text('override_reason','Expired warranty override reason (owner only)',multiline=True)
        d.submit(lambda p:self.warranties.claim(self.ident,row['id'],**p))

    def repair_warranty(self):
        d=Form('Register repair warranty',self,'Installed parts receive their own warranty automatically. Use this for repair workmanship.')
        d.text('name','Warranty description','Repair workmanship');d.text('duration','Duration','3');d.select('unit','Unit',['days','months','years'],'months')
        d.date('start_date','Starts',today());d.text('provider','Provider',self.w.db.setting('shop_name','Repair shop'));d.text('terms','Coverage / exclusions',multiline=True)
        def save(p):p['duration']=int(p['duration']);self.warranties.repair_warranty(self.ident,**p)
        d.submit(save)

    def edit_warranty(self,privileged=False):
        self.s.require_permission('correct_warranty');r=self.selected();d=Form('Edit warranty with audit',self)
        d.text('duration','Duration',r['duration']);d.select('unit','Unit',['days','months','years'],r['unit']);d.date('start_date','Starts',r['start_date'])
        if r.get('claim_id') and not privileged:raise RuleError('Warranty status is managed by its active claim.')
        if privileged:d.check('confirmed','I understand this overrides warranty data during an active claim; the claim remains authoritative in the display')
        d.select('status','Status',['ACTIVE','VOID','REPLACED'],r['status'])
        for k in ('provider','terms','notes'):d.text(k,k.title(),r[k],multiline=k!='provider')
        d.text('reason','Reason for correction',multiline=True)
        def save(p):
            if privileged and not p.pop('confirmed'):raise RuleError('Confirm the explicit owner override.')
            p['duration']=int(p['duration']);self.warranties.edit(r['id'],privileged_override=privileged,**p)
        d.submit(save)

    def manual_warranty(self):
        d=Form('Manual warranty verification',self,'Use real evidence when an old warranty is absent. This records a check on this job; it does not create historical stock or an invented installation.')
        d.select('result','Verification result',['UNVERIFIED','VALID','INVALID'],'UNVERIFIED')
        d.select('evidence_type','Evidence',['Shop invoice','Warranty slip','Supplier invoice','Manufacturer warranty','Vendor confirmation','Other'])
        d.select('coverage','Warranty coverage',[('Manufacturer','manufacturer'),('Shop part warranty','shop_part'),('Shop repair warranty','shop_repair'),('Supplier','supplier'),('Vendor','vendor')],'shop_part')
        for k,title in [('reference','Evidence reference number'),('provider','Warranty provider'),('notes','Verification findings')]:d.text(k,title,multiline=k=='notes')
        attachments=self.w.db.rows('SELECT id,title FROM attachments WHERE job_id=? OR device_id=?',(self.ident,self.s.job(self.ident)['device_id']))
        picker=d.select('attachment_id','Evidence attachment (optional)',[('No attachment',None)]+[(a['title'],a['id']) for a in attachments])
        def attach():
            from PyQt6.QtWidgets import QFileDialog
            path,_=QFileDialog.getOpenFileName(d,'Attach warranty evidence','','Evidence (*.pdf *.jpg *.jpeg *.png)')
            if path:
                saved=self.w.docs.attach(path,'Manual warranty evidence',job_id=self.ident)
                ident=self.w.db.one('SELECT id FROM attachments WHERE path=?',(saved.relative_to(self.w.db.root).as_posix(),))['id']
                picker.addItem('Manual warranty evidence',ident);picker.setCurrentIndex(picker.findData(ident))
        d.layout.addRow(button('Attach evidence file / photo',lambda:self.w.safe(attach)))
        d.submit(lambda p:self.warranties.manual_check(self.ident,**p))

    def manual_history(self):
        d=QDialog(self);d.setWindowTitle('Manual warranty evidence history');d.resize(1100,650);layout=QVBoxLayout(d);grid=Grid()
        grid.fill(self.warranties.manual_checks(self.ident),['id','result','coverage','evidence_type','reference','provider','checked_by','checked_at','notes','attachment_id'])
        layout.addWidget(grid);layout.addWidget(button('Close',d.accept));d.exec()

    def update_claim(self):
        r=self.w.selected(self.claim_grid)
        if r['new_job_id']!=self.ident:raise RuleError('Open the claim job to update its claim.')
        d=Form('Update warranty claim',self)
        d.select('status','New status',['OPEN','ACCEPTED','REJECTED','IN_REPAIR','REPLACED','COMPLETED','CLOSED'],r['status'])
        d.text('resolution','Decision / resolution',multiline=True)
        d.select('replacement_part_id','Installed replacement',[('No replacement',None)]+[(p['name'],p['id']) for p in self.parts.rows(self.ident) if p['status']=='installed'],r['replacement_part_id'])
        d.submit(lambda p:self.warranties.update_claim(r['id'],**p))
