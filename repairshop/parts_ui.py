"""Parts, issued cards and warranties inside the existing repair workspace."""
import json
from datetime import date
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QDialog
from .ui_widgets import Grid,Form,button
from .domain import money,rupees,RuleError
from .parts import Parts
from .job_cards import JobCards
from .warranties import Warranties


class RepairRecords(QWidget):
    def __init__(self,workspace,kind):
        super().__init__()
        self.ws,self.w,self.kind=workspace,workspace.window,kind
        self.s,self.ident=self.w.s,workspace.ident
        self.parts,self.cards,self.warranties=Parts(self.s),JobCards(self.s),Warranties(self.s)
        layout=QVBoxLayout(self);self.info=QLabel();self.info.setWordWrap(True);layout.addWidget(self.info)
        bar=QHBoxLayout();layout.addLayout(bar)
        actions={'cards':[('View card',self.view_card),('Print selected card',self.print_card),('Print receiving receipt',self.print_receipt),('Final invoice',self.print_invoice)],
            'parts':[('Add part',self.add_part),('Edit planned',lambda:self.add_part(self.selected())),('Remove planned',self.remove),('Mark installed',self.install),('Shop stock',self.stock)],
            'warranty':[('Repair warranty',self.repair_warranty),('Create claim',self.claim),('Edit warranty (owner)',self.edit_warranty),('Update claim',self.update_claim)]}
        for title,fn in actions[kind]:
            b=button(title,lambda checked=False,f=fn:self.ws.support(f));bar.addWidget(b)
            b.setEnabled(not self.w.db.readonly or title=='View card')
        bar.addStretch();self.grid=Grid();layout.addWidget(self.grid,1)
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
            self.info.setText('Add each required part before estimating. Selling prices are added to the estimate automatically. Installation uses approved parts and reduces shop stock. Costs shown here are internal.')
            columns=['name','quantity','source','customer_price','status','warranty_expiry','supplier','installed_by','installed_at','warranty','brand','model','part_number','serial']
            if self.s.user['role']=='owner':columns[3:3]=['purchase_cost','margin']
            self.grid.fill(rows,columns)
        else:
            device=self.s.job(self.ident)['device_id']
            self.info.setText('Warranties follow this physical device across repair jobs. Create a new intake for a returning device, then claim its original warranty here. No previous repair is overwritten.')
            self.grid.fill(self.warranties.rows(device),['name','original_job','installed_at','duration','unit','expiry','effective_status','provider','terms'])
            self.claim_grid.fill(self.warranties.claims(device),['id','claim_job','original_job','part','complaint','status','resolution','replacement_part_id'])
        self.show_selected()

    def show_selected(self):
        r=self.grid.selected()
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
        layout=QVBoxLayout(d);text=QTextEdit();text.setReadOnly(True);text.setPlainText('\n\n'.join(content));layout.addWidget(text);layout.addWidget(button('Close',d.accept));d.exec()

    def open_pdf(self,fn):
        self.w.run(fn,'Generating printable document…',callback=lambda p:QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))),refresh=False)

    def print_card(self):
        ident=self.selected()['id'];self.open_pdf(lambda:self.cards.print(ident))

    def print_receipt(self):
        self.open_pdf(lambda:self.w.docs.generate('intake_receipt',self.ident))

    def print_invoice(self):
        self.open_pdf(lambda:self.w.docs.generate('final_invoice',self.ident))

    def add_part(self,row=None):
        row=row or {}
        d=Form('Plan repair part',self,'Prices are per unit in INR. The complete part price and warranty will appear on the next estimate.')
        for key,title in [('name','Part name'),('part_type','Type'),('brand','Brand'),('model','Model'),('part_number','Part number'),('serial','Serial (one unit per serial)'),('quantity','Quantity')]:
            d.text(key,title,row.get(key,1 if key=='quantity' else ''))
        d.select('source','Part source',[('Shop inventory','stock'),('External supplier','supplier'),('Supplied by third-party technician','technician'),('Other (explain in notes)','other')],row.get('source','supplier'))
        d.select('inventory_id','Shop stock item',[('Not from stock',None)]+[(f"{r['name']} · {r['available']} available",r['id']) for r in self.parts.stock()],row.get('inventory_id'))
        supplier=d.select('supplier_id','Supplier / supplying technician',[('Not applicable',None)]+[(r['name'],r['id']) for r in self.w.db.rows("SELECT id,name FROM masters WHERE kind IN ('supplier','vendor') AND active=1 ORDER BY name")],row.get('supplier_id'))
        def new_supplier():
            add=Form('Add parts supplier',d)
            for key,title in [('name','Supplier name'),('contact','Phone'),('details','Address / email / contact person')]:add.text(key,title)
            def save(v):
                ident=self.s.save_master('supplier',**v);supplier.addItem(v['name'],ident);supplier.setCurrentIndex(supplier.findData(ident))
            add.submit(save)
        d.layout.addRow('',button('+ New supplier',new_supplier))
        for key,title in [('invoice','Supplier invoice'),('purchase_cost','Unit purchase cost (INR)'),('customer_price','Unit customer price (INR)'),('warranty_duration','Warranty duration'),('warranty_provider','Warranty provider'),('warranty_terms','Warranty terms'),('notes','Source / part notes')]:
            value=str(row.get(key,0)/100) if key in ('purchase_cost','customer_price') else row.get(key,0 if key=='warranty_duration' else '')
            d.text(key,title,value,multiline=key in ('warranty_terms','notes'))
        d.date('purchase_date','Purchase date',row.get('purchase_date'))
        d.select('warranty_unit','Warranty unit',['days','months','years'],row.get('warranty_unit','months'))
        def use_stock():
            stock=next((r for r in self.parts.stock() if r['id']==d.fields['inventory_id'].currentData()),None)
            if stock:
                for key in ('name','brand','model','part_number','purchase_cost','customer_price'):
                    d.fields[key].setText(str(stock[key]/100) if key in ('purchase_cost','customer_price') else stock[key])
                d.fields['source'].setCurrentIndex(d.fields['source'].findData('stock'))
        d.fields['inventory_id'].currentIndexChanged.connect(use_stock)
        def save(v):
            for k in ('purchase_cost','customer_price'):v[k]=money(v[k])
            for k in ('quantity','warranty_duration'):v[k]=int(v[k])
            self.parts.save(self.ident,v,row.get('id'))
        d.submit(save)

    def remove(self):
        row=self.selected();d=Form('Remove planned part',self);d.text('reason','Reason',multiline=True)
        d.submit(lambda p:self.parts.remove(row['id'],p['reason']))

    def install(self):
        row=self.selected();d=Form('Record part installed',self,row['name']);d.text('installed_by','Installed by',self.ws.view['responsible']);d.date('installed_date','Installation date',date.today().isoformat())
        d.submit(lambda p:self.parts.install(row['id'],**p))

    def stock(self):
        self.s.require('owner')
        d=QDialog(self);d.setWindowTitle('Shop parts inventory');d.resize(900,600);layout=QVBoxLayout(d);grid=Grid();layout.addWidget(grid)
        def reload():grid.fill(self.parts.stock(),['name','brand','model','part_number','purchase_cost','customer_price','available'])
        def add():
            f=Form('New stock item',d)
            for k in ('name','brand','model','part_number','purchase_cost','customer_price'):f.text(k,k.replace('_',' ').title(),0 if 'cost' in k or 'price' in k else '')
            def save(v):
                for k in ('purchase_cost','customer_price'):v[k]=money(v[k])
                self.parts.stock_item(**v)
            f.submit(save);reload()
        def adjust():
            row=self.w.selected(grid);f=Form('Receive stock / correction',d,'Positive quantities receive stock; negative quantities correct it. Installation records its own stock usage.')
            for k in ('quantity','reference','notes'):f.text(k,k.title())
            f.submit(lambda p:self.parts.adjust_stock(row['id'],int(p['quantity']),p['reference'],p['notes']));reload()
        layout.addWidget(button('Add stock item',lambda:self.w.safe(add)));layout.addWidget(button('Receive / adjust selected stock',lambda:self.w.safe(adjust)));layout.addWidget(button('Close',d.accept));reload();d.exec()

    def claim(self):
        row=self.selected();d=Form('Open warranty claim',self,'This job must be a new repair for the same device. The original job remains unchanged.')
        d.text('complaint','Complaint',self.s.job(self.ident)['complaint'],multiline=True)
        d.text('override_reason','Expired warranty override reason (owner only)',multiline=True)
        d.submit(lambda p:self.warranties.claim(self.ident,row['id'],**p))

    def repair_warranty(self):
        d=Form('Register repair warranty',self,'Installed parts receive their own warranty automatically. Use this for repair workmanship.')
        d.text('name','Warranty description','Repair workmanship');d.text('duration','Duration','3');d.select('unit','Unit',['days','months','years'],'months')
        d.date('start_date','Starts',date.today().isoformat());d.text('provider','Provider',self.w.db.setting('shop_name','Repair shop'));d.text('terms','Coverage / exclusions',multiline=True)
        def save(p):p['duration']=int(p['duration']);self.warranties.repair_warranty(self.ident,**p)
        d.submit(save)

    def edit_warranty(self):
        self.s.require('owner');r=self.selected();d=Form('Edit warranty with audit',self)
        d.text('duration','Duration',r['duration']);d.select('unit','Unit',['days','months','years'],r['unit']);d.date('start_date','Starts',r['start_date'])
        d.select('status','Status',['ACTIVE','VOID','CLAIMED','REPLACED'],r['status'])
        for k in ('provider','terms','notes'):d.text(k,k.title(),r[k],multiline=k!='provider')
        d.text('reason','Reason for correction',multiline=True)
        def save(p):p['duration']=int(p['duration']);self.warranties.edit(r['id'],**p)
        d.submit(save)

    def update_claim(self):
        r=self.w.selected(self.claim_grid)
        if r['new_job_id']!=self.ident:raise RuleError('Open the claim job to update its claim.')
        d=Form('Update warranty claim',self)
        d.select('status','New status',['OPEN','ACCEPTED','REJECTED','IN_REPAIR','REPLACED','COMPLETED','CLOSED'],r['status'])
        d.text('resolution','Decision / resolution',multiline=True)
        d.select('replacement_part_id','Installed replacement',[('No replacement',None)]+[(p['name'],p['id']) for p in self.parts.rows(self.ident) if p['status']=='installed'],r['replacement_part_id'])
        d.submit(lambda p:self.warranties.update_claim(r['id'],**p))
