import json
from datetime import date, timedelta

import pytest
from PyQt6.QtWidgets import QDialogButtonBox, QApplication

from repairshop.customer_ui import IntakeForm
from repairshop.domain import RuleError
from repairshop.ui import MainWindow
from repairshop.ui_widgets import STYLE
from repairshop.customer_records import CustomerRecords
from repairshop.intake_fields import INTAKE_STYLE


def open_intake(qtbot, service, monkeypatch, **kwargs):
    window = MainWindow(service); window.timer.stop(); qtbot.addWidget(window)
    dialogs = []
    monkeypatch.setattr(IntakeForm, 'submit', lambda form, callback: dialogs.append(form) or 0)
    window.intake(**kwargs)
    form = dialogs[0]; form.setStyleSheet(STYLE + INTAKE_STYLE); form.show(); qtbot.addWidget(form)
    return form


def select(form, key, text):
    widget = form.fields[key]
    box = widget.box if hasattr(widget, 'box') else widget
    box.setCurrentIndex(next((i for i in range(box.count()) if box.itemText(i).split(' (all categories)')[0]==text), -1))


def product(form, name='Test laptop'):
    select(form, 'category_id', 'Laptop')
    form.fields['device'].setText(name)
    form.fields['brand'].setText('Test brand'); form.fields['model'].setText('Model 1')
    form.fields['complaint'].setPlainText('Power fault')
    select(form, 'service_id', 'Diagnosis')


def test_shop_sale_autofill_warranty_and_end_to_end_save(qtbot,service,customer,monkeypatch):
    category = next(r['id'] for r in service.masters('category') if r['name']=='Laptop')
    sale_id = service.save_sale(customer, 'Dell Inspiron 15', category_id=category, serial='ABC123',
        sale_date=date.today().isoformat(), warranty_start=date.today().isoformat(),
        warranty_end=(date.today()+timedelta(days=365)).isoformat())
    sale = service.db.one('SELECT * FROM sales WHERE id=?',(sale_id,))
    CustomerRecords(service).update_device(sale['device_id'],'Dell Inspiron 15','Dell','Inspiron 15','ABC123')
    form=open_intake(qtbot,service,monkeypatch,customer_id=customer)
    wizard=form.wizard
    select(form,'origin','This shop')
    wizard.sales.setCurrentIndex(wizard.sales.findData(sale_id))
    assert form.fields['serial'].text()=='ABC123'
    assert form.fields['brand'].text()=='Dell'
    assert 'Warranty Active' in wizard.warranty_badge.text()
    assert form.fields['service_id'].box.currentText().startswith('Warranty assessment')
    wizard.next_step(); assert wizard.step==1
    wizard.next_step(); assert wizard.step==2
    form.fields['complaint'].setPlainText('Shuts down after 15 minutes')
    next(c for c in form.visit_intake.checks if c.text()=='Adapter').setChecked(True)
    wizard.next_step(); assert wizard.step==3
    form.fields['advance'].setText('500')
    form.fields['transport_agreed'].setText('200')
    wizard.update_summary(); assert 'Adapter × 1' in wizard.summary.text()
    ids=form.visit_intake.save()
    job=service.job(ids[0]); assert job['sale_id']==sale_id and job['device_id']==sale['device_id']
    assert json.loads(job['lifecycle_data'])['intake_warranty']['status']=='VALID'
    assert service.db.one("SELECT amount FROM entries WHERE kind='receipt'")['amount']==-50000
    form.keep_draft=None; form.close()


def test_external_wizard_validation_back_draft_and_save(qtbot,service,customer,monkeypatch):
    form=open_intake(qtbot,service,monkeypatch,customer_id=customer)
    wizard=form.wizard
    wizard.next_step(); assert wizard.step==1
    wizard.next_step(); assert wizard.step==1
    assert 'category' in form.error.text()
    product(form)
    select(form,'warranty_status','Valid warranty')
    form.fields['warranty_provider'].setText('External seller')
    form.fields['warranty_notes'].setPlainText('Customer has original bill')
    wizard.next_step(); assert wizard.step==2
    adapter=next(c for c in form.visit_intake.checks if c.text()=='Adapter')
    adapter.setChecked(True); form.fields['no_accessories'].setChecked(True)
    assert not adapter.isChecked()
    adapter.setChecked(True); assert not form.fields['no_accessories'].isChecked()
    wizard.go(1); assert form.fields['complaint'].toPlainText()=='Power fault'
    form.intake_support.save_draft()
    draft=CustomerRecords(service).drafts()[0]
    form.keep_draft=None; form.close()
    resumed=open_intake(qtbot,service,monkeypatch,draft=draft)
    assert resumed.fields['warranty_provider'].text()=='External seller'
    assert resumed.fields['complaint'].toPlainText()=='Power fault'
    resumed.fields['advance'].setText('-1')
    with pytest.raises(RuleError): resumed.visit_intake.save()
    resumed.fields['advance'].setText('')
    ids=resumed.visit_intake.save()
    warranty=json.loads(service.job(ids[0])['lifecycle_data'])['intake_warranty']
    assert warranty['source']=='external' and warranty['provider']=='External seller'
    assert warranty['verification']=='customer_reported'
    assert not CustomerRecords(service).drafts()
    resumed.keep_draft=None; resumed.close()


def test_source_switch_does_not_link_stale_sale(qtbot,service,customer,monkeypatch):
    sid=service.save_sale(customer,'Sold printer',serial='SOLD1')
    form=open_intake(qtbot,service,monkeypatch,sale=service.db.one('SELECT * FROM sales WHERE id=?',(sid,)))
    assert form.intake_support.sale['id']==sid
    select(form,'origin','Elsewhere')
    assert form.intake_support.sale is None
    assert form.fields['device_id'].currentData() is None
    assert not form.fields['serial'].text()
    product(form)
    ident=form.visit_intake.save()[0]
    assert service.job(ident)['sale_id'] is None
    form.keep_draft=None; form.close()


def test_customer_search_alternate_number(qtbot,service):
    from repairshop.ui_widgets import CustomerSelector
    ident=service.save_customer('Alternate contact',phone_number='9995551234',alternate='9994447777')
    selector=CustomerSelector(service); qtbot.addWidget(selector)
    selector.search.setText('9994447777')
    assert selector.box.findData(ident)>0


def test_new_customer_external_inline_category_accessory_complete_flow(qtbot,service,monkeypatch):
    from PyQt6.QtCore import QTimer, QDate
    from PyQt6.QtGui import QImage, QColor
    from PyQt6.QtWidgets import QPushButton
    form=open_intake(qtbot,service,monkeypatch)
    owner=form.fields['customer_id'];owner.search.setText('New visit customer')
    form.fields['complaint'].setPlainText('Keeps restarting')
    failures=[]
    def register():
        dialog=QApplication.activeModalWidget()
        try:
            dialog.fields['phone_number'].setText('9995551234')
            dialog.fields['address_line1'].setText('45 Test Lane')
            dialog.fields['pincode'].setText('411002')
            dialog.state.setCurrentText('Maharashtra')
            dialog.district.setCurrentText('Pune')
            image=QImage(40,40,QImage.Format.Format_RGB32);image.fill(QColor('#89aabb'))
            dialog.set_photo(image);dialog.save()
            assert dialog.saved_id
        except BaseException as exc:failures.append(exc);dialog.reject()
    QTimer.singleShot(0,register);owner.new_customer()
    assert not failures
    assert owner.text() and form.intake_support.photo_id
    assert form.fields['complaint'].toPlainText()=='Keeps restarting'
    form.wizard.next_step();assert form.wizard.step==1
    def add_master(name):
        dialog=QApplication.activeModalWidget()
        try:
            dialog.fields['name'].setText(name)
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException as exc:failures.append(exc);dialog.reject()
    QTimer.singleShot(0,lambda:add_master('Smart speaker'))
    form.fields['category_id'].add()
    assert form.fields['category_id'].box.currentText()=='Smart speaker'
    form.fields['brand'].setText('Example');form.fields['model'].setText('Speaker 1')
    select(form,'warranty_status','Valid warranty')
    form.fields['warranty_expiry'].setDate(QDate.currentDate().addDays(100))
    form.fields['warranty_provider'].setText('External retailer')
    form.wizard.next_step();assert form.wizard.step==2
    QTimer.singleShot(0,lambda:add_master('Speaker power cable'))
    next(b for b in form.findChildren(QPushButton) if b.text()=='+ Add new accessory choice').click()
    assert not failures
    accessory=next(c for c in form.visit_intake.checks if c.text()=='Speaker power cable')
    assert accessory.isChecked()
    form.wizard.next_step();assert form.wizard.step==3
    identifiers=form.visit_intake.save()
    job=service.job(identifiers[0])
    assert job['device']=='Example Speaker 1' and job['customer_id']==owner.text()
    assert json.loads(job['lifecycle_data'])['intake_warranty']['provider']=='External retailer'
    assert service.db.one("SELECT description FROM items WHERE job_id=? AND type='accessory'",(job['id'],))['description']=='Speaker power cable'
    assert service.db.one('SELECT 1 FROM category_accessories WHERE category_id=?',(form.fields['category_id'].value(),))
    form.keep_draft=None;form.close()


def test_linked_return_basket_edit_preserves_original_job(qtbot,service,customer,job,monkeypatch):
    # Seed the previous completed handover; the new intake must reuse this physical device.
    with service.db.transaction() as connection:
        connection.execute("UPDATE holdings SET location='customer'")
    form=open_intake(qtbot,service,monkeypatch,parent=job)
    product(form,'Returned laptop')
    form.visit_intake.add_current()
    assert form.visit_intake.products[0]['parent_id']==job
    form.visit_intake.grid.selectRow(0);form.visit_intake.edit_selected()
    assert form.intake_support.parent==job
    created=form.visit_intake.save()[0]
    assert service.job(created)['parent_id']==job
    assert service.job(created)['device_id']==service.job(job)['device_id']
    form.keep_draft=None;form.close()


def test_brand_master_names_and_free_text_preserve_device_identity(qtbot,service,customer,monkeypatch):
    service.save_master('brand','Existing brand')
    form=open_intake(qtbot,service,monkeypatch,customer_id=customer)
    product(form)
    brand=form.fields['brand']
    assert brand.box.findText('Existing brand')>=0
    brand.box.setCurrentIndex(brand.box.findText('Existing brand'))
    form.fields['model'].setText('Free text model')
    ident=form.visit_intake.save()[0]
    device=service.db.one('SELECT * FROM devices WHERE id=?',(service.job(ident)['device_id'],))
    assert device['brand']=='Existing brand' and device['model']=='Free text model'
    form.keep_draft=None;form.close()
