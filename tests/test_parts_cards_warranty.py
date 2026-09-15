import json
import sqlite3
import pytest
from datetime import date
from repairshop.parts import Parts
from repairshop.job_cards import JobCards
from repairshop.warranties import Warranties,warranty_expiry
from repairshop.documents import Documents
from repairshop.domain import RuleError
from test_lifecycle import route,dispatch,diagnosis,approve,complete,qc,deliver,fresh


def plan(s,job,source='supplier',duration=3,price=90000):
    parts=Parts(s)
    values=dict(name='Battery',brand='Demo',model='B50',part_number='PART-B50',serial='SERIAL-B50',quantity=1,source=source,purchase_cost=40000,customer_price=price,
        warranty_duration=duration,warranty_unit='months',warranty_provider='Test Repair Shop',warranty_terms='Manufacturing defects only',invoice='INV-001',purchase_date=date.today().isoformat())
    if source=='stock':
        stock=parts.stock_item('Battery',40000,price,part_number='PART-B50');parts.adjust_stock(stock,2,'Purchase INV-001');values['inventory_id']=stock
    elif source in ('supplier','technician'):
        values['supplier_id']=s.db.one('SELECT contact_id FROM assignments WHERE id=?',(s.job(job)['assignment_id'],))['contact_id'] if source=='technician' else s.save_master('supplier','Battery supply supplier',contact='555',details='Supplier address')
    else:values['notes']='Customer-supplied part'
    ident=parts.save(job,values)
    if source=='supplier':parts.procure(ident,'receive','Supplier receipt INV-001')
    return ident


def installed(s,customer,source='supplier',kind='in_house'):
    ident,life=route(s,customer,kind)
    if kind!='in_house':dispatch(s,ident,life)
    diagnosis(life,ident);part=plan(s,ident,source)
    quote=approve(s,ident,10000)
    if source=='stock':
        from repairshop.inventory import Inventory
        Inventory(s).transfer(part,'reserve','Reserved for job')
        Inventory(s).transfer(part,'issue','Technician received battery')
    life.execute(ident,'start_repair');Parts(s).install(part,'Amit')
    life.execute(ident,'complete_repair',{'notes':'Battery installed and tested'})
    if kind!='in_house':life.execute(ident,'receive',dict(counterparty='Shop',condition='Intact',acknowledgment='Return card'))
    else:life.execute(ident,'test',dict(result='passed',notes='Passed technician test'))
    qc(life,ident)
    return ident,life,part,quote


def test_receiving_card_snapshot_print_and_immutable(service,customer):
    ident=service.intake(customer,'Lifecycle laptop','No power',guided=True,brand='Dell',model='T14',accessories=[dict(description='Adapter',type='accessory',quantity=1)])
    card=JobCards(service).rows(ident)[0];p=json.loads(card['snapshot'])
    assert card['number'].endswith(' / CARD-01') and p['master_job']==service.job(ident)['number']
    assert p['from']['phone']=='+919990000001' and p['device']=='Lifecycle laptop'
    assert p['effective'] and p['staff'] and len(p['items'])==2
    assert p['brand']=='Dell' and p['model']=='T14'
    assert Documents(service).generate('intake_receipt',ident).read_bytes().startswith(b'%PDF')
    with service.db.transaction() as c:c.execute("UPDATE customers SET name='Changed later' WHERE id=?",(customer,))
    assert json.loads(JobCards(service).rows(ident)[0]['snapshot'])['from']['name']=='Synthetic Customer'
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:c.execute('DELETE FROM job_cards WHERE id=?',(card['id'],))


@pytest.mark.parametrize('kind,warranty',[('third_party',False),('warranty_centre',True)])
def test_external_cards_same_master_private_snapshot_and_return(service,customer,kind,warranty):
    ident,life=route(service,customer,kind,warranty);dispatch(service,ident,life)
    diagnosis(life,ident)
    if warranty:life.execute(ident,'warranty_result',dict(decision='accepted',notes='Covered',rma='OEM-123'))
    else:approve(service,ident,0)
    complete(life,ident,True);qc(life,ident);deliver(service,customer,ident,life,0)
    cards=JobCards(service).rows(ident)
    assert [r['sequence'] for r in cards]==[1,2,3,4]
    assert all(r['job_id']==ident for r in cards)
    for r in cards[1:3]:
        p=json.loads(r['snapshot']);raw=r['snapshot']
        assert '9990000001' not in raw and 'synthetic@example.invalid' not in raw and 'Synthetic Customer' not in raw
        assert 'customer_photo' not in raw and 'current_photo_id' not in raw
        assert 'Test Repair Shop' in (p['from']['name'],p['to']['name'])
        assert p['movement_ids']
        assert JobCards(service).print(r['id']).is_file()
    assert cards[-1]['kind']=='customer_delivery' and life.snapshot(ident)['current_location']=='WITH CUSTOMER'
    assert Documents(service).generate('final_invoice',ident).is_file()


@pytest.mark.parametrize('source,kind',[('stock','in_house'),('supplier','in_house'),('technician','third_party'),('supplier','third_party'),('other','in_house')])
def test_part_source_approval_install_warranty_and_delivery(service,customer,source,kind):
    ident,life,part,quote=installed(service,customer,source,kind)
    p=Parts(service).rows(ident)[0]
    assert p['purchase_cost']==40000 and p['customer_price']==90000 and p['margin']==50000
    assert p['estimate_id']==quote and p['card_id'] and p['installed_by']=='Amit'
    assert p['status']=='installed' and p['warranty_expiry']==warranty_expiry(date.today().isoformat(),3,'months')
    q=service.db.one('SELECT * FROM quotes WHERE id=?',(quote,))
    assert q['total']==100000 and any(x.get('part_id')==part for x in json.loads(q['lines']))
    assert 'purchase_cost' not in q['lines']
    if source=='stock':assert Parts(service).stock()[0]['available']==1
    warranties=Warranties(service).rows(service.job(ident)['device_id'])
    assert warranties[0]['effective_status']=='ACTIVE' and warranties[0]['part_id']==part
    deliver(service,customer,ident,life,100000)
    assert Documents(service).generate('final_invoice',ident).is_file()


def test_changed_parts_preserve_approved_quote_and_require_new_approval(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident);part=plan(service,ident)
    q=approve(service,ident,10000);before=service.db.one('SELECT * FROM quotes WHERE id=?',(q,))
    Parts(service).save(ident,{'customer_price':95000},part)
    assert service.job(ident)['stage']=='awaiting_estimate'
    assert service.db.one('SELECT lines FROM quotes WHERE id=?',(q,))['lines']==before['lines']
    assert service.db.one('SELECT state FROM quotes WHERE id=?',(q,))['state']=='superseded'
    with pytest.raises(RuleError):life.execute(ident,'start_repair')
    q2=approve(service,ident,10000);life.execute(ident,'start_repair');Parts(service).install(part,'Amit')
    assert service.db.one('SELECT total FROM quotes WHERE id=?',(q2,))['total']==105000


def test_stock_shortage_installation_is_atomic(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident);part=plan(service,ident,'stock')
    stock=Parts(service).stock()[0];Parts(service).adjust_stock(stock['id'],-2,'Physical stock correction')
    approve(service,ident);life.execute(ident,'start_repair')
    with pytest.raises(RuleError,match='Insufficient'):Parts(service).install(part,'Amit')
    assert Parts(service).rows(ident)[0]['status']=='planned'
    assert not Warranties(service).rows(service.job(ident)['device_id'])
    assert not service.db.rows('SELECT * FROM stock_movements WHERE part_id=?',(part,))


def test_install_requires_source_and_approval_and_cannot_remove_installed(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident)
    with pytest.raises(RuleError,match='Identify'):Parts(service).save(ident,dict(name='Battery',source='supplier'))
    part=plan(service,ident)
    with pytest.raises(RuleError):Parts(service).install(part,'Amit')
    approve(service,ident);life.execute(ident,'start_repair');Parts(service).install(part,'Amit')
    with pytest.raises(RuleError):Parts(service).remove(part,'Erase')
    with pytest.raises(RuleError):Parts(service).save(ident,{'name':'Changed'},part)
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:c.execute('DELETE FROM repair_parts WHERE id=?',(part,))


@pytest.mark.parametrize('start,duration,unit,expiry',[('2026-01-31',3,'months','2026-04-30'),('2026-08-31',6,'months','2027-02-28'),('2024-02-29',1,'years','2025-02-28'),('2026-09-12',90,'days','2026-12-11')])
def test_calendar_expiry(start,duration,unit,expiry):
    assert warranty_expiry(start,duration,unit)==expiry


def test_future_job_claim_links_original_and_preserves_history(service,customer):
    old,life,part,q=installed(service,customer);deliver(service,customer,old,life,100000)
    device=service.job(old)['device_id'];w=Warranties(service);warranty=w.rows(device)[0]
    before=service.job(old);oldpart=Parts(service).rows(old)[0]
    new=service.intake(customer,'Lifecycle laptop','Battery failed again',device_id=device,parent_id=old,guided=True)
    assert w.rows(device)[0]['effective_status']=='ACTIVE'
    claim=w.claim(new,warranty['id'],'Battery fails to charge')
    r=w.claims(device)[0]
    assert (r['new_job_id'],r['original_job_id'],r['part_id'],r['device_id'])==(new,old,part,device)
    w.update_claim(claim,'ACCEPTED','Defect accepted');w.update_claim(claim,'IN_REPAIR','Repair being carried out')
    assert service.job(old)==before and Parts(service).rows(old)[0]==oldpart
    assert '1 claims in progress' in life.snapshot(new)['warranty_indicator']
    assert life.rows(filter_key='warranty_claims')[0]['id']==new


def test_expired_claim_override_and_warranty_edit_permissions(service,customer):
    old,life,part,q=installed(service,customer);deliver(service,customer,old,life,100000)
    w=Warranties(service);device=service.job(old)['device_id'];wid=w.rows(device)[0]['id']
    w.edit(wid,'Correct historical installation',start_date='2020-01-31',duration=6,unit='months')
    assert w.rows(device)[0]['effective_status']=='EXPIRED'
    new=service.intake(customer,'Lifecycle laptop','Battery failed',device_id=device,guided=True)
    with pytest.raises(RuleError,match='expired'):w.claim(new,wid,'Failed again')
    owner=dict(service.user);service.save_staff('counter','Counter','counter','CounterPassword123!');service.login('counter','CounterPassword123!')
    with pytest.raises(RuleError):w.edit(wid,'Unauthorized',duration=12)
    with pytest.raises(RuleError):w.claim(new,wid,'Failed again','Owner override typed by counter')
    service.user=owner;claim=w.claim(new,wid,'Failed again','Owner goodwill exception')
    assert claim and service.db.rows("SELECT * FROM audit WHERE action='warranty_edited'")


def test_claim_replacement_must_belong_to_claim_job(service,customer):
    old,life,part,q=installed(service,customer);deliver(service,customer,old,life,100000)
    w=Warranties(service);device=service.job(old)['device_id'];wid=w.rows(device)[0]['id']
    new=service.intake(customer,'Lifecycle laptop','Battery failure',device_id=device,guided=True)
    claim=w.claim(new,wid,'Failure');w.update_claim(claim,'ACCEPTED','Accepted');w.update_claim(claim,'IN_REPAIR','Repair')
    with pytest.raises(RuleError,match='replacement'):w.update_claim(claim,'REPLACED','Replaced',part)
    assert w.claims(device)[0]['status']=='IN_REPAIR'


def test_new_tabs_show_parts_cards_and_warranty(qtbot,service,customer):
    from repairshop.ui import MainWindow
    from repairshop.lifecycle_ui import JobWorkspace
    ident,life,part,q=installed(service,customer)
    w=MainWindow(service);qtbot.addWidget(w)
    dialog=JobWorkspace(w,ident);qtbot.addWidget(dialog)
    names=[dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert {'Job Cards','Parts','Warranty'}<=set(names)
    assert 'CARD-04' in dialog.heading.text() and '1 active warranties' in dialog.heading.text()
    assert dialog.record_tabs[1].grid.rowCount()==1


def test_repair_warranty_is_structured_and_audited(service,customer):
    ident,life,part,q=installed(service,customer)
    w=Warranties(service);wid=w.repair_warranty(ident,'Workmanship',date.today().isoformat(),6,'months','Our shop','Labour only')
    row=service.db.one('SELECT * FROM part_warranties WHERE id=?',(wid,))
    assert row['part_id'] is None and row['source']=='repair' and row['expiry']==warranty_expiry(date.today().isoformat(),6,'months')


def test_claim_replacement_full_flow_and_dashboard_filters(service,customer):
    old,life,oldpart,q=installed(service,customer);deliver(service,customer,old,life,100000)
    device=service.job(old)['device_id'];w=Warranties(service);wid=w.rows(device)[0]['id']
    new=service.intake(customer,'Lifecycle laptop','Battery failed',device_id=device,guided=True)
    claim=w.claim(new,wid,'Failure');w.update_claim(claim,'ACCEPTED','Accepted')
    life.execute(new,'inspect');life.execute(new,'inspection_done',{'notes':'Failure reproduced'})
    life.execute(new,'verify_warranty',dict(warranty_status='out_of_warranty',notes='Manufacturer expired; shop part claim accepted'))
    life.execute(new,'select_route',dict(route='in_house',confirmed=True,technician_id=service.user['id']))
    diagnosis(life,new);part=plan(service,new,price=0);approve(service,new,0)
    life.execute(new,'start_repair');w.update_claim(claim,'IN_REPAIR','Replacing under part warranty');Parts(service).install(part,'Amit')
    w.update_claim(claim,'REPLACED','Replacement installed',part)
    life.execute(new,'complete_repair',{'notes':'Replaced battery'});life.execute(new,'test',dict(result='passed',notes='Passed'));qc(life,new)
    w.update_claim(claim,'COMPLETED','Repair and QC passed')
    life.execute(new,'bill',{'confirmed':True});life.execute(new,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,received_by='Owner',acknowledgment='Signed'))
    with pytest.raises(RuleError,match='claim'):life.execute(new,'close')
    w.update_claim(claim,'CLOSED','Delivered');life.execute(new,'close')
    assert service.db.one('SELECT status FROM part_warranties WHERE id=?',(wid,))['status']=='REPLACED'
    assert len(life.rows(filter_key='collected'))==life.dashboard_counts()['collected']==2
    assert life.dashboard_counts()['warranty_claims']==0


def test_schema6_upgrade_does_not_invent_cards(service,customer,job,tmp_path):
    from repairshop.persistence import Database
    from repairshop.backup import Backups
    import shutil
    target=tmp_path/'schema6';shutil.copytree(service.db.root,target,ignore=shutil.ignore_patterns('shop.db*'))
    with service.db.read() as source:
        with sqlite3.connect(target/'shop.db') as c:source.driver_connection.backup(c)
    with sqlite3.connect(target/'shop.db') as c:
        for table in ('manual_warranty_checks','category_services','warranty_claims','part_warranties','stock_movements','repair_parts','stock_items','job_cards'):c.execute('DROP TABLE '+table)
        c.execute('PRAGMA user_version=6')
    upgraded=Database(target)
    assert upgraded.rows('SELECT * FROM job_cards')==[]
    assert upgraded.rows('SELECT * FROM entries')==service.db.rows('SELECT * FROM entries')
    assert upgraded.rows('SELECT * FROM devices')==service.db.rows('SELECT * FROM devices')
    archive=list((target/'backups').glob('*pre-upgrade-v6*.zip'))[0]
    assert Backups.validate(archive)['schema']==6


def test_parts_reports_and_customer_folder_history(service,customer):
    from repairshop.queries import Queries
    from repairshop.customer_records import CustomerRecords
    ident,life,part,q=installed(service,customer)
    reports=Queries(service)
    assert reports.report('repair_parts','2000-01-01','2099-01-01')[0]['margin']==50000
    assert reports.report('part_warranties','2000-01-01','2099-01-01')[0]['status']=='ACTIVE'
    assert [r['kind'] for r in reports.report('job_cards','2000-01-01','2099-01-01')]==['customer_receiving','in_house_assignment','in_house_handover','in_house_return']
    assert reports.report('warranty_claims','2000-01-01','2099-01-01')==[]
    folder=CustomerRecords(service).sync_customer(customer)
    text=next(folder.rglob('customer-job-summary.txt')).read_text(encoding='utf-8')
    # The customer summary carries their own warranty, not the shop's parts ledger.
    assert 'Warranty' in text and 'Accessories Received' in text
    assert 'Repair Parts' not in text and 'Job Cards' not in text
    internal=next((service.db.root/'Internal').rglob('internal-job-details.txt')).read_text(encoding='utf-8')
    assert 'Repair Parts' in internal and 'Part Warranties' in internal and 'Job Cards' in internal


def test_window_closes_after_background_work_without_blocking_dialog(qtbot,service,monkeypatch):
    import threading
    from repairshop.ui import MainWindow
    from PyQt6.QtWidgets import QMessageBox
    w=MainWindow(service);qtbot.addWidget(w);w.show()
    started,release=threading.Event(),threading.Event()
    def work():
        started.set();release.wait(5)
        return True
    def no_modal(*args):raise AssertionError('Closing must not block in a modal dialog')
    monkeypatch.setattr(QMessageBox,'information',no_modal)
    w.run(work,refresh=False)
    try:
        qtbot.waitUntil(started.is_set,timeout=2000)
        w.close()
        assert w.close_when_idle and w.isVisible()
    finally:
        release.set()
    qtbot.waitUntil(lambda:not w.isVisible(),timeout=4000)
    assert w.closing and not w.tasks


def test_covered_service_center_parts_still_have_clear_approval_action(service,customer):
    ident,life=route(service,customer,'warranty_centre',True);dispatch(service,ident,life);diagnosis(life,ident)
    part=plan(service,ident,price=0)
    life.execute(ident,'warranty_result',dict(decision='accepted',notes='OEM covered board replacement'))
    assert life.snapshot(ident)['primary']=='quote'
    approve(service,ident,0);life.execute(ident,'start_repair');Parts(service).install(part,'Service center')
    life.execute(ident,'complete_repair',dict(notes='Warranty part replaced'))
    life.execute(ident,'receive',dict(counterparty='Shop',condition='Intact',acknowledgment='OEM return'))
    qc(life,ident);deliver(service,customer,ident,life,0)
