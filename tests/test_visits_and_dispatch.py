"""Visit grouping and versioned third-party dispatch over the existing domain."""
import json
import sqlite3
import uuid
import pytest
from repairshop.domain import RuleError
from repairshop.lifecycle import Lifecycle
from repairshop.visits import Visits
from repairshop.dispatch import Dispatches


def master(s, kind, name):
    return next(r['id'] for r in s.masters(kind) if r['name'] == name)


def product(s, customer, name, category='Laptop', **extra):
    return dict(customer_id=customer, device=name, complaint='Fault on ' + name,
                category_id=master(s, 'category', category),
                service_id=master(s, 'service', category + ' repair'), guided=True, **extra)


def three(service, customer):
    return service.intake_visit([
        product(service, customer, 'Dell Laptop', deposit=500000,
                accessories=[dict(type='accessory', description='Charger', quantity=1)]),
        product(service, customer, 'Samsung Mobile', 'Phone', deposit=150000),
        product(service, customer, 'HP Printer', 'Printer')], 'visit-op-' + uuid.uuid4().hex)


# ---- Part 1: visit / intake session -------------------------------------

def test_single_product_intake_creates_one_visit_and_one_job(service, customer):
    job = service.intake(**product(service, customer, 'Lone laptop'))
    visits = Visits(service).for_customer(customer)
    assert len(visits) == 1 and visits[0]['products'] == 1
    assert visits[0]['number'].startswith('VIS-') and len(visits[0]['number']) == 17
    assert service.job(job)['visit_id'] == visits[0]['id']


def test_three_product_intake_creates_one_visit_with_three_jobs(service, customer):
    jobs = three(service, customer)
    visits = Visits(service).for_customer(customer)
    assert len(jobs) == 3 and len(visits) == 1
    assert visits[0]['products'] == 3 and visits[0]['status'] == 'Open'
    assert [r['id'] for r in Visits(service).jobs(visits[0]['id'])] == jobs


def test_all_jobs_reference_the_same_visit(service, customer):
    jobs = three(service, customer)
    assert len({service.job(i)['visit_id'] for i in jobs}) == 1
    assert all(service.job(i)['visit_id'] for i in jobs)


def test_jobs_in_one_visit_keep_independent_lifecycle_stages(service, customer):
    laptop, mobile, printer = three(service, customer)
    life = Lifecycle(service)
    life.execute(laptop, 'inspect')
    life.execute(mobile, 'inspect')
    life.execute(mobile, 'inspection_done', {'notes': 'Charging port damage confirmed'})
    assert service.job(laptop)['stage'] == 'inspection'
    assert service.job(mobile)['stage'] == 'warranty_check'
    assert service.job(printer)['stage'] == 'received'
    visit = Visits(service).for_job(laptop)
    assert {r['stage'] for r in visit['jobs']} == {'inspection', 'warranty_check', 'received'}


def test_failed_child_job_rolls_back_the_whole_visit(service, customer):
    good = product(service, customer, 'Dell Laptop')
    bad = product(service, customer, 'HP Printer', 'Printer')
    bad['service_id'] = master(service, 'service', 'Laptop repair')
    with pytest.raises(RuleError):
        service.intake_visit([good, bad], 'rollback-op')
    for table in ('jobs', 'visits', 'items', 'movements', 'commands'):
        assert service.db.one('SELECT count(*) n FROM ' + table)['n'] == 0


def test_visit_summary_status_projects_child_job_closure(service, customer):
    assert Visits.status(3, 0, 3) == 'Open'
    assert Visits.status(3, 1, 2) == 'Partly completed'
    assert Visits.status(3, 3, 0) == 'Completed'
    jobs = three(service, customer)
    with service.db.transaction() as c:
        c.execute("UPDATE jobs SET stage='closed' WHERE id=?", (jobs[0],))
    assert Visits(service).for_customer(customer)[0]['status'] == 'Partly completed'


def test_visit_search_by_number_customer_and_job_number(service, customer):
    jobs = three(service, customer)
    visit = Visits(service).for_customer(customer)[0]
    assert [r['id'] for r in Visits(service).search(visit['number'])] == [visit['id']]
    assert [r['id'] for r in Visits(service).search('Synthetic')] == [visit['id']]
    assert [r['id'] for r in Visits(service).search(service.job(jobs[1])['number'])] == [visit['id']]
    assert Visits(service).search('VIS-19700101-9999') == []
    assert len(Lifecycle(service).rows(search=visit['number'])) == 3


def test_customer_history_lists_visits_with_child_jobs(service, customer):
    from repairshop.customer_records import CustomerRecords
    jobs = three(service, customer)
    data = CustomerRecords(service).overview(customer)
    assert len(data['visits']) == 1
    assert [p['job_id'] for p in data['visits'][0]['product_list']] == jobs
    assert all(p['status'] for p in data['visits'][0]['product_list'])


def test_visit_cancellation_keeps_child_jobs_and_records_a_reason(service, customer):
    jobs = three(service, customer)
    visit = Visits(service).for_customer(customer)[0]
    with pytest.raises(RuleError, match='why'):
        Visits(service).cancel(visit['id'], '  ')
    Visits(service).cancel(visit['id'], 'Customer withdrew the intake at the counter')
    assert len(Visits(service).jobs(visit['id'])) == len(jobs)
    assert Visits(service).for_customer(customer)[0]['status'].startswith('Cancelled')
    assert service.db.one("SELECT 1 n FROM audit WHERE entity='visit' AND action='visit_cancelled'")


def test_visit_history_cannot_be_deleted(service, customer):
    three(service, customer)
    visit = Visits(service).for_customer(customer)[0]
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:
            c.execute('DELETE FROM visits WHERE id=?', (visit['id'],))


def test_migration_attaches_historical_jobs_to_reconstructed_visits(service, customer, tmp_path):
    import shutil
    from repairshop.persistence import Database, SCHEMA_VERSION
    jobs = three(service, customer)
    lone = service.intake(**product(service, customer, 'Separate later visit'))
    target = tmp_path / 'legacy'
    shutil.copytree(service.db.root, target, ignore=shutil.ignore_patterns('shop.db*'))
    with service.db.read() as source:
        with sqlite3.connect(target / 'shop.db') as c:
            source.driver_connection.backup(c)
    with sqlite3.connect(target / 'shop.db') as c:
        # Reproduce the pre-visit schema: jobs grouped only by their intake reference.
        c.execute('DROP TABLE dispatches')
        for trigger in ('visit_history_delete', 'immutable_visit_number', 'dispatch_history_update', 'dispatch_history_delete'):
            c.execute('DROP TRIGGER IF EXISTS ' + trigger)
        c.execute('UPDATE jobs SET visit_id=NULL')
        c.execute('DELETE FROM visits')
        c.execute('PRAGMA user_version=10')
    upgraded = Database(target)
    assert upgraded.one('PRAGMA user_version')['user_version'] == SCHEMA_VERSION
    for ident in jobs + [lone]:
        assert upgraded.one('SELECT visit_id FROM jobs WHERE id=?', (ident,))['visit_id']
    grouped = upgraded.rows('SELECT visit_id,count(*) n FROM jobs GROUP BY visit_id ORDER BY n')
    assert [r['n'] for r in grouped] == [1, 3]
    assert upgraded.one('SELECT count(*) n FROM movements')['n'] == service.db.one('SELECT count(*) n FROM movements')['n']
    numbers = [r['number'] for r in upgraded.rows('SELECT number FROM visits ORDER BY id')]
    assert len(set(numbers)) == 2 and all(n.startswith('VIS-') for n in numbers)


# ---- Part 2: dispatch ---------------------------------------------------

def external(service, customer, ident, party='ABC Repair'):
    life = Lifecycle(service)
    life.execute(ident, 'inspect')
    life.execute(ident, 'inspection_done', {'notes': 'Inspected at counter'})
    life.execute(ident, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'No proof'})
    life.execute(ident, 'select_route', {'route': 'third_party', 'confirmed': True,
                                         'contact_id': service.save_master('vendor', party)})
    return life


def prepared(service, life, ident, **extra):
    payload = dict(items=[r['id'] for r in life.holdings(ident)],
        consent=True, condition='Intact', expected_return='2099-01-01', reference='TP-1',
        transport_mode='COURIER', transport={'courier_name': 'Blue Dart', 'docket_number': 'BD12345'},
        amount=25000)
    payload.update(extra)
    life.execute(ident, 'prepare_dispatch', payload)
    return Dispatches(service).current(ident)


def send(service, life, ident):
    life.execute(ident, 'dispatch', dict(counterparty='Courier desk', condition='Intact',
                                         acknowledgment='Receipt D1'))
    return Dispatches(service).current(ident)


def test_dispatch_belongs_to_the_individual_job_not_the_visit(service, customer):
    laptop, mobile, _ = three(service, customer)
    life = external(service, customer, mobile, 'XYZ Mobile Repair')
    record = prepared(service, life, mobile)
    assert record['job_id'] == mobile
    assert Dispatches(service).current(laptop) is None
    assert service.job(mobile)['visit_id'] == service.job(laptop)['visit_id']


def test_two_jobs_in_one_visit_dispatch_independently(service, customer):
    laptop, mobile, _ = three(service, customer)
    prepared(service, external(service, customer, laptop, 'ABC Repair'), laptop)
    prepared(service, external(service, customer, mobile, 'XYZ Repair'), mobile)
    first, second = Dispatches(service).current(laptop), Dispatches(service).current(mobile)
    assert first['id'] != second['id'] and first['contact_id'] != second['contact_id']
    send(service, Lifecycle(service), mobile)
    assert Dispatches(service).current(mobile)['status'] == 'DISPATCHED'
    assert Dispatches(service).current(laptop)['status'] == 'READY'


def test_draft_dispatch_is_edited_in_place(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    record = prepared(service, life, ident)
    Dispatches(service).edit(ident, dict(reference='TP-2', amount=30000,
        transport_mode='COURIER', transport={'courier_name': 'Blue Dart', 'docket_number': 'BD99999'}))
    current = Dispatches(service).current(ident)
    assert current['id'] == record['id'] and current['version'] == 1
    assert current['reference'] == 'TP-2' and current['amount'] == 30000
    assert current['transport']['docket_number'] == 'BD99999'
    assert len(Dispatches(service).history(ident)) == 1

def test_transport_payer_is_saved_edited_and_versioned(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    record = prepared(service, life, ident, paid_by='customer')
    assert record['paid_by'] == 'customer'
    Dispatches(service).edit(ident, dict(paid_by='shop'))
    assert Dispatches(service).current(ident)['paid_by'] == 'shop'
    send(service, life, ident)
    current = Dispatches(service).current(ident)
    Dispatches(service).amend(ident, dict(paid_by='third_party'), 'Payer corrected', operation_id=uuid.uuid4().hex)
    amended = Dispatches(service).current(ident)
    assert amended['paid_by'] == 'third_party'
    assert amended['version'] == current['version'] + 1


def test_transport_payer_rejects_unknown_values(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    with pytest.raises(RuleError, match='who pays'):
        prepared(service, life, ident, paid_by='somebody_else')


def test_sent_dispatch_cannot_be_edited_or_overwritten(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    record = send(service, life, ident)
    with pytest.raises(RuleError, match='Amend'):
        Dispatches(service).edit(ident, dict(reference='TP-9'))
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:
            c.execute("UPDATE dispatches SET reference='rewritten' WHERE id=?", (record['id'],))
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:
            c.execute('DELETE FROM dispatches WHERE id=?', (record['id'],))
    assert Dispatches(service).current(ident)['reference'] == 'TP-1'


def test_amendment_creates_a_new_version_and_keeps_the_original(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    original = send(service, life, ident)
    Dispatches(service).amend(ident, dict(transport_mode='COURIER',
        transport={'courier_name': 'Blue Dart', 'docket_number': 'BD12355'}),
        'Courier receipt entered incorrectly')
    history = Dispatches(service).history(ident)
    assert [r['version'] for r in history] == [1, 2]
    assert history[0]['status'] == 'SUPERSEDED' and not history[0]['current']
    assert history[0]['transport']['docket_number'] == 'BD12345'
    assert history[1]['status'] == 'DISPATCHED' and history[1]['current']
    assert history[1]['transport']['docket_number'] == 'BD12355'
    assert history[1]['supersedes_id'] == original['id']
    assert history[1]['amendment_reason'] == 'Courier receipt entered incorrectly'
    assert history[1]['actual_dispatch_at'] == original['actual_dispatch_at']


def test_amendment_requires_a_reason(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    send(service, life, ident)
    for empty in ('', '   ', None):
        with pytest.raises(RuleError, match='why'):
            Dispatches(service).amend(ident, dict(reference='TP-3'), empty)
    assert len(Dispatches(service).history(ident)) == 1


def test_amendment_does_not_alter_physical_custody_movements(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    send(service, life, ident)
    before = service.db.rows('''SELECT m.* FROM movements m JOIN items i ON i.id=m.item_id
        WHERE i.job_id=? ORDER BY m.id''', (ident,))
    Dispatches(service).amend(ident, dict(amount=99900, transport_mode='COURIER',
        transport={'courier_name': 'Blue Dart', 'docket_number': 'BD12355'}), 'Incorrect courier amount')
    after = service.db.rows('''SELECT m.* FROM movements m JOIN items i ON i.id=m.item_id
        WHERE i.job_id=? ORDER BY m.id''', (ident,))
    assert before == after
    assert Lifecycle(service).snapshot(ident)['current_custodian'] == 'ABC Repair'


def test_third_party_cannot_be_silently_changed_after_dispatch(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    send(service, life, ident)
    other = service.save_master('vendor', 'XYZ Repair')
    with pytest.raises(RuleError, match='physical movement'):
        Dispatches(service).amend(ident, dict(contact_id=other), 'Wrong third-party selected')
    assert Dispatches(service).current(ident)['contact_name'] == 'ABC Repair'
    assert len(Dispatches(service).history(ident)) == 1


def test_manifest_cannot_include_an_item_the_shop_does_not_hold(service, customer):
    laptop, mobile, _ = three(service, customer)
    life = external(service, customer, laptop)
    foreign = service.db.one('SELECT id FROM items WHERE job_id=?', (mobile,))['id']
    with pytest.raises(RuleError):
        prepared(service, life, laptop, items=[foreign])
    prepared(service, life, laptop)
    with pytest.raises(RuleError, match='does not currently hold'):
        Dispatches(service).edit(laptop, dict(manifest=[foreign]))


def test_manifest_is_physical_history_after_dispatch(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    record = prepared(service, life, ident)
    send(service, life, ident)
    with pytest.raises(RuleError, match='physical history'):
        Dispatches(service).amend(ident, dict(manifest=record['manifest'][:1]), 'Wrong items listed')


def test_receive_from_third_party_closes_the_current_dispatch(service, customer):
    ident = three(service, customer)[2]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    send(service, life, ident)
    life.execute(ident, 'diagnose', dict(notes='Board fault', repairable=True))
    quote = service.issue_quote(ident, 'Board repair', [{'description': 'Board', 'amount': 100000}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    life.execute(ident, 'start_repair')
    life.execute(ident, 'complete_repair', dict(notes='Board replaced', parts='Board'))
    life.execute(ident, 'receive', dict(counterparty='Counter staff', condition='Intact',
                                        acknowledgment='Return R1',
                                        repair_result='REPAIRED'))
    assert Dispatches(service).current(ident) is None
    assert [r['status'] for r in Dispatches(service).history(ident)] == ['RETURNED']
    assert service.job(ident)['stage'] == 'final_qc'


def test_backup_archive_carries_visit_and_dispatch_versions(service, customer, tmp_path):
    from repairshop.backup import Backups
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    send(service, life, ident)
    Dispatches(service).amend(ident, dict(transport_mode='COURIER',
        transport={'courier_name': 'Blue Dart', 'docket_number': 'BD12355'}), 'Wrong docket number entered')
    archive = Backups(service).create('manual', tmp_path / 'archives')
    restored = tmp_path / 'restored.db'
    import zipfile
    with zipfile.ZipFile(archive) as z:
        restored.write_bytes(z.read('shop.db'))
    with sqlite3.connect(restored) as c:
        c.row_factory = sqlite3.Row
        assert c.execute('SELECT count(*) FROM visits').fetchone()[0] == 1
        versions = [dict(r) for r in c.execute('SELECT version,status,current FROM dispatches ORDER BY version')]
        assert [v['version'] for v in versions] == [1, 2]
        assert [v['status'] for v in versions] == ['SUPERSEDED', 'DISPATCHED']
        assert c.execute('SELECT count(*) FROM jobs WHERE visit_id IS NULL').fetchone()[0] == 0


def test_audit_records_the_significant_dispatch_events(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    Dispatches(service).edit(ident, dict(reference='TP-2'))
    send(service, life, ident)
    Dispatches(service).amend(ident, dict(amount=30000), 'Incorrect courier amount')
    actions = [r['action'] for r in service.db.rows(
        "SELECT action FROM audit WHERE entity='job' AND entity_id=? ORDER BY id", (ident,))]
    for expected in ('dispatch_created', 'dispatch_edited_before_send', 'dispatch_confirmed', 'dispatch_amended'):
        assert expected in actions
    amendment = json.loads(service.db.one(
        "SELECT payload FROM audit WHERE action='dispatch_amended' ORDER BY id DESC")['payload'])
    assert amendment['reason'] == 'Incorrect courier amount'
    assert amendment['changes']['amount'] == [25000, 30000]


# ---- UI ---------------------------------------------------------------

def test_dispatch_panel_edits_before_send_and_amends_after(qtbot, service, customer, monkeypatch):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox
    from legacy_desktop.ui import MainWindow
    from legacy_desktop.lifecycle_ui import JobWorkspace
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    prepared(service, life, ident)
    window = MainWindow(service)
    qtbot.addWidget(window)
    workspace = JobWorkspace(window, ident)
    qtbot.addWidget(workspace)
    panel = workspace.dispatch_tab
    assert panel is not None and 'BD12345' in panel.summary.text()

    def fill(values, button_text='Save'):
        form = QApplication.activeModalWidget()
        try:
            for key, value in values.items():
                widget = form.fields[key]
                if hasattr(widget, 'setPlainText'):
                    widget.setPlainText(value)
                elif hasattr(widget, 'setCurrentIndex') and hasattr(widget, 'findData'):
                    widget.setCurrentIndex(widget.findData(value))
                else:
                    widget.setText(value)
            form.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException:
            form.reject()
            raise

    QTimer.singleShot(30, lambda: fill({'reference': 'TP-EDITED'}))
    panel.edit()
    current = Dispatches(service).current(ident)
    assert current['version'] == 1 and current['reference'] == 'TP-EDITED'

    send(service, life, ident)
    workspace.reload()
    assert 'Amend dispatch' in {panel.controls.itemAt(i).widget().text() for i in range(panel.controls.count())}
    with pytest.raises(RuleError, match='Amend'):
        panel.edit()

    QTimer.singleShot(30, lambda: fill({'transport_COURIER_docket_number': 'BD12355',
                                        'reason_code': 'Wrong docket number entered'}))
    panel.amend()
    history = Dispatches(service).history(ident)
    assert [r['version'] for r in history] == [1, 2]
    assert history[1]['transport']['docket_number'] == 'BD12355'
    assert 'Wrong docket number entered' in history[1]['amendment_reason']


# ---- Transport section -------------------------------------------------

def test_only_three_transport_modes_each_with_its_own_fields():
    from repairshop.dispatch import TRANSPORT_MODES, TRANSPORT_METHODS
    assert set(TRANSPORT_MODES) == set(TRANSPORT_METHODS) == {'COURIER', 'BUS', 'IN_HAND'}
    assert TRANSPORT_MODES['COURIER'] == ('courier_name', 'docket_number', 'docket_date')
    # The bus operator's route and contact come from the saved bus service, not these fields.
    assert TRANSPORT_MODES['BUS'] == ('bus_number', 'parcel_number', 'departure_date', 'departure_time',
                                      'arrival_date', 'arrival_time')
    assert TRANSPORT_MODES['IN_HAND'] == ('person_name', 'mobile', 'role', 'departure_date', 'departure_time')


def test_a_mode_refuses_another_modes_fields(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    with pytest.raises(RuleError, match='Unsupported transport detail for Bus'):
        prepared(service, life, ident, transport_mode='BUS',
                 transport={'bus_number': 'MH12AB1234', 'contact_name': 'Desk',
                            'contact_mobile': '9990012345', 'docket_number': 'BD1'})


@pytest.mark.parametrize('mode,transport,missing', [
    ('COURIER', {'courier_name': 'Blue Dart'}, 'Tracking / docket number'),
    ('COURIER', {'docket_number': 'BD1'}, 'Courier company'),
    ('BUS', {'bus_number': 'MH12AB1234', 'contact_name': 'Desk'}, 'Contact person number'),
    ('BUS', {'bus_number': 'MH12AB1234'}, 'bus / transport service'),
    ('IN_HAND', {'person_name': 'Runner'}, 'Mobile'),
])
def test_each_mode_requires_what_makes_it_traceable(service, customer, mode, transport, missing):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    with pytest.raises(RuleError, match=missing):
        prepared(service, life, ident, transport_mode=mode, transport=transport)


def test_bus_contact_from_the_saved_service_is_not_retyped(service, customer):
    from repairshop.contacts import Contacts
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    operator = Contacts(service).save('transporter', dict(name='Sharma Travels', mobile='9990012345'))
    with pytest.raises(RuleError, match='comes from the selected bus service'):
        prepared(service, life, ident, transport_mode='BUS', transporter_id=operator,
                 transport={'bus_number': 'MH12AB1234', 'contact_name': 'Desk', 'contact_mobile': '9990012345'})


def test_contact_numbers_are_validated_and_normalised(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    with pytest.raises(RuleError, match='valid contact person number'):
        prepared(service, life, ident, transport_mode='BUS',
                 transport={'bus_number': 'MH12AB1234', 'contact_name': 'Desk', 'contact_mobile': '123'})
    record = prepared(service, life, ident, transport_mode='BUS',
                      transport={'bus_number': 'MH12AB1234', 'contact_name': 'Desk', 'contact_mobile': '9990012345'})
    assert record['transport']['contact_mobile'] == '+919990012345'


def test_docket_date_must_be_a_real_date(service, customer):
    ident = three(service, customer)[0]
    life = external(service, customer, ident)
    with pytest.raises(RuleError, match='docket date as a real calendar date'):
        prepared(service, life, ident, transport_mode='COURIER',
                 transport={'docket_number': 'BD1', 'courier_name': 'Blue Dart', 'docket_date': '2099-13-45'})
    record = prepared(service, life, ident, transport_mode='COURIER',
                      transport={'docket_number': 'BD1', 'courier_name': 'Blue Dart', 'docket_date': '2099-01-02'})
    assert record['transport']['docket_date'] == '2099-01-02'


def test_switching_mode_shows_only_that_modes_fields_and_clears_the_others(qtbot, service, customer):
    from legacy_desktop.ui_widgets import Form
    from legacy_desktop.dispatch_ui import MODE_LABELS, transport_fields
    from repairshop.contacts import Contacts
    operator = Contacts(service).save('transporter', dict(name='Sharma Travels', mobile='9990012345',
        route_from='Pune', route_to='Bhubaneswar', vehicle_number='MH12AB1234'))
    form = Form('Transport', None)
    qtbot.addWidget(form)
    selector = form.select('transport_mode', 'Transport mode', MODE_LABELS, 'COURIER')
    gather = transport_fields(form, selector, service=service)
    form.show()

    visible = lambda: {k for k, w in form.fields.items() if k != 'transport_mode'
                       and k.startswith('transport_') and w.isVisible()}
    assert visible() == {'transport_COURIER_docket_number', 'transport_COURIER_courier_name',
                         'transport_COURIER_docket_date'}
    form.fields['transport_COURIER_docket_number'].setText('BD12345')

    selector.setCurrentIndex(selector.findData('BUS'))
    assert visible() == {'transport_BUS_service', 'transport_BUS_bus_number', 'transport_BUS_parcel_number',
                         'transport_BUS_departure_date', 'transport_BUS_departure_time',
                         'transport_BUS_arrival_date', 'transport_BUS_arrival_time'}
    # The courier value is gone, so it cannot be saved against a bus dispatch.
    assert form.fields['transport_COURIER_docket_number'].text() == ''

    picker = form.fields['transport_BUS_service']
    picker.box.setCurrentIndex(picker.box.findData(operator))
    # The usual bus is offered, and stays editable because tonight's bus may differ.
    assert form.fields['transport_BUS_bus_number'].text() == 'MH12AB1234'
    assert 'Pune → Bhubaneswar' in picker.card.text()
    form.fields['transport_BUS_bus_number'].setText('MH12XY9999')
    form.fields['transport_BUS_parcel_number'].setText('P-77')
    mode, transport, transporter = gather(form.values())
    assert (mode, transporter) == ('BUS', operator)
    assert transport == {'bus_number': 'MH12XY9999', 'parcel_number': 'P-77'}

    selector.setCurrentIndex(selector.findData('IN_HAND'))
    assert visible() == {'transport_IN_HAND_person_name', 'transport_IN_HAND_mobile', 'transport_IN_HAND_role',
                         'transport_IN_HAND_departure_date', 'transport_IN_HAND_departure_time'}
    assert gather(form.values())[1:] == ({}, None)
    form.close()
