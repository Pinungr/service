import json
import sqlite3
import shutil
import pytest
from datetime import date
from repairshop.inventory import Inventory
from repairshop.parts import Parts
from repairshop.costing import JobCosts
from repairshop.warranties import Warranties
from repairshop.job_cards import JobCards
from repairshop.documents import Documents
from repairshop.domain import RuleError
from repairshop.persistence import Database
from repairshop.lifecycle import Lifecycle
from test_lifecycle import route,dispatch,diagnosis,approve,qc,deliver,fresh
from test_parts_cards_warranty import installed


def stock(s,quantity=5,**extra):
    inv=Inventory(s)
    ident=inv.save(dict(name='Dell Battery 54Wh',sku='BAT-DELL-001',compatibility='Inspiron 15',purchase_cost=250000,customer_price=320000,
        warranty_duration=6,warranty_unit='months',warranty_provider='Our shop',storage='Shelf B',minimum_stock=2,**extra))
    inv.adjust(ident,quantity,'INV-100')
    return inv,ident


def required(s,job,inventory_id,**values):
    return Parts(s).save(job,dict(source='stock',inventory_id=inventory_id,**values))


def test_technician_can_return_device_for_route_change_without_skipping_repair(service,customer):
    job,life=route(service,customer)
    assert 'return_technician' in life.snapshot(job)['actions']
    life.execute(job,'return_technician',dict(condition='Intact',acknowledgment='Returned for specialist assessment'))
    assert service.job(job)['stage']=='diagnosis'
    assert life.snapshot(job)['current_custodian']==service.db.setting('shop_name')
    vendor=service.save_master('vendor','Board specialist')
    life.execute(job,'change_route',dict(route='third_party',contact_id=vendor,confirmed=True))
    assert service.job(job)['stage']=='ready_dispatch'


def test_two_connections_cannot_reserve_same_last_unit(service,customer):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from repairshop.services import Service
    inv,ident=stock(service,1)
    jobs=[route(service,customer)[0] for _ in range(2)]
    parts=[required(service,j,ident) for j in jobs]
    other=Service(Database(service.db.root));other.user=dict(service.user)
    barrier=Barrier(2)
    def reserve(pair):
        s,part=pair;barrier.wait(timeout=5)
        try:Inventory(s).transfer(part,'reserve','Simultaneous reservation');return True
        except RuleError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,zip((service,other),parts)))
    assert sorted(results)==[False,True]
    assert inv.rows()[0]['available']==0 and inv.rows()[0]['reserved']==1


@pytest.mark.parametrize('action',['damaged','scrapped'])
def test_issued_stock_writeoff_releases_commitment_and_preserves_event(service,customer,action):
    job,life=route(service,customer);inv,ident=stock(service,1);part=required(service,job,ident)
    inv.transfer(part,'reserve','Reserved');inv.transfer(part,'issue','Signed')
    inv.transfer(part,action,'Documented damage / disposal')
    row=inv.rows()[0];assert row['stock']==row['issued']==row['available']==0
    assert inv.movements(ident)[0]['kind']==action.upper()


def test_catalog_receive_search_low_stock_and_immutable_ledger(service):
    inv,ident=stock(service,2,brand='Dell',model='B54',batch='B2026')
    row=inv.rows('Inspiron','low')[0]
    assert (row['stock'],row['available'],row['reserved'],row['issued'])==(2,2,0,0)
    assert not inv.rows(view='out')
    inv.adjust(ident,-2,'Damaged batch','Packing crushed',kind='DAMAGED')
    assert inv.rows(view='out')[0]['id']==ident
    with pytest.raises(RuleError,match='Insufficient'):inv.adjust(ident,-1,'Bad correction')
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:c.execute('UPDATE stock_movements SET delta=9')
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:c.execute('DELETE FROM stock_movements')


def test_stock_receipt_retry_and_markup(service):
    inv=Inventory(service);ident=inv.save(dict(name='Fan',purchase_cost=10000,markup_basis_points=2500))
    assert inv.rows()[0]['customer_price']==12500
    first=inv.adjust(ident,3,'Invoice',operation_id='receipt-1')
    assert inv.adjust(ident,3,'Invoice',operation_id='receipt-1')==first
    with pytest.raises(RuleError):inv.adjust(ident,8,'Invoice',operation_id='receipt-1')
    assert inv.rows()[0]['stock']==3


@pytest.mark.parametrize('kind',['in_house','third_party'])
def test_reserve_issue_return_then_install_and_warranty_snapshot(service,customer,kind):
    job,life=route(service,customer,kind)
    if kind!='in_house':dispatch(service,job,life)
    diagnosis(life,job);inv,ident=stock(service);part=required(service,job,ident)
    inv.transfer(part,'reserve','Reserved for device')
    assert (inv.rows()[0]['available'],inv.rows()[0]['reserved'],inv.rows()[0]['stock'])==(4,1,5)
    with pytest.raises(RuleError):inv.adjust(ident,-5,'Cannot remove reserved units')
    inv.transfer(part,'issue','Repairer signed')
    assert (inv.rows()[0]['issued'],inv.rows()[0]['reserved'],inv.rows()[0]['stock'])==(1,0,5)
    assert JobCards(service).rows(job)[-1]['kind']=='part_transfer'
    with pytest.raises(RuleError,match='Release|return'):Parts(service).remove(part,'Cancel')
    inv.transfer(part,'return','Returned unused')
    assert inv.rows()[0]['available']==5
    inv.transfer(part,'reserve','Reserved again');inv.transfer(part,'issue','Issued again')
    approve(service,job,150000);life.execute(job,'start_repair');Parts(service).install(part,'Repairer')
    assert (inv.rows()[0]['stock'],inv.rows()[0]['available'],inv.rows()[0]['issued'])==(4,4,0)
    warranty=Warranties(service).rows(service.job(job)['device_id'])[0]
    inv.save({'warranty_duration':12,'customer_price':360000},ident)
    assert Warranties(service).rows(service.job(job)['device_id'])[0]==warranty
    assert Parts(service).rows(job)[0]['warranty_duration']==6
    assert inv.movements(stock_id=ident)[0]['kind']=='INSTALLED'
    assert any('Stock Movement' in e['event'] for e in life.timeline(job))


def test_reservations_cannot_oversell_and_failed_transfer_is_atomic(service,customer,monkeypatch):
    inv,ident=stock(service,1);j1,_=route(service,customer);j2,_=route(service,customer)
    p1=required(service,j1,ident);p2=required(service,j2,ident)
    inv.transfer(p1,'reserve','First reservation')
    with pytest.raises(RuleError,match='Insufficient'):inv.transfer(p2,'reserve','Second reservation')
    before=inv.rows();events=len(inv.movements())
    def fail(*a,**k):raise RuntimeError('Failed transfer card write')
    monkeypatch.setattr(JobCards,'issue',fail)
    with pytest.raises(RuntimeError):inv.transfer(p1,'issue','Signed')
    assert inv.rows()==before and len(inv.movements())==events
    assert Parts(service).rows(j1)[0]['stock_state']=='reserved'


def test_serialized_and_generic_parts(service,customer):
    inv=Inventory(service)
    with pytest.raises(RuleError,match='serial'):inv.save(dict(name='SSD',serialized=True))
    ident=inv.save(dict(name='SSD',serialized=True,serial='SSD-0001'))
    with pytest.raises(RuleError,match='one unit'):inv.adjust(ident,2,'Purchase')
    inv.adjust(ident,1,'Purchase')
    with pytest.raises(RuleError,match='serial'):inv.save(dict(name='Duplicate SSD',serialized=True,serial='SSD-0001'))
    job,_=route(service,customer)
    with pytest.raises(RuleError,match='quantity of one'):required(service,job,ident,quantity=2)
    p=required(service,job,ident)
    assert Parts(service).rows(job)[0]['serial']=='SSD-0001'
    inv.transfer(p,'reserve','Reserve SSD')
    with pytest.raises(RuleError):inv.save(dict(serial='Different'),ident)
    generic=inv.save(dict(name='Thermal paste'))
    inv.adjust(generic,20,'Generic stock')
    assert next(r for r in inv.rows() if r['id']==generic)['available']==20


def test_third_party_supplier_is_locked_and_external_supplier_is_distinct(service,customer):
    job,life=route(service,customer,'third_party');dispatch(service,job,life);diagnosis(life,job)
    assigned=service.db.one('SELECT contact_id FROM assignments WHERE id=?',(service.job(job)['assignment_id'],))['contact_id']
    other=service.save_master('vendor','Unrelated business')
    with pytest.raises(RuleError,match='currently assigned'):Parts(service).save(job,dict(name='Charging IC',source='technician',supplier_id=other,purchase_cost=120000,customer_price=180000))
    part=Parts(service).save(job,dict(name='Charging IC',source='technician',purchase_cost=120000,customer_price=180000,requested_by='Assigned vendor',request_notes='Charging circuit failed'))
    assert Parts(service).rows(job)[0]['supplier_id']==assigned
    external=Parts(service).save(job,dict(name='Connector',source='supplier',supplier_id=other,purchase_cost=10000,customer_price=15000))
    Parts(service).procure(external,'order','PO-10');Parts(service).procure(external,'receive','INV-10')
    assert next(r for r in Parts(service).rows(job) if r['id']==external)['procurement_status']=='received'
    JobCosts(service).save(job,dict(vendor_labour=80000,transport_cost=20000,vendor_invoice='V-100'),'Vendor estimate')
    q=approve(service,job,150000)
    costs=JobCosts(service).summary(job)
    assert costs['vendor_parts']==120000 and costs['vendor_labour']==80000 and costs['total_internal']==230000
    assert costs['customer_total']==345000 and costs['expected_margin']==115000
    assert 'purchase_cost' not in service.db.one('SELECT lines FROM quotes WHERE id=?',(q,))['lines']


@pytest.mark.parametrize('kind,warranty',[('third_party',False),('warranty_centre',True)])
def test_courier_outbound_and_reverse_custody_cards_are_consistent(service,customer,kind,warranty):
    job,life=route(service,customer,kind,warranty)
    life.execute(job,'prepare_dispatch',dict(items=[r['id'] for r in life.holdings(job)],consent=True,condition='Intact'))
    life.execute(job,'dispatch',dict(carrier='DTDC',counterparty='Driver',condition='Packed',acknowledgment='AWB-100'))
    v=life.snapshot(job)
    assert v['current_location']=='IN TRANSIT' and v['current_custodian']=='DTDC'
    assert 'AT SERVICE CENTER' not in v['current_status'] and 'WITH THIRD' not in v['current_status']
    card=json.loads(JobCards(service).rows(job)[-1]['snapshot'])
    assert card['to']['name']=='DTDC' and card['final_destination']==v['assignment']['party']
    assert card['kind']=='carrier_dispatch'
    with pytest.raises(RuleError):life.execute(job,'diagnose',dict(notes='Cannot diagnose in transit'))
    life.execute(job,'arrive',dict(counterparty='Repairer',condition='Intact',acknowledgment='Arrived'))
    card=json.loads(JobCards(service).rows(job)[-1]['snapshot'])
    assert card['from']['name']=='DTDC' and card['to']['name']==v['assignment']['party']
    diagnosis(life,job)
    if warranty:life.execute(job,'warranty_result',dict(decision='accepted',notes='Covered',rma='W100'))
    else:approve(service,job,0)
    life.execute(job,'start_repair');life.execute(job,'complete_repair',dict(notes='Repaired power circuit'))
    life.execute(job,'return_dispatch',dict(carrier='Blue Dart',counterparty='Return driver',condition='Packed',acknowledgment='AWB-200'))
    v=life.snapshot(job)
    assert v['current_location']=='IN TRANSIT' and v['current_custodian']=='Blue Dart' and v['primary']=='receive'
    assert v['final_destination']=='Test Repair Shop' and 'RETURN DISPATCHED' in v['current_status']
    life.execute(job,'receive',dict(counterparty='Counter',condition='Intact',acknowledgment='Received return',repair_result='REPAIRED',vendor_invoice='V-200'))
    v=life.snapshot(job);assert v['current_custodian']=='Test Repair Shop' and not v['final_destination']
    card=json.loads(JobCards(service).rows(job)[-1]['snapshot'])
    assert card['from']['name']=='Blue Dart' and card['to']['name']=='Test Repair Shop'
    assert card['return_details']['work_performed']=='Repaired power circuit' and card['return_details']['vendor_invoice']=='V-200'
    if warranty:assert card['return_details']['warranty_decision']['rma']=='W100'


def test_in_house_assignment_handover_and_return_are_separate(service,customer):
    job,life=fresh(service,customer);life.execute(job,'inspect');life.execute(job,'inspection_done',dict(notes='Checked'))
    life.execute(job,'verify_warranty',dict(warranty_status='out_of_warranty',notes='No manufacturer warranty'))
    life.execute(job,'select_route',dict(route='in_house',technician_id=service.user['id'],confirmed=True))
    v=life.snapshot(job)
    assert v['primary']=='hand_technician' and v['current_custodian']=='Test Repair Shop'
    assert v['assigned_technician']=='Owner' and 'Front desk' in v['current_location']
    assert not service.db.rows("SELECT * FROM movements WHERE to_location LIKE 'technician:%'")
    life.execute(job,'hand_technician',dict(bench='Bench 2',condition='Intact',acknowledgment='Signed by technician'))
    v=life.snapshot(job);assert v['current_custodian']=='Owner' and 'Bench 2' in v['current_location']
    diagnosis(life,job);approve(service,job,0);life.execute(job,'start_repair');life.execute(job,'complete_repair',dict(notes='Repaired'))
    life.execute(job,'test',dict(result='passed',notes='Pass'))
    assert life.snapshot(job)['primary']=='return_technician'
    with pytest.raises(RuleError,match='Return the device'):life.execute(job,'qc',dict(notes='Cannot QC before return'))
    life.execute(job,'return_technician',dict(storage='shop:QC Area',condition='Intact',acknowledgment='QC received'))
    assert life.snapshot(job)['current_custodian']=='Test Repair Shop' and life.snapshot(job)['primary']=='qc'
    assert [r['kind'] for r in JobCards(service).rows(job)]==['customer_receiving','in_house_assignment','in_house_handover','in_house_return']


def test_return_snapshot_costs_and_parts_are_permanent_and_customer_safe(service,customer,monkeypatch):
    job,life=route(service,customer,'third_party');dispatch(service,job,life);diagnosis(life,job)
    inv,ident=stock(service);part=required(service,job,ident)
    inv.transfer(part,'reserve','Reserve');inv.transfer(part,'issue','Vendor signed')
    JobCosts(service).save(job,dict(vendor_labour=80000,transport_cost=20000,vendor_invoice='INV-333'),'Budget')
    approve(service,job,150000);life.execute(job,'start_repair');Parts(service).install(part,'Assigned vendor')
    life.execute(job,'complete_repair',dict(notes='Battery replaced'))
    life.execute(job,'receive',dict(counterparty='Counter',condition='Good',acknowledgment='Returned'))
    card=JobCards(service).rows(job)[-1];saved=card['snapshot'];result=json.loads(saved)['return_details']
    assert result['costs']['total_internal']==350000 and result['costs']['expected_margin']==120000
    assert result['repair_status']=='Received at shop; final quality check pending'
    assert result['repairer']==life.snapshot(job)['assignment']['party']
    assert result['parts_installed'][0]['source']=='stock' and result['parts_installed'][0]['warranty_duration']==6
    captured=[]
    monkeypatch.setattr(Documents,'snapshot',lambda self,title,sections,*a,**kw:captured.append(sections))
    JobCards(service).print(card['id']);public=json.dumps(captured[-1])
    assert '3500' not in public and '2500' not in public and 'margin' not in public.lower()
    JobCards(service).print(card['id'],internal=True);assert '3,500' in json.dumps(captured[-1])
    JobCosts(service).save(job,dict(vendor_labour=99900),'Late corrected budget')
    assert service.db.one('SELECT snapshot FROM job_cards WHERE id=?',(card['id'],))['snapshot']==saved


def test_counter_views_and_documents_do_not_expose_internal_cost(service,customer,monkeypatch):
    job,life=route(service,customer,'third_party');dispatch(service,job,life);diagnosis(life,job);inv,ident=stock(service)
    part=required(service,job,ident);JobCosts(service).save(job,dict(vendor_labour=87321,in_house_cost=76543),'Private budget')
    owner=dict(service.user);service.save_staff('counter','Counter','counter','CounterPassword123!');service.login('counter','CounterPassword123!')
    for data in (inv.rows(),Parts(service).rows(job),life.snapshot(job),life.timeline(job)):
        text=json.dumps(data);assert 'purchase_cost' not in text and '87321' not in text and '76543' not in text
    with pytest.raises(RuleError):JobCosts(service).summary(job)
    with pytest.raises(RuleError):Parts(service).save(job,dict(purchase_cost=1),part)
    with pytest.raises(RuleError):life.execute(job,'details',dict(vendor_labour=1))
    life.execute(job,'details',dict(notes='Counter progress update'))
    service.user=owner;assert JobCosts(service).summary(job)['vendor_labour']==87321


@pytest.mark.parametrize('result',['VALID','INVALID','UNVERIFIED'])
def test_manual_warranty_check_does_not_invent_history(service,customer,result):
    job,life=fresh(service,customer);life.execute(job,'inspect');life.execute(job,'inspection_done',dict(notes='Checked'))
    ident=Warranties(service).manual_check(job,result,'Warranty slip','OLD-123','Our shop','shop_part','Original printed slip checked')
    assert Warranties(service).manual_checks(job)[0]['id']==ident
    assert not service.db.rows('SELECT * FROM part_warranties') and not service.db.rows('SELECT * FROM stock_movements')
    assert service.job(job)['stage']==('route_selection' if result=='VALID' else 'warranty_check')
    if result=='VALID':
        life.execute(job,'select_route',dict(route='in_house',technician_id=service.user['id'],confirmed=True))
        assert life.snapshot(job)['warranty_status']=='shop_warranty'


def test_active_claim_locks_normal_edits_and_rejection_restores_effective_warranty(service,customer):
    old,life,part,q=installed(service,customer);deliver(service,customer,old,life,100000)
    w=Warranties(service);device=service.job(old)['device_id'];wid=w.rows(device)[0]['id']
    new=service.intake(customer,'Same device','Battery fault',device_id=device,guided=True)
    claim=w.claim(new,wid,'Battery fault')
    for state in ('OPEN','ACCEPTED','IN_REPAIR'):
        if state!='OPEN':w.update_claim(claim,state,'Evidence reviewed')
        assert w.rows(device)[0]['effective_status']=='CLAIM IN PROGRESS'
        with pytest.raises(RuleError,match='MANAGED BY ACTIVE CLAIM'):w.edit(wid,'Ordinary correction',status='ACTIVE')
    w.edit(wid,'Exceptional owner correction of coverage',privileged_override=True,terms='Updated coverage wording')
    assert w.rows(device)[0]['effective_status']=='CLAIM IN PROGRESS'
    assert service.db.one("SELECT payload FROM audit WHERE action='warranty_admin_override'")
    # Rejection is permitted while reviewing an accepted claim before repair.
    other=service.intake(customer,'Another device','Other fault',guided=True)
    with pytest.raises(RuleError):w.claim(other,wid,'Different device')


def test_rejected_claim_does_not_permanently_mark_warranty_claimed(service,customer):
    old,life,_,_=installed(service,customer);deliver(service,customer,old,life,100000)
    w=Warranties(service);device=service.job(old)['device_id'];wid=w.rows(device)[0]['id']
    new=service.intake(customer,'Same device','Fault',device_id=device,guided=True);claim=w.claim(new,wid,'Fault')
    w.update_claim(claim,'REJECTED','Reported symptom is not a covered defect')
    assert w.rows(device)[0]['effective_status']=='ACTIVE' and not w.active_claim(wid)
    w.edit(wid,'After rejection coverage correction',terms='Original coverage')


def test_v8_migration_preserves_installed_history_and_balances(service,customer,tmp_path):
    old,life,part,_=installed(service,customer,source='stock')
    target=tmp_path/'v8';shutil.copytree(service.db.root,target,ignore=shutil.ignore_patterns('shop.db*'))
    with service.db.read() as source:
        with sqlite3.connect(target/'shop.db') as c:source.driver_connection.backup(c)
    with sqlite3.connect(target/'shop.db') as c:
        from schema_fixtures import remove_v9
        remove_v9(c)
        before_cards=c.execute('SELECT snapshot FROM job_cards ORDER BY id').fetchall()
        before_stock=c.execute('SELECT sum(delta) FROM stock_movements').fetchone()[0]
    upgraded=Database(target)
    assert upgraded.one('PRAGMA user_version')['user_version']==9
    assert [r['snapshot'] for r in upgraded.rows('SELECT snapshot FROM job_cards ORDER BY id')]==[r[0] for r in before_cards]
    assert upgraded.one('SELECT sum(delta) n FROM stock_movements')['n']==before_stock
    assert upgraded.one('SELECT stock_state FROM repair_parts WHERE id=?',(part,))['stock_state']=='installed'
    from repairshop.backup import Backups
    archive=list((target/'backups').glob('*pre-upgrade-v8*.zip'))[0];assert Backups.validate(archive)['schema']==8
