"""Inventory-first required-part selection inside the existing Parts tab."""
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QLabel
from .ui_widgets import Form,Grid,button
from .inventory import Inventory
from .domain import money


def choose_and_plan(records,row=None):
    if row:return edit_part(records,row)
    r=records;d=QDialog(r);d.setWindowTitle('Add required part · search shop inventory first');d.resize(1000,620)
    layout=QVBoxLayout(d);layout.addWidget(QLabel('Search shop stock first. Select the correct part, then reserve it from the job’s Parts tab.'))
    search=QLineEdit();search.setPlaceholderText('Part name, SKU, compatibility, brand, model or supplier…');layout.addWidget(search)
    grid=Grid();layout.addWidget(grid,1);inventory=Inventory(r.s);result={}
    def reload():
        cols=['sku','name','brand','compatibility','available','customer_price','warranty']
        if r.s.may('view_internal_cost'):cols.insert(5,'purchase_cost')
        grid.fill([s for s in inventory.rows(search.text()) if s['active']],cols)
    def stock():result.update(stock=r.w.selected(grid));d.accept()
    def external():result.update(external=True);d.accept()
    controls=QHBoxLayout();layout.addLayout(controls)
    controls.addWidget(button('Use shop stock',lambda:r.w.safe(stock),True));controls.addWidget(button('Source externally',external));controls.addWidget(button('Cancel',d.reject))
    search.textChanged.connect(reload);reload()
    if d.exec():edit_part(r,stock=result.get('stock'))


def edit_part(r,row=None,stock=None):
    row=row or {};stock=stock or {};values=dict(stock,**row)
    if stock:values.update(inventory_id=stock['id'],source='stock')
    d=Form('Plan repair part',r,'Customer prices are per unit in INR and appear on the next estimate. A changed part requires a revised customer approval.')
    for key,title in [('name','Part name'),('part_type','Type'),('brand','Brand'),('model','Model'),('part_number','Part number'),('serial','Serial (one unit per serial)'),('quantity','Quantity')]:
        d.text(key,title,values.get(key,1 if key=='quantity' else ''))
    assigned=r.w.db.one('SELECT a.contact_id,m.name FROM jobs j JOIN assignments a ON a.id=j.assignment_id JOIN masters m ON m.id=a.contact_id WHERE j.id=? AND j.route=\'third_party\'',(r.ident,))
    source=d.select('source','Part source',[('Shop inventory','stock'),('Repairing third-party technician','technician'),('External supplier','supplier'),('Other (explain in notes)','other')],values.get('source','technician' if assigned else 'supplier'));source.setEditable(False)
    stocks=Inventory(r.s).rows()
    inventory=d.select('inventory_id','Inventory item',[('Select stock item',None)]+[(f"{s['sku']} · {s['name']} · {s['available']} available",s['id']) for s in stocks if s['active']],values.get('inventory_id'));inventory.setEditable(False)
    supplier=d.select('supplier_id','Supplier / repairing vendor',[('Not recorded',None)]+[(s['name'],s['id']) for s in r.w.db.rows("SELECT id,name FROM masters WHERE kind IN ('supplier','vendor') AND active=1 ORDER BY name")],values.get('supplier_id'));supplier.setEditable(False)
    def new_supplier():
        f=Form('New external supplier',d)
        for k in ('name','contact','details'):f.text(k,k.title())
        def save(p):
            ident=r.s.save_master('supplier',**p);supplier.addItem(p['name'],ident);supplier.setCurrentIndex(supplier.findData(ident))
        f.submit(save)
    add_supplier=button('+ New external supplier',lambda:r.w.safe(new_supplier));d.layout.addRow(add_supplier)
    for key,title in [('invoice','Supplier invoice'),('purchase_cost','Internal unit purchase cost (INR)'),('customer_price','Unit customer selling price (INR)'),('warranty_duration','Warranty duration (0 = not recorded)'),('warranty_provider','Warranty provider'),('warranty_terms','Warranty coverage / exclusions'),('requested_by','Part requested by'),('request_notes','Repairer requirement / diagnosis'),('notes','Source / part notes')]:
        if key=='purchase_cost' and not r.s.may('view_internal_cost'):continue
        value=str(values.get(key,0)/100) if key in ('purchase_cost','customer_price') else values.get(key,0 if key=='warranty_duration' else assigned['name'] if key=='requested_by' and assigned else '')
        d.text(key,title,value,multiline=key in ('warranty_terms','request_notes','notes'))
    d.date('purchase_date','Purchase date',values.get('purchase_date'));d.select('warranty_unit','Warranty unit',['days','months','years'],values.get('warranty_unit','months'))
    def changed_source(*_):
        kind=source.currentData();inventory.setEnabled(kind=='stock');supplier.setEnabled(kind=='supplier')
        add_supplier.setEnabled(kind=='supplier')
        if 'purchase_cost' in d.fields:d.fields['purchase_cost'].setReadOnly(kind=='stock')
        if kind=='technician':supplier.setCurrentIndex(supplier.findData(assigned['contact_id']) if assigned else 0)
        if kind in ('stock','other'):supplier.setCurrentIndex(0)
    def use_stock(*_):
        s=next((s for s in stocks if s['id']==inventory.currentData()),None)
        if s:
            source.setCurrentIndex(source.findData('stock'))
            for key in ('name','brand','model','part_number','serial','purchase_cost','customer_price','warranty_duration','warranty_provider','warranty_terms','invoice'):
                if key in d.fields:d.fields[key].setText(str(s[key]/100) if key in ('purchase_cost','customer_price') else str(s[key]))
            d.fields['warranty_unit'].setCurrentIndex(d.fields['warranty_unit'].findData(s['warranty_unit']))
            if s['serialized']:d.fields['quantity'].setText('1')
    inventory.currentIndexChanged.connect(use_stock);source.currentIndexChanged.connect(changed_source);changed_source()
    def save(p):
        for k in ('purchase_cost','customer_price'):
            if k in p:p[k]=money(p[k])
        for k in ('quantity','warranty_duration'):p[k]=int(p[k])
        # Stock supplier/defaults are authoritative in the service; a disabled
        # supplier picker cannot accidentally erase that provenance.
        if p['source']=='stock':p.pop('supplier_id',None)
        r.parts.save(r.ident,p,row.get('id'))
    d.submit(save)
