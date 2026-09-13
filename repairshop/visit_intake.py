"""Draft visit basket using the existing per-device intake form and service."""
import json
import uuid
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QDialogButtonBox,QSizePolicy
from .ui_widgets import Grid,button,FlowLayout
from .domain import RuleError,money


class VisitIntake:
    def __init__(self,window,form,support,checks,storage,draft=None):
        self.w,self.form,self.support,self.checks,self.storage=window,form,support,checks,storage
        payload=json.loads(draft['payload']) if draft else {}
        self.products=payload.get('visit_products',[])
        form.visit_intake=self
        if not form.fields['intake_ref'].text():form.fields['intake_ref'].setText('VIS-'+uuid.uuid4().hex[:10].upper())
        box=QWidget();layout=QVBoxLayout(box);layout.setContentsMargins(0,0,0,0)
        box.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
        self.info=QLabel();self.info.setWordWrap(True);layout.addWidget(self.info)
        self.grid=Grid();self.grid.setMinimumHeight(100);self.grid.setMaximumHeight(150);layout.addWidget(self.grid)
        self.grid.set_empty_text('Add each product here. Each device receives its own repair job.')
        controls=FlowLayout();layout.addLayout(controls)
        self.add=button('+ Add this product to visit',lambda:window.safe(self.add_current),True)
        self.edit=button('Edit selected product',lambda:window.safe(self.edit_selected))
        self.remove=button('Remove selected product',lambda:window.safe(self.remove_selected))
        for control in (self.add,self.edit,self.remove):controls.addWidget(control)
        # Kept outside the scrolling form, so the visit list is always available.
        root=QWidget.layout(form)
        root.insertWidget(root.count()-2,box)
        form.resize(820,940)
        self.reload()

    def current(self):
        payload=self.support.payload()
        payload.pop('visit_products',None)
        return payload

    def entered(self):
        p=self.form.values()
        return any(p.get(k) for k in ('device','brand','model','serial','complaint','damage','device_id','category_id','service_id'))

    def prepare(self,payload):
        p=dict(payload)
        if not p.get('customer_id'):
            raise RuleError('Select or register the device owner first.')
        if not p.get('photo_id'):
            raise RuleError('Capture and save the required customer photo before adding products.')
        if not p.get('device','').strip() or not p.get('complaint','').strip():
            raise RuleError('Enter the device description and reported fault for this product.')
        self.w.s.validate_intake_service(p.get('category_id'),p.get('service_id'))
        storage=self.w.db.one("SELECT name FROM masters WHERE id=? AND kind='storage' AND active=1",(p.pop('storage_id',None),))
        if not storage:raise RuleError('Choose shop storage for this product.')
        p['storage']='shop:'+storage['name']
        p.pop('photo_role',None);p.pop('visit_products',None)
        for key in ('advance','deposit','transport_agreed','assessment_agreed'):
            p[key]=money(p[key])
            if p[key]<0:raise RuleError('Intake amounts cannot be negative.')
        p['accessories']=[dict(type='accessory',description=a['description'],quantity=a['quantity'],serial=a.get('serial','')) for a in p.get('accessories',[]) if a.get('checked')]
        p['guided']=True
        return p

    def add_current(self):
        self.w.s.require('owner','counter')
        if len(self.products)>=50:raise RuleError('Receive up to 50 products in one visit.')
        p=self.current();self.prepare(p)
        if self.products and p['customer_id']!=self.products[0]['customer_id']:
            raise RuleError('All products in this visit must belong to the same customer.')
        if p.get('device_id') and any(r.get('device_id')==p['device_id'] for r in self.products):
            raise RuleError('This physical device is already in the visit list.')
        self.products.append(p)
        self.clear_product();self.reload();self.support.save_draft()

    def clear_product(self):
        self.support.parent=None;self.support.sale=None
        self.form.fields['device_id'].setCurrentIndex(0)
        self.form.fields['category_id'].box.setCurrentIndex(0)
        for key in ('device','brand','model','serial','complaint','damage'):
            self.form.fields[key].clear()
        for key in ('repair_due','collection_due'):
            self.form.fields[key].setDate(QDate(1900,1,1))
        for key in ('advance','deposit','transport_agreed','assessment_agreed'):
            self.form.fields[key].setText('0')
        self.form.fields['assessment_consent'].setChecked(False)
        self.form.fields['origin'].setCurrentIndex(self.form.fields['origin'].findData('elsewhere'))
        for check in self.checks:check.setChecked(False)

    def edit_selected(self):
        row=self.w.selected(self.grid)
        if self.entered():raise RuleError('Add the product currently being entered before editing another product in this visit.')
        p=self.products.pop(row['index'])
        self.support.parent=p.get('parent_id')
        self.support.sale=self.w.db.one('SELECT * FROM sales WHERE id=?',(p.get('sale_id'),)) if p.get('sale_id') else None
        self.support.restore(p)
        self.reload();self.support.save_draft()

    def remove_selected(self):
        row=self.w.selected(self.grid);self.products.pop(row['index'])
        self.reload();self.support.save_draft()

    def reload(self):
        count=len(self.products)
        self.info.setText(f'{count} product(s) in this visit. Add another device above, or Save visit to receive all listed products.' if count else 'Multiple products? Fill one device above, then Add this product to visit. Customer details and photo are shared; each device gets its own repair job.')
        self.grid.fill([dict(index=n,product=r['device'],fault=r['complaint'],category=(self.w.db.one('SELECT name FROM masters WHERE id=?',(r.get('category_id'),)) or {}).get('name','Not selected'),advance=r.get('advance','0')) for n,r in enumerate(self.products)],['product','category','fault','advance'])
        self.grid.setVisible(bool(count));self.edit.setEnabled(bool(count));self.remove.setEnabled(bool(count))
        self.form.fields['customer_id'].setEnabled(not count)
        self.form.fields['intake_ref'].setReadOnly(bool(count))
        self.form.buttons.button(QDialogButtonBox.StandardButton.Save).setText('Save visit' if count else 'Save')

    def save(self):
        self.support.save_draft()
        products=list(self.products)
        if self.entered() or not products:products.append(self.current())
        prepared=[self.prepare(p) for p in products]
        return self.w.s.intake_visit(prepared,self.support.draft_id,draft_id=self.support.draft_id)
