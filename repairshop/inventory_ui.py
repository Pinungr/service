"""Shop inventory navigation, catalog details and immutable movement history."""
import uuid
from datetime import date
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QDialog,QLabel,QLineEdit,QTabWidget
from .ui_widgets import Grid,Form,button,combo,panel,FlowLayout
from .inventory import Inventory
from .domain import money,rupees


class InventoryPage(QWidget):
    def __init__(self,window):
        super().__init__();self.w=window;self.s=window.s;self.inventory=Inventory(self.s)
        layout=QVBoxLayout(self);layout.setSpacing(12)
        summary_panel, summary_layout = panel('Inventory control', 'Owned stock includes reserved and issued parts until installation. Every stock change has a permanent movement record.')
        self.summary=QLabel();self.summary.setWordWrap(True);summary_layout.addWidget(self.summary);layout.addWidget(summary_panel)
        search_panel, search_layout = panel('Search and filter')
        search=QHBoxLayout();search_layout.addLayout(search);layout.addWidget(search_panel)
        self.search=QLineEdit();self.search.setPlaceholderText('Search part, SKU, brand, model, compatibility, supplier or serial…');search.addWidget(self.search,1)
        self.filter=combo([('All parts','all'),('Low stock','low'),('Out of stock','out')],'all');search.addWidget(self.filter)
        self.grid=Grid();layout.addWidget(self.grid,1)
        controls=FlowLayout();layout.addLayout(controls)
        actions=[('Part details',self.detail),('New inventory item',self.edit),('Edit item / warranty defaults',lambda:self.edit(self.w.selected(self.grid))),
            ('Receive / adjust stock',self.adjust),('Stock movements',self.history),('Suppliers',lambda:self.w.navigate('Directories'))]
        for i,(title,fn) in enumerate(actions):
            b=button(title,lambda checked=False,f=fn:self.w.safe(f),title=='New inventory item');controls.addWidget(b)
            if i in (1,2,3):b.setEnabled(self.s.user['role']=='owner' and not self.w.db.readonly)
        self.search.textChanged.connect(self.reload);self.filter.currentIndexChanged.connect(self.reload);self.reload()

    def reload(self,*_):
        rows=self.inventory.rows(self.search.text(),self.filter.currentData());allrows=self.inventory.rows()
        self.summary.setText(f"{len(allrows)} inventory items · {sum(r['available'] for r in allrows)} available units · {sum(r['reserved'] for r in allrows)} reserved · {sum(r['issued'] for r in allrows)} issued")
        cols=['sku','name','brand','compatibility','stock','reserved','issued','available','customer_price','warranty','supplier','storage','active']
        if self.s.user['role']=='owner':cols[9:9]=['purchase_cost','margin']
        self.grid.fill(rows,cols)

    def edit(self,row=None):
        row=row or {};d=Form('Inventory item and warranty defaults',self,'Use one inventory item per serialized unit. Generic parts may have any whole quantity. Stock quantities change through stock movements.')
        for key,title in [('sku','SKU (generated if blank)'),('name','Part name'),('brand','Brand'),('model','Model'),('part_number','Part number'),('compatibility','Compatible devices / notes'),('serial','Serial (serialized units only)'),('batch','Batch number'),('invoice','Supplier invoice'),('storage','Shelf / bin'),('minimum_stock','Minimum available quantity')]:
            d.text(key,title,row.get(key,'Stock shelf' if key=='storage' else 0 if key=='minimum_stock' else ''))
        d.check('serialized','Individually serialized unit',row.get('serialized',False))
        d.select('category_id','Product category',[('General / other',None)]+[(r['name'],r['id']) for r in self.s.masters('category')],row.get('category_id'))
        suppliers=self.w.db.rows("SELECT id,name FROM masters WHERE kind IN ('supplier','vendor') AND active=1 ORDER BY name")
        supplier=d.select('supplier_id','Supplier',[('Not recorded',None)]+[(r['name'],r['id']) for r in suppliers],row.get('supplier_id'))
        def new_supplier():
            f=Form('New supplier',d)
            for k in ('name','contact','details'):f.text(k,k.title())
            def save(v):
                ident=self.s.save_master('supplier',**v);supplier.addItem(v['name'],ident);supplier.setCurrentIndex(supplier.findData(ident))
            f.submit(save)
        d.layout.addRow(button('+ New supplier',lambda:self.w.safe(new_supplier)))
        d.date('purchase_date','Purchase date',row.get('purchase_date'))
        for k,title in [('purchase_cost','Unit purchase cost (INR)'),('customer_price','Default customer price (INR)')]:d.text(k,title,str(row.get(k,0)/100))
        d.text('markup','Default markup % (optional)',str(row['markup_basis_points']/100) if row.get('markup_basis_points') is not None else '')
        d.check('calculate_price','Calculate selling price from cost and markup',False)
        d.text('warranty_duration','Default warranty duration (0 = not recorded)',row.get('warranty_duration',0))
        d.select('warranty_unit','Warranty unit',['days','months','years'],row.get('warranty_unit','months'))
        d.text('warranty_provider','Warranty provider',row.get('warranty_provider',''))
        d.text('warranty_terms','Warranty coverage / exclusions',row.get('warranty_terms',''),multiline=True)
        d.text('notes','Notes',row.get('notes',''),multiline=True);d.check('active','Active item',row.get('active',True))
        def save(v):
            for k in ('purchase_cost','customer_price'):v[k]=money(v[k])
            for k in ('minimum_stock','warranty_duration'):v[k]=int(v[k])
            markup=v.pop('markup');v['markup_basis_points']=money(markup) if markup else None
            if v.pop('calculate_price'):
                if v['markup_basis_points'] is None:
                    from .domain import RuleError
                    raise RuleError('Enter a markup percentage to calculate the price.')
                v.pop('customer_price')
            self.inventory.save(v,row.get('id'))
        if d.submit(save):self.reload()

    def adjust(self):
        row=self.w.selected(self.grid);d=Form('Receive stock / record adjustment',self,row['sku']+' · '+row['name']+'\nReceipts increase stock. Damage/scrap decreases available stock. Use a signed quantity for corrections.')
        d.select('kind','Movement type',[('Stock received','STOCK_RECEIVED'),('Stock adjustment','STOCK_ADJUSTMENT'),('Damaged','DAMAGED'),('Scrapped','SCRAPPED'),('Warranty replacement received','WARRANTY_REPLACEMENT'),('Customer return to stock','CUSTOMER_RETURN')],'STOCK_RECEIVED')
        d.text('quantity','Quantity','1');d.text('reference','Invoice / correction reason');d.text('notes','Notes',multiline=True)
        operation_id=uuid.uuid4().hex
        def save(v):
            qty=int(v.pop('quantity'))
            if v['kind'] in ('DAMAGED','SCRAPPED'):qty=-abs(qty)
            self.inventory.adjust(row['id'],qty,operation_id=operation_id,**v)
        if d.submit(save):self.reload()

    def history(self):
        d=QDialog(self);d.setWindowTitle('Stock movement history');d.resize(1200,650);layout=QVBoxLayout(d);grid=Grid()
        grid.fill(self.inventory.movements(),['created','sku','part','kind','quantity','delta','from_location','to_location','job','reference','staff','notes'])
        layout.addWidget(grid);layout.addWidget(button('Close',d.accept));d.exec()

    def detail(self):
        row=self.w.selected(self.grid);d=QDialog(self);d.setWindowTitle(row['sku']+' · '+row['name']);d.resize(1150,740);layout=QVBoxLayout(d)
        text=f"{row['name']} · {row['brand']} {row['model']} · {row['compatibility']}\nStock {row['stock']} · Reserved {row['reserved']} · Issued {row['issued']} · Available {row['available']}\nCustomer price {rupees(row['customer_price'])} · Warranty {row['warranty']} · {row['warranty_provider']}\nSupplier: {row['supplier'] or 'Not recorded'} · Invoice {row['invoice']} · Bin {row['storage']} · Serial {row['serial']} · Batch {row['batch']}"
        if self.s.user['role']=='owner':text+=f"\nUnit purchase cost {rupees(row['purchase_cost'])} · Unit margin {rupees(row['margin'])}"
        summary=QLabel(text);summary.setWordWrap(True);layout.addWidget(summary);tabs=QTabWidget();layout.addWidget(tabs,1)
        movements=self.inventory.movements(stock_id=row['id'])
        for title,rows,cols in [('Stock movements',movements,['created','kind','quantity','from_location','to_location','job','reference','staff']),
            ('Purchase / receipt history',[m for m in movements if m['delta']>0],['created','quantity','supplier','invoice','purchase_date','reference','notes','staff']+(['purchase_cost'] if self.s.user['role']=='owner' else []))]:
            grid=Grid();grid.fill(rows,cols);tabs.addTab(grid,title)
        installed=self.w.db.rows("SELECT p.id,j.number job,p.name,p.quantity,p.installed_at,p.installed_by,w.expiry FROM repair_parts p JOIN jobs j ON j.id=p.job_id LEFT JOIN part_warranties w ON w.part_id=p.id WHERE p.inventory_id=? AND p.status='installed'",(row['id'],))
        grid=Grid();grid.fill(installed,['job','name','quantity','installed_at','installed_by','expiry']);tabs.addTab(grid,'Installations')
        claims=self.w.db.rows('SELECT c.id,j.number job,c.complaint,c.status,c.resolution FROM warranty_claims c JOIN repair_parts p ON p.id=c.part_id JOIN jobs j ON j.id=c.new_job_id WHERE p.inventory_id=?',(row['id'],))
        grid=Grid();grid.fill(claims);tabs.addTab(grid,'Warranty claims');layout.addWidget(button('Close',d.accept));d.exec()
