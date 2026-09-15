import json
import sqlite3
import pytest
from repairshop.domain import RuleError
from repairshop.lifecycle import Lifecycle
from repairshop.documents import Documents
from repairshop.ui_widgets import MasterSelector,Form


def master(s,kind,name):
    return next(r['id'] for r in s.masters(kind) if r['name']==name)


def product(s,customer,name,category='Laptop',**extra):
    return dict(customer_id=customer,device=name,complaint='Test fault',category_id=master(s,'category',category),service_id=master(s,'service',category+' repair'),guided=True,**extra)


def test_services_follow_category_and_common_services_are_shared(service):
    laptop=master(service,'category','Laptop');desktop=master(service,'category','Desktop')
    assert {r['name'] for r in service.services_for_category(laptop)}=={'Laptop repair','Diagnosis','Warranty assessment'}
    assert {r['name'] for r in service.services_for_category(desktop)}=={'Desktop repair','Diagnosis','Warranty assessment'}
    shared=service.save_master('service','Board repair',category_ids=[laptop,desktop])
    assert shared in {r['id'] for r in service.services_for_category(laptop)}
    assert shared not in {r['id'] for r in service.services_for_category(master(service,'category','Printer'))}
    service.save_master('service','Board repair',ident=shared,category_ids=[])
    assert shared in {r['id'] for r in service.services_for_category(master(service,'category','Printer'))}


def test_mismatched_service_is_blocked_at_save(service,customer):
    p=product(service,customer,'Desktop','Desktop');p['service_id']=master(service,'service','Laptop repair')
    with pytest.raises(RuleError,match='category'):service.intake(**p)
    assert not service.db.rows('SELECT * FROM jobs')


def test_selector_drops_incompatible_selection_and_scopes_inline_service(qtbot,service):
    selector=MasterSelector(service,'service');qtbot.addWidget(selector)
    assert not selector.add_button.isEnabled() and selector.box.count()==1
    laptop=master(service,'category','Laptop');desktop=master(service,'category','Desktop')
    selector.set_category(laptop);selector.box.setCurrentIndex(selector.box.findData(master(service,'service','Laptop repair')))
    selector.set_category(desktop)
    assert selector.value() is None and selector.box.findData(master(service,'service','Laptop repair'))<0
    ident=service.save_master('service','Desktop cooling fan repair',category_id=desktop)
    selector.reload(ident);assert selector.value()==ident
    assert ident not in {r['id'] for r in service.services_for_category(laptop)}


def test_receive_multiple_devices_atomically_with_separate_cards_and_advances(service,customer):
    products=[product(service,customer,'Laptop A',advance=10000,accessories=[dict(type='accessory',description='Adapter',quantity=1)]),product(service,customer,'Printer B','Printer',advance=20000)]
    jobs=service.intake_visit(products,'test-visit')
    assert len(jobs)==2 and len({service.job(i)['device_id'] for i in jobs})==2
    assert len({service.job(i)['intake_ref'] for i in jobs})==1
    assert len(service.db.rows('SELECT * FROM job_cards'))==2
    assert service.db.one("SELECT sum(amount) n FROM entries WHERE kind='receipt'")['n']==-30000
    assert service.intake_visit(products,'test-visit')==jobs
    assert len(service.db.rows('SELECT * FROM jobs'))==2
    assert Documents(service).visit_receipt(jobs).read_bytes().startswith(b'%PDF')
    assert len(Lifecycle(service).rows(search=service.job(jobs[0])['intake_ref']))==2


def test_failed_second_product_rolls_back_entire_visit_and_keeps_draft(service,customer):
    from repairshop.customer_records import CustomerRecords
    CustomerRecords(service).save_draft('draft-visit',dict(customer_id=customer,visit_products=[{'device':'Retain me'}]))
    p1=product(service,customer,'Laptop A',advance=10000)
    p2=product(service,customer,'Printer B','Printer');p2['service_id']=master(service,'service','Laptop repair')
    with pytest.raises(RuleError):service.intake_visit([p1,p2],'draft-visit',draft_id='draft-visit')
    for table in ('jobs','items','movements','entries','job_cards','commands'):
        assert service.db.one('SELECT count(*) n FROM '+table)['n']==0
    assert CustomerRecords(service).drafts()[0]['id']=='draft-visit'


def test_visit_rejects_mixed_customers_and_duplicate_existing_device(service,customer):
    other=service.save_customer('Another test customer')
    with pytest.raises(RuleError,match='same customer'):service.intake_visit([product(service,customer,'A'),product(service,other,'B')],'mixed')
    from repairshop.customer_records import device_record
    with service.db.transaction() as c:device=device_record(c,customer,'Physical laptop')
    p=product(service,customer,'Physical laptop',device_id=device)
    with pytest.raises(RuleError,match='outstanding'):service.intake_visit([p,p],'duplicate-device')
    assert not service.db.rows('SELECT * FROM jobs')


def test_visit_basket_draft_resume_edit_and_save(qtbot,service,customer,monkeypatch):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication,QDialogButtonBox
    from repairshop.ui import MainWindow
    from repairshop.customer_records import CustomerRecords
    w=MainWindow(service);qtbot.addWidget(w)
    summaries=[];monkeypatch.setattr(w,'visit_summary',lambda ids:summaries.append(ids))
    # The post-intake send/print dialog runs after the records are committed; the test
    # records the jobs it was given instead of opening it.
    monkeypatch.setattr(w,'post_intake',lambda jobs,documents,document_error='':summaries.append(jobs))
    def fill_product(form,name,category,amount):
        form.fields['category_id'].box.setCurrentIndex(form.fields['category_id'].box.findData(master(service,'category',category)))
        svc=form.fields['service_id'].box;svc.setCurrentIndex(svc.findData(master(service,'service',category+' repair')))
        form.fields['device'].setText(name);form.fields['complaint'].setPlainText('Fault on '+name);form.fields['advance'].setText(amount)
        form.fields['brand'].setText('Test brand');form.fields['model'].setText('Test model')
    def first():
        form=QApplication.activeModalWidget()
        try:
            form.fields['customer_id'].select(customer)
            fill_product(form,'Laptop A','Laptop','100')
            next(c for c in form.visit_intake.checks if c.text()=='Adapter').setChecked(True)
            form.visit_intake.add_current()
            assert not form.fields['customer_id'].isEnabled()
            assert form.fields['device'].text()=='' and form.fields['advance'].text()=='0'
            assert form.intake_support.photo_id
            fill_product(form,'Printer B','Printer','200');form.visit_intake.add_current()
            fill_product(form,'Phone not received','Phone','0');form.visit_intake.add_current()
            form.visit_intake.grid.selectRow(2);form.visit_intake.remove_selected()
            assert len(form.visit_intake.products)==2
            form.reject()
        except BaseException:form.reject();raise
    QTimer.singleShot(30,first);w.intake()
    draft=CustomerRecords(service).drafts()[0]
    assert len(json.loads(draft['payload'])['visit_products'])==2 and not service.db.rows('SELECT * FROM jobs')
    def resumed():
        form=QApplication.activeModalWidget()
        try:
            assert len(form.visit_intake.products)==2
            form.visit_intake.grid.selectRow(1);form.visit_intake.edit_selected()
            assert form.fields['device'].text()=='Printer B'
            assert form.fields['service_id'].value()==master(service,'service','Printer repair')
            form.fields['complaint'].setPlainText('Revised printer fault')
            form.wizard.go(3)
            form.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException:form.reject();raise
    QTimer.singleShot(30,resumed);w.intake(draft=draft)
    qtbot.waitUntil(lambda:not w.tasks,timeout=15000)
    assert len(summaries)==1 and len(summaries[0])==2
    assert service.db.one("SELECT complaint FROM jobs WHERE device='Printer B'")['complaint']=='Revised printer fault'
    assert service.db.rows("SELECT j.device FROM items i JOIN jobs j ON j.id=i.job_id WHERE i.type='accessory'")==[{'device':'Laptop A'}]
    assert not CustomerRecords(service).drafts()
    qtbot.waitUntil(lambda:not w.tasks,timeout=10000)


def test_schema7_migration_preserves_existing_job_and_scopes_seed_service(service,customer,tmp_path):
    import shutil
    from repairshop.persistence import Database, SCHEMA_VERSION
    from repairshop.backup import Backups
    job=service.intake(**product(service,customer,'Legacy laptop'))
    target=tmp_path/'schema7';shutil.copytree(service.db.root,target,ignore=shutil.ignore_patterns('shop.db*'))
    with service.db.read() as source:
        with sqlite3.connect(target/'shop.db') as c:source.driver_connection.backup(c)
    with sqlite3.connect(target/'shop.db') as c:
        from schema_fixtures import remove_v9
        remove_v9(c)
        c.execute('DROP TABLE category_services');c.execute('PRAGMA user_version=7')
    upgraded=Database(target)
    assert upgraded.one('SELECT * FROM jobs WHERE id=?',(job,))==service.db.one('SELECT * FROM jobs WHERE id=?',(job,))
    assert upgraded.one('PRAGMA user_version')['user_version']==SCHEMA_VERSION
    archive=list((target/'backups').glob('*pre-upgrade-v7*.zip'))[0]
    assert Backups.validate(archive)['schema']==7
