import json
import sqlite3
import uuid
import pytest
from repairshop.lifecycle import Lifecycle
from repairshop.domain import RuleError, in_shop


def fresh(s,customer):
    ident=s.intake(customer,'Lifecycle laptop','No power',guided=True,
        accessories=[dict(type='accessory',description='Adapter',quantity=1)])
    return ident,Lifecycle(s)


def route(s,customer,kind='in_house',warranty=False):
    ident,life=fresh(s,customer)
    life.execute(ident,'inspect')
    life.execute(ident,'inspection_done',{'notes':'Power fault confirmed; condition checked'})
    life.execute(ident,'verify_warranty',{'warranty_status':'under_warranty' if warranty else 'out_of_warranty','notes':'Purchase evidence reviewed'})
    p={'route':kind,'confirmed':True,'technician_id':s.user['id']}
    if kind=='in_house':p.update(handed_over=True,bench='Bench 2',condition='Intact',acknowledgment='Technician received')
    if kind!='in_house':
        p['contact_id']=s.save_master('centre' if kind=='warranty_centre' else 'vendor',kind+' test')
    life.execute(ident,'select_route',p)
    return ident,life


def dispatch(s,ident,life,carrier=''):
    life.execute(ident,'prepare_dispatch',dict(items=[r['id'] for r in life.holdings(ident)],consent=True,condition='Intact',expected_return='2099-01-01'))
    life.execute(ident,'dispatch',dict(counterparty='Courier' if carrier else 'Repairer',condition='Intact',acknowledgment='Receipt D1',carrier=carrier))
    if carrier:
        assert 'IN TRANSIT' in life.snapshot(ident)['current_location']
        life.execute(ident,'arrive',dict(counterparty='Repairer',condition='Intact',acknowledgment='Arrival A1'))


def diagnosis(life,ident,repairable=True,parts=True):
    if 'hand_technician' in life.snapshot(ident)['actions']:
        life.execute(ident,'hand_technician',dict(bench='Bench 2',condition='Intact',acknowledgment='Technician received device'))
    life.execute(ident,'diagnose',dict(notes='Faulty power board',repairable=repairable,parts='Power board',parts_available=parts))


def approve(s,ident,total=120000):
    q=s.issue_quote(ident,'Replace power board',[{'description':'Parts and labour','amount':total}])
    s.decide_quote(q,'approved','Device owner','in_person')
    return q


def complete(life,ident,external=False):
    life.execute(ident,'start_repair')
    life.execute(ident,'complete_repair',dict(notes='Power board replaced',parts='Power board'))
    if external:
        life.execute(ident,'receive',dict(counterparty='Counter staff',condition='Intact',acknowledgment='Return R1'))
    else:
        life.execute(ident,'test',dict(result='passed',notes='Power on test passed'))


def qc(life,ident,result='passed'):
    if 'return_technician' in life.snapshot(ident)['actions']:
        life.execute(ident,'return_technician',dict(condition='Intact',acknowledgment='QC counter received'))
    life.execute(ident,'qc',dict(result=result,notes='Original fault verified',condition_checked=True,
        checks={k:'passed' for k in ('functional','power','charging','display','connectivity','complaint')},repair_warranty='90 days workmanship',warranty_until='2099-01-01'))


def deliver(s,customer,ident,life,total=120000):
    life.execute(ident,'bill',{'confirmed':True})
    if total:
        s.post('customer',customer,'receipt',total,uuid.uuid4().hex,job_id=ident)
    life.execute(ident,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,
        received_by='Owner',acknowledgment='Signed receipt'))
    assert life.snapshot(ident)['current_status']=='DELIVERED'
    assert life.snapshot(ident)['current_location']=='WITH CUSTOMER'
    life.execute(ident,'close')
    assert s.job(ident)['stage']=='closed'


def test_in_house_full_flow_payment_and_history(service,customer):
    ident,life=route(service,customer)
    diagnosis(life,ident);approve(service,ident);complete(life,ident);qc(life,ident)
    life.execute(ident,'bill',{'confirmed':True})
    assert life.snapshot(ident)['next_action']=='Collect remaining payment'
    assert life.snapshot(ident)['current_status']=='READY FOR DELIVERY'
    with pytest.raises(RuleError,match='credit'):
        life.execute(ident,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,received_by='Owner',acknowledgment='Signed'))
    assert 'IN SHOP' in life.snapshot(ident)['current_location']
    service.post('customer',customer,'receipt',120000,'paid',job_id=ident)
    life.execute(ident,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,received_by='Owner',acknowledgment='Signed'))
    life.execute(ident,'close')
    events=life.timeline(ident)
    assert len(events)>12 and all(e['actor'] for e in events)
    assert service.job(ident)['actual_collection']
    assert all(h['location']=='customer' for h in life.holdings(ident))
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:c.execute("DELETE FROM audit WHERE entity='job' AND entity_id=?",(ident,))


def test_warranty_center_happy_path(service,customer):
    ident,life=route(service,customer,'warranty_centre',True)
    dispatch(service,ident,life,carrier='Test courier')
    assert 'AUTHORIZED SERVICE CENTER' in life.snapshot(ident)['current_location']
    diagnosis(life,ident)
    life.execute(ident,'warranty_result',{'decision':'accepted','notes':'Covered by OEM','covered':'Power board'})
    complete(life,ident,True)
    assert life.snapshot(ident)['primary']=='qc'
    assert 'IN SHOP' in life.snapshot(ident)['current_location']
    qc(life,ident);deliver(service,customer,ident,life,0)
    assert not service.db.one("SELECT * FROM entries WHERE job_id=?",(ident,))


def test_third_party_happy_path(service,customer):
    ident,life=route(service,customer,'third_party');dispatch(service,ident,life)
    diagnosis(life,ident);approve(service,ident)
    vendor=life.snapshot(ident)['assignment']['contact_id']
    service.post('vendor',vendor,'charge',80000,'vendor-bill',job_id=ident)
    service.post('vendor',vendor,'payment',80000,'vendor-paid',job_id=ident)
    complete(life,ident,True);qc(life,ident);deliver(service,customer,ident,life)
    assert service.db.one("SELECT sum(amount) n FROM entries WHERE account_type='vendor'")['n']==0


def test_warranty_rejection_receive_then_switch(service,customer):
    ident,life=route(service,customer,'warranty_centre',True);dispatch(service,ident,life);diagnosis(life,ident)
    life.execute(ident,'warranty_result',{'decision':'rejected','notes':'Liquid damage excluded'})
    with pytest.raises(RuleError):life.execute(ident,'change_route',{'route':'in_house','confirmed':True,'technician_id':service.user['id']})
    life.execute(ident,'decline',{'notes':'Return for shop repair','reason':'Warranty rejected'})
    life.execute(ident,'receive',dict(counterparty='Shop',condition='Unrepaired',acknowledgment='R2'))
    life.execute(ident,'change_route',{'route':'in_house','confirmed':True,'technician_id':service.user['id']})
    diagnosis(life,ident);approve(service,ident);complete(life,ident);qc(life,ident)
    deliver(service,customer,ident,life)
    assert service.job(ident)['route']=='in_house'


@pytest.mark.parametrize('kind',['in_house','third_party'])
def test_unsuccessful_repair_returns_without_false_qc(service,customer,kind):
    ident,life=route(service,customer,kind)
    if kind!='in_house':dispatch(service,ident,life)
    diagnosis(life,ident);approve(service,ident);life.execute(ident,'start_repair')
    life.execute(ident,'repair_failed',{'notes':'Board is not recoverable'})
    if kind!='in_house':life.execute(ident,'receive',dict(counterparty='Shop',condition='Unrepaired',acknowledgment='R1'))
    qc(life,ident);deliver(service,customer,ident,life,0)
    assert service.job(ident)['test_result']=='checked_unrepaired'


def test_wait_for_parts_blocks_start_and_resumes(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident,parts=False)
    approve(service,ident)
    with pytest.raises(RuleError,match='parts'):life.execute(ident,'start_repair')
    life.execute(ident,'wait_parts',{'notes':'Power board ordered PO100'})
    assert life.snapshot(ident)['current_status']=='WAITING FOR PARTS'
    life.execute(ident,'parts_received',{'notes':'PO100 received and checked'})
    assert service.job(ident)['stage']=='approved'
    life.execute(ident,'start_repair')


def test_qc_failure_requires_rework_and_new_tests(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident);approve(service,ident);complete(life,ident)
    qc(life,ident,'failed')
    assert service.job(ident)['stage']=='diagnosis'
    with pytest.raises(RuleError):life.execute(ident,'bill',{'confirmed':True})
    diagnosis(life,ident);approve(service,ident);complete(life,ident);qc(life,ident)
    deliver(service,customer,ident,life)


def test_declined_quote_and_not_repairable(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident)
    q=service.issue_quote(ident,'Repair',[dict(description='Work',amount=100000)])
    service.decide_quote(q,'declined','Customer','call','Too expensive')
    assert service.job(ident)['stage']=='return_unrepaired'
    qc(life,ident);deliver(service,customer,ident,life,0)


def test_invalid_transitions_and_old_api_cannot_bypass(service,customer):
    ident,life=fresh(service,customer)
    for action in ('start_repair','receive','qc','handover','close'):
        with pytest.raises(RuleError):life.execute(ident,action)
    with pytest.raises(RuleError,match='guided'):service.stage(ident,'closed')
    with pytest.raises(RuleError,match='guided'):service.assign(ident,'in_house')
    h=life.holdings(ident)[0]
    with pytest.raises(RuleError,match='guided'):service.move(h['id'],1,h['location'],'vendor:Fake','Fake','illegal')
    with pytest.raises(RuleError,match='diagnosis'):approve(service,ident)


def test_qc_pass_requires_checklist_and_staff_permission(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident);approve(service,ident);complete(life,ident)
    life.execute(ident,'return_technician',dict(condition='Intact',acknowledgment='Returned to QC'))
    with pytest.raises(RuleError,match='checks'):life.execute(ident,'qc',{'result':'passed','notes':'Skipped checks'})
    service.save_staff('other','Other technician','technician','TestPassword123')
    service.login('other','TestPassword123')
    with pytest.raises(RuleError,match='assigned'):qc(life,ident)


def test_legacy_snapshot_preserves_data_and_explicit_adoption(service,job):
    life=Lifecycle(service);original=service.job(job)
    assert 'LEGACY' in life.snapshot(job)['current_status']
    assert service.job(job)==original
    life.execute(job,'adopt',{'confirmed':True,'notes':'Reviewed intake and custody'})
    assert service.job(job)['number']==original['number']
    assert service.job(job)['stage']==original['stage']
    assert service.job(job)['device_id']==original['device_id']


def test_compound_handover_rolls_back_all_items(service,customer,monkeypatch):
    ident,life=route(service,customer);diagnosis(life,ident,False);qc(life,ident)
    life.execute(ident,'bill',{'confirmed':True})
    original=service.move;calls=[]
    def fail_second(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('Simulated disk failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(service,'move',fail_second)
    with pytest.raises(RuntimeError):life.execute(ident,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,received_by='Owner',acknowledgment='Signed'))
    assert all(in_shop(h['location']) for h in life.holdings(ident))
    assert not service.job(ident)['actual_collection']


def test_stale_action_and_invalid_master_do_not_write(service,customer):
    ident,life=fresh(service,customer);version=service.job(ident)['version'];life.execute(ident,'inspect')
    with pytest.raises(RuleError,match='changed'):life.execute(ident,'inspection_done',{'notes':'Old form'},version)
    life.execute(ident,'inspection_done',{'notes':'Checked'})
    life.execute(ident,'verify_warranty',{'warranty_status':'out_of_warranty','notes':'Verified'})
    wrong=service.save_master('centre','Wrong type')
    with pytest.raises(RuleError,match='third-party repairer'):life.execute(ident,'select_route',{'route':'third_party','contact_id':wrong})
    assert not service.job(ident)['assignment_id']


def test_guided_workspace_and_route_specific_tracker(qtbot,service,customer):
    from repairshop.ui import MainWindow
    from repairshop.lifecycle_ui import JobWorkspace
    ident,life=route(service,customer,'third_party');dispatch(service,ident,life)
    window=MainWindow(service);window.timer.stop();qtbot.addWidget(window)
    d=JobWorkspace(window,ident);qtbot.addWidget(d);d.show()
    # Physical location now reads under "Currently with", beside who is responsible.
    assert 'THIRD-PARTY' in d.values['currently_with'].text()
    assert set(d.values) >= {'received_by_name', 'assigned_technician', 'currently_with'}
    assert 'Service center dispatch' not in d.tracker.text()
    assert 'Third-party dispatch' in d.tracker.text()
    assert d.primary.isEnabled()
    window.pool.waitForDone(10000)


def test_external_qc_failure_requires_redispatch(service,customer):
    ident,life=route(service,customer,'third_party');dispatch(service,ident,life)
    diagnosis(life,ident);approve(service,ident);complete(life,ident,True);qc(life,ident,'failed')
    assert service.job(ident)['stage']=='ready_dispatch'
    assert life.snapshot(ident)['primary']=='prepare_dispatch'
    assert 'IN SHOP' in life.snapshot(ident)['current_location']
    with pytest.raises(RuleError):life.execute(ident,'bill',{'confirmed':True})


def test_partial_accessory_return_remains_visible(service,customer):
    ident,life=route(service,customer,'third_party');dispatch(service,ident,life)
    diagnosis(life,ident);approve(service,ident);life.execute(ident,'start_repair')
    life.execute(ident,'complete_repair',{'notes':'Repaired'})
    device=next(h for h in life.holdings(ident) if h['type']=='device')
    life.execute(ident,'receive',dict(counterparty='Shop',condition='Intact',acknowledgment='R1',items=[device['id']]))
    assert 'receive' in life.snapshot(ident)['actions']
    assert any('Accessories' in a for a in life.snapshot(ident)['attention'])
    qc(life,ident);life.execute(ident,'bill',{'confirmed':True})
    service.post('customer',customer,'receipt',120000,'partial-paid',job_id=ident)
    with pytest.raises(RuleError,match='every'):
        life.execute(ident,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,received_by='Owner',acknowledgment='Signed'))
    life.execute(ident,'receive',dict(counterparty='Shop',condition='Adapter intact',acknowledgment='R2'))
    assert all(in_shop(h['location']) for h in life.holdings(ident))


def test_replacement_preserves_original_and_delivers_new_serial(service,customer):
    ident,life=route(service,customer,'warranty_centre',True);dispatch(service,ident,life);diagnosis(life,ident)
    life.execute(ident,'warranty_result',{'decision':'accepted','notes':'Replacement covered'})
    life.execute(ident,'start_repair')
    device_id=service.job(ident)['device_id']
    original=next(h for h in life.holdings(ident) if h['type']=='device')
    life.execute(ident,'replacement',dict(notes='OEM replacement certificate',description='Replacement laptop',serial='NEW-SERIAL-123',terms='Remaining OEM warranty'))
    assert any(h['id']==original['id'] and h['location'].startswith('exception:') for h in life.holdings(ident))
    life.execute(ident,'receive',dict(counterparty='Shop',condition='Replacement intact',acknowledgment='R1'))
    qc(life,ident);deliver(service,customer,ident,life,0)
    assert service.job(ident)['device_id']==device_id
    assert any(h['serial']=='NEW-SERIAL-123' and h['location']=='customer' for h in life.holdings(ident))


def test_refund_due_blocks_handover_until_recorded(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident,False)
    service.post('customer',customer,'receipt',10000,'advance-to-refund',job_id=ident)
    qc(life,ident);life.execute(ident,'bill',{'confirmed':True})
    p=dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,received_by='Owner',acknowledgment='Signed')
    with pytest.raises(RuleError,match='refund'):life.execute(ident,'handover',p)
    service.post('customer',customer,'refund',10000,'refund-completed',job_id=ident)
    life.execute(ident,'handover',p)


def test_owner_credit_keeps_real_balance(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident);approve(service,ident);complete(life,ident);qc(life,ident)
    life.execute(ident,'bill',{'confirmed':True})
    life.execute(ident,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,
        received_by='Owner',acknowledgment='Signed',credit_reason='Owner approved payment tomorrow'))
    life.execute(ident,'close')
    assert life.snapshot(ident)['balance']==120000


def test_migration5_to6_preserves_photos_finance_custody_and_verified_backup(service,customer,job,tmp_path):
    from repairshop.persistence import Database, SCHEMA_VERSION
    from repairshop.backup import Backups
    import shutil
    q=service.issue_quote(job,'Repair',[dict(description='Work',amount=100000)])
    service.decide_quote(q,'approved','Customer','in_person')
    service.invoice(q,'legacy-invoice');service.post('customer',customer,'receipt',20000,'legacy-payment',job_id=job)
    target=tmp_path/'legacy5'
    shutil.copytree(service.db.root,target,ignore=shutil.ignore_patterns('shop.db*'))
    with service.db.read() as source:
        with sqlite3.connect(target/'shop.db') as c:source.driver_connection.backup(c)
    with sqlite3.connect(target/'shop.db') as c:
        for table in ('manual_warranty_checks','category_services','warranty_claims','part_warranties','stock_movements','repair_parts','stock_items','job_cards'):
            c.execute('DROP TABLE '+table)
        c.execute('DROP INDEX ix_job_lifecycle')
        c.execute('ALTER TABLE jobs DROP COLUMN lifecycle_version')
        c.execute('ALTER TABLE jobs DROP COLUMN lifecycle_data')
        c.execute('PRAGMA user_version=5')
    upgraded=Database(target)
    assert upgraded.one('PRAGMA user_version')['user_version']==SCHEMA_VERSION
    for table in ('customers','devices','items','holdings','movements','quotes','decisions','entries','attachments'):
        assert upgraded.rows(f'SELECT * FROM {table}')==service.db.rows(f'SELECT * FROM {table}')
    assert upgraded.rows("SELECT * FROM audit WHERE entity!='schema'")==service.db.rows("SELECT * FROM audit WHERE entity!='schema'")
    assert upgraded.one('SELECT lifecycle_version FROM jobs')['lifecycle_version']==0
    archives=list((target/'backups').glob('*pre-upgrade-v5*.zip'))
    assert len(archives)==1 and Backups.validate(archives[0])['schema']==5
    attachment=upgraded.one("SELECT * FROM attachments WHERE kind='customer_photo'")
    assert (target/attachment['path']).read_bytes()==(service.db.root/attachment['path']).read_bytes()


def test_current_quote_cannot_be_approved_after_cancellation(service,customer):
    ident,life=route(service,customer);diagnosis(life,ident)
    q=service.issue_quote(ident,'Repair',[dict(description='Work',amount=100000)])
    life.execute(ident,'decline',{'notes':'Customer cancelled'})
    with pytest.raises(RuleError,match='no longer waiting'):service.decide_quote(q,'approved','Customer','call')


def test_read_snapshot_is_consistent_and_never_accepts_writes(service,customer):
    with service.db.read_snapshot():
        assert service.db.one('SELECT id FROM customers')['id']==customer
        with pytest.raises(RuleError,match='read-only'):service.save_customer('Must not save')
    assert service.db.one('SELECT count(*) n FROM customers')['n']==1


def test_rows_projects_only_requested_page(service,customer):
    for i in range(12):
        service.intake(customer,f"Paging device {i}","Fault",assessment_consent=True)
    life=Lifecycle(service);calls=[];original=life.snapshot
    def counted(ident):
        calls.append(ident);return original(ident)
    life.snapshot=counted
    rows=life.rows(limit=5)
    assert len(rows)==5 and len(calls)==5


def ready_for_route(s,customer,warranty=False):
    """Job advanced to route_selection with no route chosen yet."""
    ident,life=fresh(s,customer)
    life.execute(ident,'inspect')
    life.execute(ident,'inspection_done',{'notes':'Power fault confirmed'})
    life.execute(ident,'verify_warranty',{'warranty_status':'under_warranty' if warranty else 'out_of_warranty','notes':'Evidence reviewed'})
    assert s.job(ident)['stage']=='route_selection' and not s.job(ident)['assignment_id']
    return ident,life


def test_initial_route_to_service_centre_needs_no_confirmation(service,customer):
    ident,life=ready_for_route(service,customer,warranty=True)
    centre=service.save_master('centre','Nokia')
    life.execute(ident,'select_route',{'route':'warranty_centre','contact_id':centre,'reference':'bibhu'})
    assignment=service.db.one('SELECT * FROM assignments WHERE job_id=?',(ident,))
    assert assignment['route']=='warranty_centre' and assignment['contact_id']==centre
    assert assignment['reference']=='bibhu'
    assert service.job(ident)['stage']=='ready_dispatch'
    assert life.snapshot(ident)['route_label']=='AUTHORIZED SERVICE CENTER'
    assert service.db.one('SELECT count(*) n FROM assignments WHERE job_id=?',(ident,))['n']==1


def test_initial_route_to_in_house_technician_needs_no_confirmation(service,customer):
    ident,life=ready_for_route(service,customer)
    tech=service.save_master('technician','Amit')
    life.execute(ident,'select_route',{'route':'in_house','technician_master_id':tech})
    assignment=service.db.one('SELECT * FROM assignments WHERE job_id=?',(ident,))
    assert assignment['technician_master_id']==tech and assignment['route']=='in_house'
    assert service.job(ident)['stage']=='diagnosis'


def test_initial_route_to_third_party_needs_no_confirmation(service,customer):
    ident,life=ready_for_route(service,customer)
    vendor=service.save_master('vendor','Board specialist')
    life.execute(ident,'select_route',{'route':'third_party','contact_id':vendor})
    assignment=service.db.one('SELECT * FROM assignments WHERE job_id=?',(ident,))
    assert assignment['route']=='third_party' and assignment['contact_id']==vendor
    assert service.job(ident)['stage']=='ready_dispatch'


def test_initial_route_does_not_move_the_physical_device(service,customer):
    ident,life=ready_for_route(service,customer,warranty=True)
    before=service.db.rows('SELECT h.location,h.quantity FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? ORDER BY i.id',(ident,))
    moves=service.db.one('SELECT count(*) n FROM movements WHERE item_id IN (SELECT id FROM items WHERE job_id=?)',(ident,))['n']
    centre=service.save_master('centre','Nokia')
    life.execute(ident,'select_route',{'route':'warranty_centre','contact_id':centre,'reference':'bibhu'})
    after=service.db.rows('SELECT h.location,h.quantity FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? ORDER BY i.id',(ident,))
    assert after==before, 'assigning responsibility must not relocate the device'
    assert service.db.one('SELECT count(*) n FROM movements WHERE item_id IN (SELECT id FROM items WHERE job_id=?)',(ident,))['n']==moves
    assert life.snapshot(ident)['responsible']=='Nokia'


def test_changing_an_existing_route_still_requires_confirmation(service,customer):
    ident,life=route(service,customer)          # already assigned in-house
    life.execute(ident,'return_technician',dict(condition='Intact',acknowledgment='Returned for specialist'))
    before=service.job(ident)['assignment_id']
    vendor=service.save_master('vendor','Board specialist')
    # Owner cancelled the confirmation dialog: the UI never sends confirmed.
    with pytest.raises(RuleError,match='Confirm the replacement'):
        life.execute(ident,'change_route',{'route':'third_party','contact_id':vendor})
    assert service.job(ident)['assignment_id']==before
    assert service.job(ident)['route']=='in_house'
    # Owner chose Change Route.
    life.execute(ident,'change_route',{'route':'third_party','contact_id':vendor,'confirmed':True})
    assert service.job(ident)['route']=='third_party'
    assert service.job(ident)['assignment_id']!=before


def test_initial_route_still_enforces_existing_guards(service,customer):
    ident,life=ready_for_route(service,customer)
    with pytest.raises(RuleError,match='third-party repairer'):
        life.execute(ident,'select_route',{'route':'third_party'})
    with pytest.raises(RuleError,match='shop technician'):
        life.execute(ident,'select_route',{'route':'in_house'})
    with pytest.raises(RuleError,match='manufacturer warranty'):
        life.execute(ident,'select_route',{'route':'warranty_centre','contact_id':service.save_master('centre','Nokia')})
    assert not service.job(ident)['assignment_id']


def test_initial_route_requires_device_at_shop_with_accurate_message(service,customer):
    ident,life=ready_for_route(service,customer)
    device=next(h for h in life.holdings(ident) if h['type']=='device')
    life.execute(ident,'resolve_item',dict(item_id=device['id'],source=device['location'],
        quantity=device['quantity'],counterparty='Owner',notes='Misplaced during audit'))
    with pytest.raises(RuleError,match='before assigning this repair route'):
        life.execute(ident,'select_route',{'route':'in_house','technician_master_id':service.save_master('technician','Amit')})


def test_handover_to_technician_still_works_after_initial_route(service,customer):
    ident,life=ready_for_route(service,customer)
    tech=service.save_master('technician','Amit')
    life.execute(ident,'select_route',{'route':'in_house','technician_master_id':tech})
    assert life.snapshot(ident)['current_custodian']=='Owner'
    life.execute(ident,'hand_technician',dict(bench='Bench 2',condition='Intact',acknowledgment='Technician received'))
    v=life.snapshot(ident)
    assert v['current_custodian']=='Amit' and 'Bench 2' in v['current_location']


def test_route_form_has_no_confirmation_checkbox_and_indicator_is_styled():
    from repairshop.ui_widgets import STYLE, CHECKBOX_STYLE
    from repairshop.intake_fields import INTAKE_STYLE
    from pathlib import Path
    import re, inspect
    from repairshop.lifecycle_ui import JobWorkspace
    source=inspect.getsource(JobWorkspace.route_choice)
    assert "f.check('confirmed'" not in source and 'f.check("confirmed"' not in source
    assert CHECKBOX_STYLE.strip() in STYLE and INTAKE_STYLE==CHECKBOX_STYLE
    for state in ('::indicator {','::indicator:hover','::indicator:checked','::indicator:disabled'):
        assert state in CHECKBOX_STYLE, state
    assert '__CHECK__' not in STYLE and '__CHECKBOX__' not in STYLE
    for url in re.findall(r'image: url\("([^"]+)"\)',STYLE):
        assert Path(url).is_file(), url
