"""Contacts & Services: configure once, select many times, keep history as it was."""
import json
import sqlite3
import uuid
import pytest
from repairshop.contacts import Contacts, DuplicateContact, summary
from repairshop.dispatch import Dispatches
from repairshop.domain import RuleError
from repairshop.job_cards import JobCards
from repairshop.lifecycle import Lifecycle
from repairshop.persistence import Database, SCHEMA_VERSION


def master(s, kind, name):
    return next(r['id'] for r in s.masters(kind) if r['name'] == name)


def intake(service, customer, device='Galaxy S21', category='Phone', brand='Samsung'):
    return service.intake(customer_id=customer, device=device, complaint='No display', brand=brand, model='S21',
                          category_id=master(service, 'category', category),
                          service_id=master(service, 'service', category + ' repair'), guided=True)


def to_route(service, job, warranty='out_of_warranty'):
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Inspected'})
    life.execute(job, 'verify_warranty', {'warranty_status': warranty, 'notes': 'Checked'})
    return life


def repairer(service, name='Rajesh Laptop Services', mobile='9876543210', **extra):
    return Contacts(service).save('vendor', dict(name=name, mobile=mobile, **extra))


def third_party(service, customer, partner=None, **route):
    job = intake(service, customer)
    life = to_route(service, job)
    partner = partner or repairer(service, specialization='Mobile, display', contact_person='Rajesh',
                                  city='Pune', address_line1='Shop 4, Wakad')
    life.execute(job, 'select_route', dict(route='third_party', contact_id=partner, confirmed=True, **route))
    return job, life, partner


def prepare(life, job, **extra):
    payload = dict(items=[r['id'] for r in life.holdings(job)], consent=True, condition='Intact',
                   transport_mode='COURIER', transport={'courier_name': 'DTDC', 'docket_number': 'D-1'})
    payload.update(extra)
    life.execute(job, 'prepare_dispatch', payload)


# ---- master records ------------------------------------------------------

def test_repairer_needs_only_name_and_mobile(service):
    ident = Contacts(service).save('vendor', dict(name='Quick Fix', mobile='9876500001', specialization='Laptop'))
    row = service.db.one('SELECT * FROM masters WHERE id=?', (ident,))
    assert (row['kind'], row['contact'], row['specialization'], row['active']) == ('vendor', '+919876500001', 'Laptop', 1)
    assert row['address_line1'] == '' and row['created'] and row['updated']
    with pytest.raises(RuleError, match='mobile'):
        Contacts(service).save('vendor', dict(name='No Mobile'))


def test_full_repairer_profile_and_supported_work(service):
    laptop = master(service, 'category', 'Laptop')
    ident = Contacts(service).save('vendor', dict(
        name='Rajesh Laptop Services', mobile='9876543210', alternate='9876543211', contact_person='Rajesh Kumar',
        email='rajesh@example.invalid', address_line1='Shop 4', city='Pune', district='Pune', state='Maharashtra',
        pincode='411057', specialization='Motherboard, chip-level', supports=[laptop], brands='Dell, HP', notes='Closed Sunday'))
    shot = Contacts(service).snapshot(ident)
    assert shot['contact_person'] == 'Rajesh Kumar' and shot['alternate'] == '+919876543211'
    assert shot['category_supported'] == ['Laptop'] and shot['brand_supported'] == ['Dell', 'HP']
    card = summary(shot)
    assert card.splitlines()[0] == 'Rajesh Laptop Services'
    assert 'Rajesh Kumar · +919876543210' in card and 'Pune' in card


def test_profile_fields_are_kind_specific(service):
    with pytest.raises(RuleError, match='does not apply'):
        service.save_master('vendor', 'Wrong Field', contact='9876500002', profile={'route_from': 'Pune'})
    with pytest.raises(RuleError, match='email'):
        Contacts(service).save('centre', dict(name='Bad Mail', mobile='9876500003', email='not-an-email'))


def test_bus_service_master_holds_route_and_usual_bus(service):
    ident = Contacts(service).save('transporter', dict(
        name='Sharma Travels', mobile='9990012345', contact_person='Ramesh', route_from='Pune',
        route_to='Bhubaneswar', pickup_point='Wakad', drop_point='Baramunda', vehicle_number='MH12AB1234'))
    card = summary(Contacts(service).snapshot(ident))
    for text in ('Sharma Travels', 'Pune → Bhubaneswar', 'Ramesh · +919990012345', 'Pickup: Wakad',
                 'Drop: Baramunda', 'Usual bus: MH12AB1234'):
        assert text in card


def test_transport_method_is_no_longer_a_directory(service):
    from repairshop.domain import MASTER_KINDS
    assert 'transport_method' not in MASTER_KINDS
    assert not service.masters('transport_method')
    with pytest.raises(RuleError):
        service.save_master('transport_method', 'Train')


# ---- quick create, duplicates, inactive ---------------------------------

def test_quick_create_saves_centrally_and_is_audited_on_the_repair(service, customer):
    job = intake(service, customer)
    ident = Contacts(service).quick_create('vendor', 'New Board Shop', '9876500010', job_id=job, specialization='Board')
    assert ident in {r['id'] for r in Contacts(service).directory('vendor')}
    events = service.db.rows("SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='contact_created'", (job,))
    assert json.loads(events[0]['payload'])['name'] == 'New Board Shop'


def test_probable_duplicate_is_flagged_and_can_be_created_anyway(service):
    contacts = Contacts(service)
    first = repairer(service, city='Pune')
    with pytest.raises(DuplicateContact) as same_mobile:
        contacts.quick_create('vendor', 'RLS Repairs', '+91 98765 43210')
    assert same_mobile.value.matches[0]['id'] == first and 'same mobile' in same_mobile.value.matches[0]['reasons']
    with pytest.raises(DuplicateContact, match='similar name'):
        contacts.quick_create('vendor', 'Rajesh Laptop Services Pune', '9000000001', city='Pune')
    second = contacts.quick_create('vendor', 'RLS Repairs', '9876543210', allow_duplicate=True)
    assert second != first
    with pytest.raises(RuleError, match='exactly this name'):
        contacts.quick_create('vendor', 'rajesh laptop services', '9000000002', allow_duplicate=True)


def test_inactive_contacts_leave_selectors_but_keep_history(service, customer):
    job, life, partner = third_party(service, customer)
    Contacts(service).set_active(partner, False)
    assert partner not in {r['id'] for r in Contacts(service).options('vendor')}
    assert partner not in {r['id'] for r in Contacts(service).directory('vendor')}
    assert partner in {r['id'] for r in Contacts(service).directory('vendor', include_inactive=True)}
    assert life.snapshot(job)['assignment']['party'] == 'Rajesh Laptop Services'
    actions = [r['action'] for r in service.db.rows("SELECT action FROM audit WHERE entity='master' AND entity_id=?", (partner,))]
    assert 'deactivated' in actions
    # Deactivation changes status only; nothing else on the record is blanked.
    assert service.db.one('SELECT contact FROM masters WHERE id=?', (partner,))['contact'] == '+919876543210'


# ---- recommendations ------------------------------------------------------

def test_service_centres_for_the_products_brand_are_recommended_first(service, customer):
    contacts = Contacts(service)
    phone = master(service, 'category', 'Phone')
    other = contacts.save('centre', dict(name='Apple Care Pune', mobile='9000000011', brands='Apple'))
    samsung = contacts.save('centre', dict(name='Samsung Service Centre Pune', mobile='9000000012',
                                           brands='Samsung', supports=[phone], warranty_service=True))
    pimpri = contacts.save('centre', dict(name='Samsung Service Centre Pimpri', mobile='9000000013', brands='Samsung'))
    job = intake(service, customer, brand='samsung')
    ranked = contacts.options('centre', job)
    assert [r['id'] for r in ranked[:2]] == [samsung, pimpri]
    assert ranked[0]['recommended'] and 'Samsung' in ranked[0]['reasons']
    # Recommendation only reorders: every active centre is still selectable.
    assert {r['id'] for r in ranked} == {other, samsung, pimpri}
    assert not next(r for r in ranked if r['id'] == other)['recommended']


def test_repairers_matching_category_or_specialization_rank_first(service, customer):
    laptop = master(service, 'category', 'Laptop')
    general = repairer(service, 'Any Gadget Fix', '9000000021', specialization='Speakers')
    board = repairer(service, 'Chip Level Lab', '9000000022', supports=[laptop])
    typed = repairer(service, 'Old Record Repairs', '9000000023', specialization='laptop motherboard')
    job = intake(service, customer, 'Dell Inspiron', 'Laptop', 'Dell')
    ranked = Contacts(service).options('vendor', job)
    assert [r['id'] for r in ranked][:2] == [board, typed]
    assert ranked[-1]['id'] == general and not ranked[-1]['recommended']


# ---- third party and service centre workflow ------------------------------

def test_route_selection_records_only_job_specific_details(service, customer):
    job, life, partner = third_party(service, customer, reference='EXT-77', expected_return='2099-02-01',
                                     instructions='Customer data must be kept')
    assignment = service.db.one('SELECT * FROM assignments WHERE id=?', (service.job(job)['assignment_id'],))
    assert (assignment['contact_id'], assignment['reference'], assignment['expected_return'],
            assignment['instructions']) == (partner, 'EXT-77', '2099-02-01', 'Customer data must be kept')
    assert service.job(job)['return_due'] == '2099-02-01'
    shot = json.loads(assignment['contact_snapshot'])
    assert shot['name'] == 'Rajesh Laptop Services' and shot['phone'] == '+919876543210'
    view = life.snapshot(job)
    assert 'Rajesh · +919876543210' in view['assignment']['summary']
    # The dispatch reuses the ticket typed at assignment instead of asking again.
    prepare(life, job, reference='')
    assert Dispatches(service).current(job)['reference'] == 'EXT-77'


def test_route_details_refuse_retyped_partner_contact(service, customer):
    job, life, _ = third_party(service, customer)
    for key in ('contact_person', 'address', 'phone', 'specialization', 'transport'):
        with pytest.raises(RuleError, match='Contacts & Services'):
            life.execute(job, 'details', {key: 'Typed again'})
    life.execute(job, 'details', {'external_reference': 'TICKET-9', 'notes': 'Waiting for board'})


def test_selecting_a_partner_never_moves_the_product(service, customer):
    job, life, _ = third_party(service, customer)
    locations = {h['location'] for h in life.holdings(job)}
    assert all(l.startswith('staff:') for l in locations)
    assert life.snapshot(job)['at_shop']


def test_service_centre_route_uses_the_centre_master(service, customer):
    centre = Contacts(service).save('centre', dict(name='Samsung Service Centre Pune', mobile='9000000031',
                                                   brands='Samsung', turnaround_days=7, pickup=True))
    job = intake(service, customer)
    life = to_route(service, job, 'under_warranty')
    life.execute(job, 'select_route', dict(route='warranty_centre', contact_id=centre, reference='RMA-1'))
    view = life.snapshot(job)
    assert view['assignment']['party'] == 'Samsung Service Centre Pune'
    assert 'Usual turnaround 7 days' in view['assignment']['summary']
    with pytest.raises(RuleError, match='authorized service center'):
        life.execute(job, 'change_route', dict(route='warranty_centre', contact_id=repairer(service), confirmed=True))


# ---- history snapshots --------------------------------------------------

def test_editing_the_master_does_not_rewrite_repair_history(service, customer):
    job, life, partner = third_party(service, customer)
    prepare(life, job)
    life.execute(job, 'dispatch', dict(counterparty='DTDC desk', condition='Intact', acknowledgment='D1', carrier='DTDC'))
    life.execute(job, 'arrive', dict(counterparty='Rajesh', condition='Intact', acknowledgment='A1'))
    # Six months later the repairer moves and changes number.
    Contacts(service).save('vendor', dict(name='Rajesh Laptop Services', mobile='9999999999',
                                          address_line1='Office 9, Baner', city='Baner'), ident=partner)
    view = life.snapshot(job)
    assert view['assignment']['contact'] == '+919876543210'
    assert 'Wakad' in view['assignment']['partner']['address'] and 'Baner' not in view['assignment']['summary']
    sent = Dispatches(service).current(job)
    assert sent['contact_snapshot']['phone'] == '+919876543210'
    card = json.loads(service.db.one("SELECT snapshot FROM job_cards WHERE job_id=? AND kind='third_party_arrival'", (job,))['snapshot'])
    assert card['to']['contact'] == '+919876543210' and 'Wakad' in card['to']['address']
    # A new repair uses the updated record.
    second, _, _ = third_party(service, customer, partner)
    assert Lifecycle(service).snapshot(second)['assignment']['contact'] == '+919999999999'
    # The dispatch snapshot itself is protected once sent.
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:
            c.execute("UPDATE dispatches SET contact_snapshot='{}' WHERE id=?", (sent['id'],))


def test_repair_attempts_show_each_partner_in_order(service, customer):
    first = repairer(service, 'First Lab', '9000000041')
    job, life, _ = third_party(service, customer, first, reference='A-1')
    second = repairer(service, 'Second Lab', '9000000042')
    life.execute(job, 'change_route', dict(route='third_party', contact_id=second, confirmed=True, reference='B-2'))
    attempts = Dispatches(service).attempts(job)
    assert [(a['attempt'], a['partner'], a['reference'], a['result']) for a in attempts] == [
        (1, 'First Lab', 'A-1', 'Reassigned'), (2, 'Second Lab', 'B-2', 'In progress')]
    replaced = json.loads(service.db.one("SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='assigned' ORDER BY id DESC", (job,))['payload'])
    assert replaced['replaces'] == 'First Lab' and replaced['partner'] == 'Second Lab'


# ---- transport -------------------------------------------------------------

def bus_service(service, **extra):
    values = dict(name='Sharma Travels', mobile='9990012345', contact_person='Ramesh', route_from='Pune',
                  route_to='Bhubaneswar', pickup_point='Wakad', drop_point='Baramunda', vehicle_number='MH12AB1234')
    values.update(extra)
    return Contacts(service).save('transporter', values)


def test_bus_dispatch_selects_the_service_and_records_the_journey(service, customer):
    job, life, _ = third_party(service, customer)
    operator = bus_service(service)
    prepare(life, job, transport_mode='BUS', transporter_id=operator, amount=35000,
            transport={'bus_number': 'MH12XY9999', 'parcel_number': 'P-501', 'departure_date': '2099-01-02',
                       'departure_time': '9:30', 'arrival_date': '2099-01-03', 'arrival_time': '06:00'})
    record = Dispatches(service).current(job)
    assert record['transporter_id'] == operator and record['amount'] == 35000
    assert record['transporter_snapshot']['route_to'] == 'Bhubaneswar'
    assert record['transport'] == {'bus_number': 'MH12XY9999', 'parcel_number': 'P-501', 'departure_date': '2099-01-02',
                                   'departure_time': '09:30', 'arrival_date': '2099-01-03', 'arrival_time': '06:00'}
    assert 'Sharma Travels' in record['transport_summary'] and 'Pune → Bhubaneswar' in record['transport_summary']
    assert record['carrier'] == 'Sharma Travels · MH12XY9999'
    with pytest.raises(RuleError, match='HH:MM'):
        Dispatches(service).edit(job, dict(transport_mode='BUS', transporter_id=operator,
                                           transport={'bus_number': 'X', 'departure_time': '25:00'}))


def test_sent_bus_dispatch_keeps_the_original_operator_and_bus(service, customer):
    job, life, _ = third_party(service, customer)
    operator = bus_service(service)
    prepare(life, job, transport_mode='BUS', transporter_id=operator, transport={'bus_number': 'MH12XY9999'})
    life.execute(job, 'dispatch', dict(counterparty='Ramesh', condition='Intact', acknowledgment='D1',
                                       carrier='Sharma Travels · MH12XY9999'))
    Contacts(service).save('transporter', dict(name='Sharma Travels', mobile='9111111111', route_from='Pune',
                                               route_to='Cuttack', vehicle_number='OD02ZZ0001'), ident=operator)
    Dispatches(service).amend(job, dict(transport={'bus_number': 'MH12XY9999', 'parcel_number': 'P-9'}),
                              'Wrong bus number entered', operation_id=uuid.uuid4().hex)
    history = Dispatches(service).history(job)
    assert [h['transporter_snapshot']['route_to'] for h in history] == ['Bhubaneswar', 'Bhubaneswar']
    assert history[-1]['transport']['bus_number'] == 'MH12XY9999' and history[-1]['transport']['parcel_number'] == 'P-9'
    assert {h['transporter_snapshot']['phone'] for h in history} == {'+919990012345'}
    # Custody followed the actual handover, not the directory.
    assert any(h['location'] == 'transit:Sharma Travels · MH12XY9999' for h in life.holdings(job))
    stats = Contacts(service).activity(operator)
    assert stats['dispatches'] == 1


def test_courier_stays_free_text_with_suggestions(service, customer):
    job, life, _ = third_party(service, customer)
    prepare(life, job, transport={'courier_name': 'Professional Couriers Ltd', 'docket_number': 'PC-1', 'docket_date': '2099-01-02'})
    record = Dispatches(service).current(job)
    assert record['transport']['courier_name'] == 'Professional Couriers Ltd' and record['transporter_id'] is None
    assert not service.masters('transporter')
    assert 'Professional Couriers Ltd' in Dispatches(service).courier_suggestions()


def test_in_hand_dispatch_records_the_person_and_custody(service, customer):
    job, life, _ = third_party(service, customer)
    prepare(life, job, transport_mode='IN_HAND', transport={'person_name': 'Shop runner', 'mobile': '9990011001',
                                                            'role': 'Staff', 'departure_time': '18:15'})
    record = Dispatches(service).current(job)
    assert record['carrier'] == 'Shop runner' and record['transport']['role'] == 'Staff'
    life.execute(job, 'dispatch', dict(counterparty='Shop runner', condition='Intact', acknowledgment='D1', carrier=record['carrier']))
    assert {h['location'] for h in life.holdings(job) if h['type'] == 'device'} == {'transit:Shop runner'}
    life.execute(job, 'arrive', dict(counterparty='Rajesh', condition='Intact', acknowledgment='A1'))
    assert {h['location'] for h in life.holdings(job) if h['type'] == 'device'} == {'vendor:Rajesh Laptop Services'}


def test_legacy_bus_dispatch_without_a_saved_service_stays_valid(service, customer):
    job, life, _ = third_party(service, customer)
    prepare(life, job, transport_mode='BUS', transport={'bus_number': 'MH12AB1234', 'contact_name': 'Desk',
                                                        'contact_mobile': '9990012345'})
    life.execute(job, 'dispatch', dict(counterparty='Desk', condition='Intact', acknowledgment='D1'))
    Dispatches(service).amend(job, dict(amount=5000), 'Incorrect courier amount')
    current = Dispatches(service).current(job)
    assert current['transport']['contact_mobile'] == '+919990012345' and current['carrier'] == 'Desk · MH12AB1234'


# ---- upgrade -------------------------------------------------------------

def test_upgrade_lifts_profiles_and_snapshots_existing_history(service, customer, tmp_path):
    job, life, partner = third_party(service, customer)
    prepare(life, job)
    life.execute(job, 'dispatch', dict(counterparty='Desk', condition='Intact', acknowledgment='D1', carrier='DTDC'))
    centre = service.save_master('centre', 'Legacy Centre', contact='9000000051')
    service.save_master('transporter', 'Legacy Bus', contact='9000000052', details='Night bus only')
    with service.db.transaction() as c:
        # Reproduce schema 14 data: profile JSON in details, no snapshots, live transport list.
        for trigger in ('immutable_assignments_update', 'dispatch_history_update'):
            c.execute('DROP TRIGGER ' + trigger)
        c.execute("UPDATE masters SET details=?,contact_person='',email='',notes='' WHERE id=?",
                  (json.dumps({'company': 'Samsung', 'contact_person': 'Ravi', 'email': 'ravi@example.invalid', 'notes': 'Old'}), centre))
        c.execute("UPDATE masters SET details=?,contact_person='',notes='' WHERE id=?",
                  (json.dumps({'company': 'Rajesh Enterprises', 'contact_person': 'Rajesh'}), partner))
        c.execute("UPDATE masters SET notes='' WHERE kind='transporter'")
        c.execute("INSERT INTO masters(kind,name,normalized) VALUES ('transport_method','Train','train')")
        c.execute("UPDATE assignments SET contact_snapshot='{}'")
        c.execute("UPDATE dispatches SET contact_snapshot='{}',assignment_id=NULL")
        c.execute('PRAGMA user_version=14')
    upgraded = Database(service.db.root)
    assert upgraded.one('PRAGMA user_version')['user_version'] == SCHEMA_VERSION == 15
    row = upgraded.one('SELECT * FROM masters WHERE id=?', (centre,))
    assert (row['details'], row['contact_person'], row['email'], row['notes']) == ('', 'Ravi', 'ravi@example.invalid', 'Old')
    assert upgraded.one('''SELECT m.name FROM master_supports s JOIN masters m ON m.id=s.target_id
        WHERE s.master_id=?''', (centre,))['name'] == 'Samsung'
    vendor = upgraded.one('SELECT * FROM masters WHERE id=?', (partner,))
    assert vendor['contact_person'] == 'Rajesh' and 'Company: Rajesh Enterprises' in vendor['notes'] and vendor['details'] == ''
    assert upgraded.one("SELECT notes FROM masters WHERE kind='transporter'")['notes'] == 'Night bus only'
    assert not upgraded.rows("SELECT 1 FROM masters WHERE kind='transport_method' AND active=1")
    assignment = upgraded.one('SELECT * FROM assignments WHERE job_id=?', (job,))
    assert json.loads(assignment['contact_snapshot'])['name'] == 'Rajesh Laptop Services'
    dispatch = upgraded.one('SELECT * FROM dispatches WHERE job_id=?', (job,))
    assert dispatch['assignment_id'] == assignment['id']
    assert json.loads(dispatch['contact_snapshot'])['name'] == 'Rajesh Laptop Services'
    with pytest.raises(sqlite3.IntegrityError):
        with upgraded.transaction() as c:
            c.execute("UPDATE assignments SET reference='rewritten' WHERE id=?", (assignment['id'],))
    with pytest.raises(sqlite3.IntegrityError):
        with upgraded.transaction() as c:
            c.execute("UPDATE dispatches SET contact_snapshot='{}' WHERE id=?", (dispatch['id'],))
    assert upgraded.one('SELECT count(*) n FROM movements')['n'] == service.db.one('SELECT count(*) n FROM movements')['n']


# ---- UI ----------------------------------------------------------------

def test_selector_recommends_summarises_and_quick_creates(qtbot, service, customer, monkeypatch):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox
    from repairshop.contacts_ui import ContactSelector
    contacts = Contacts(service)
    contacts.save('centre', dict(name='Apple Care Pune', mobile='9000000061', brands='Apple'))
    samsung = contacts.save('centre', dict(name='Samsung Service Centre Pune', mobile='9000000062', brands='Samsung',
                                           city='Pune', contact_person='Anita'))
    job = intake(service, customer)
    selector = ContactSelector(service, 'centre', job_id=job)
    qtbot.addWidget(selector)
    texts = [selector.box.itemText(i) for i in range(selector.box.count())]
    assert texts[1].startswith('— Recommended') and texts[2].startswith('Samsung Service Centre Pune')
    assert selector.value() is None and selector.card.isHidden()
    selector.box.setCurrentIndex(selector.box.findData(samsung))
    assert selector.value() == samsung
    assert 'Anita · +919000000062' in selector.card.text() and 'Recommended' in selector.card.text()

    def fill():
        form = QApplication.activeModalWidget()
        form.fields['name'].setText('Samsung Care Pimpri')
        form.fields['mobile'].setText('9000000063')
        form.fields['brands'].setText('Samsung')
        assert 'Select' in form.buttons.button(QDialogButtonBox.StandardButton.Save).text()
        form.buttons.button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(30, fill)
    created = selector.add()
    assert created and selector.value() == created
    assert service.db.one('SELECT kind FROM masters WHERE id=?', (created,))['kind'] == 'centre'


def test_contacts_and_services_screen_lists_each_section(qtbot, service):
    from repairshop.ui import MainWindow
    from repairshop.contacts_ui import ContactList, SetupList
    repairer(service)
    bus_service(service)
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    window.navigate('Contacts & Services')
    page = window.contacts_page
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == ['Repair Partners', 'Suppliers', 'Transport', 'Shop Setup']
    vendors = page.show_kind('vendor')
    assert isinstance(vendors, ContactList) and vendors.grid.rows[0]['name'] == 'Rajesh Laptop Services'
    assert 'Repairs: 0' in vendors.card.text()
    buses = page.show_kind('transporter')
    assert buses.grid.rows[0]['works_on'] == 'Pune → Bhubaneswar'
    buses.search.setText('nothing matches this')
    assert not buses.grid.rows
    assert isinstance(page.show_kind('category'), SetupList)
    window.pool.waitForDone(10000)
