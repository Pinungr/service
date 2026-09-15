"""Structured addresses, richer intake evidence, third-party quotations, returns, billing."""
import json
import sqlite3
import uuid
import pytest
from repairshop.domain import RuleError, rupees
from repairshop.lifecycle import Lifecycle, intake_warranty
from repairshop.persistence import Database, SCHEMA_VERSION
from repairshop.billing import Billing
from repairshop.party_quotes import PartyQuotes
from repairshop.returns import Returns
from repairshop.visits import Visits


def master(s, kind, name):
    return next(r['id'] for r in s.masters(kind) if r['name'] == name)


def product(s, customer, name, category='Laptop', **extra):
    return dict(customer_id=customer, device=name, complaint='Fault on ' + name,
                category_id=master(s, 'category', category),
                service_id=master(s, 'service', category + ' repair'), guided=True, **extra)


ADDRESS = dict(address_line1='12 MG Road', address_line2='Near the clock tower',
               pincode='411001', district='Pune', state='Maharashtra')


# ---- 1. structured customer address -------------------------------------

def test_structured_address_saves_reads_and_composes_the_legacy_column(service):
    ident = service.save_customer('Structured Person', '9990000021', **ADDRESS)
    row = service.db.one('SELECT * FROM customers WHERE id=?', (ident,))
    for key, value in ADDRESS.items():
        assert row[key] == value
    assert '12 MG Road' in row['address'] and '411001' in row['address'] and 'Maharashtra' in row['address']


def test_invalid_pin_code_is_rejected(service):
    for bad in ('41100', '4110011', 'ABC123', ''):
        with pytest.raises(RuleError, match='6-digit PIN'):
            service.save_customer('Bad PIN', '9990000022', **dict(ADDRESS, pincode=bad))
    assert not service.db.rows("SELECT id FROM customers WHERE name='Bad PIN'")


def test_address_requires_line1_district_and_state(service):
    for field, message in (('address_line1', 'Address Line 1'), ('district', 'District'), ('state', 'State')):
        with pytest.raises(RuleError, match=message):
            service.save_customer('Incomplete', '9990000023', **dict(ADDRESS, **{field: ''}))


def test_quick_registration_without_any_address_still_works(service):
    ident = service.save_customer('Counter Walk-in', '9990000024', complete=False)
    assert service.db.one('SELECT pincode FROM customers WHERE id=?', (ident,))['pincode'] == ''


def test_migration_moves_free_text_address_into_line1(service, tmp_path):
    import shutil
    ident = service.save_customer('Legacy Address', '9990000025', complete=False)
    with service.db.transaction() as c:
        c.execute("UPDATE customers SET address=?,address_line1='',address_line2='' WHERE id=?",
                  ('9 Old Street\nShivajinagar', ident))
    target = tmp_path / 'legacy-address'
    shutil.copytree(service.db.root, target, ignore=shutil.ignore_patterns('shop.db*'))
    with service.db.read() as source:
        with sqlite3.connect(target / 'shop.db') as c:
            source.driver_connection.backup(c)
    with sqlite3.connect(target / 'shop.db') as c:
        c.execute('DROP INDEX ix_customer_pincode')
        for column in ('address_line1', 'address_line2', 'pincode', 'district', 'state'):
            c.execute('ALTER TABLE customers DROP COLUMN ' + column)
        c.execute('PRAGMA user_version=11')
    upgraded = Database(target)
    assert upgraded.one('PRAGMA user_version')['user_version'] == SCHEMA_VERSION
    row = upgraded.one('SELECT * FROM customers WHERE id=?', (ident,))
    assert row['address_line1'] == '9 Old Street'
    assert row['address_line2'] == 'Shivajinagar'
    assert row['address'] == '9 Old Street\nShivajinagar'


# ---- 2/3. accessories, photos -------------------------------------------

def accessory_photo(service, customer, name):
    from PyQt6.QtGui import QImage, QColor
    from repairshop.customer_records import CustomerRecords
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#445566'))
    return CustomerRecords(service).save_photo(image, customer, 'accessory', name)


def test_accessories_record_condition_notes_and_photo(service, customer):
    photo = accessory_photo(service, customer, 'Charger')
    job = service.intake(**product(service, customer, 'Dell Laptop'), accessories=[
        dict(type='accessory', description='Charger', quantity=1, condition='Working',
             notes='Original Dell charger', photo_id=photo),
        dict(type='accessory', description='Bag', quantity=1, condition='Not Tested'),
        dict(type='accessory', description='Mouse', quantity=1, condition='Not Working')])
    rows = {r['description']: r for r in service.db.rows(
        "SELECT description,condition,notes,photo_id FROM items WHERE job_id=? AND type='accessory'", (job,))}
    assert rows['Charger']['condition'] == 'Working'
    assert rows['Charger']['notes'] == 'Original Dell charger'
    assert rows['Charger']['photo_id'] == photo
    assert rows['Bag']['condition'] == 'Not Tested'
    assert rows['Mouse']['condition'] == 'Not Working'


def test_unsupported_accessory_condition_is_rejected(service, customer):
    with pytest.raises(RuleError, match='Not Tested'):
        service.intake(**product(service, customer, 'Dell Laptop'),
                       accessories=[dict(type='accessory', description='Charger', quantity=1, condition='Maybe')])
    assert not service.db.rows('SELECT id FROM jobs')


def test_accessories_belong_to_their_own_product_in_a_multi_product_visit(service, customer):
    laptop, mobile = service.intake_visit([
        dict(product(service, customer, 'Dell Laptop'),
             accessories=[dict(type='accessory', description='Charger', quantity=1, condition='Working'),
                          dict(type='accessory', description='Bag', quantity=1, condition='Not Tested')]),
        dict(product(service, customer, 'Samsung Mobile', 'Phone'),
             accessories=[dict(type='accessory', description='USB cable', quantity=1, condition='Working')])],
        'accessory-visit')
    def names(job):
        return {r['description'] for r in service.db.rows(
            "SELECT description FROM items WHERE job_id=? AND type='accessory'", (job,))}
    assert names(laptop) == {'Charger', 'Bag'}
    assert names(mobile) == {'USB cable'}


def test_product_photo_is_stored_against_the_right_job_and_device(service, customer):
    from PyQt6.QtGui import QImage, QColor
    from repairshop.customer_records import CustomerRecords
    job = service.intake(**product(service, customer, 'Dell Laptop'))
    device = service.job(job)['device_id']
    image = QImage(48, 48, QImage.Format.Format_RGB32)
    image.fill(QColor('#227722'))
    photo = CustomerRecords(service).save_photo(image, customer, 'product', device_id=device, job_id=job)
    row = service.db.one('SELECT * FROM attachments WHERE id=?', (photo,))
    assert row['kind'] == 'product_photo' and row['job_id'] == job and row['device_id'] == device


# ---- 5/6. initial estimate and customer requirement ---------------------

def test_initial_estimate_and_requirement_are_saved_per_job(service, customer):
    laptop, mobile = service.intake_visit([
        dict(product(service, customer, 'Dell Laptop'), initial_estimate=500000,
             customer_requirement='Back up all documents before reinstalling Windows.'),
        dict(product(service, customer, 'Samsung Mobile', 'Phone'), initial_estimate=150000)],
        'estimate-visit')
    assert service.job(laptop)['initial_estimate'] == 500000
    assert service.job(laptop)['customer_requirement'].startswith('Back up all documents')
    assert service.job(mobile)['initial_estimate'] == 150000
    assert service.job(mobile)['customer_requirement'] == ''
    total = sum(service.job(i)['initial_estimate'] for i in (laptop, mobile))
    assert total == 650000


def test_negative_initial_estimate_is_rejected(service, customer):
    with pytest.raises(RuleError, match='nonnegative'):
        service.intake(**product(service, customer, 'Dell Laptop'), initial_estimate=-100)


def test_initial_estimate_survives_quotation_and_final_bill(service, customer):
    job, life = at_estimate(service, customer, estimate=500000)
    quote = service.issue_quote(job, 'Display repair', [{'description': 'Display', 'amount': 650000}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    assert service.job(job)['initial_estimate'] == 500000
    summary = Billing(service).summary(job)
    assert summary['initial_estimate'] == 500000
    assert summary['approved_total'] == 650000
    assert summary['initial_estimate'] != summary['approved_total']


# ---- 7/8. documents -----------------------------------------------------

def test_single_product_intake_creates_one_visit_receipt_and_one_job_card(service, customer):
    from repairshop.documents import Documents
    from repairshop.job_cards import JobCards
    job = service.intake(**product(service, customer, 'Dell Laptop'), initial_estimate=500000,
                         customer_requirement='Call before replacing the battery.')
    cards = [r for r in JobCards(service).rows(job) if r['kind'] == 'customer_receiving']
    assert len(cards) == 1
    snapshot = json.loads(cards[0]['snapshot'])
    assert snapshot['initial_estimate'] == 500000
    assert snapshot['customer_requirement'] == 'Call before replacing the battery.'
    assert snapshot['visit'].startswith('VIS-')
    assert JobCards(service).print(cards[0]['id']).read_bytes().startswith(b'%PDF')
    assert Documents(service).visit_receipt([job]).read_bytes().startswith(b'%PDF')


def test_multi_product_intake_creates_one_receipt_and_a_card_per_job(service, customer):
    from repairshop.documents import Documents
    from repairshop.job_cards import JobCards
    jobs = service.intake_visit([
        dict(product(service, customer, 'Dell Laptop'), initial_estimate=500000),
        dict(product(service, customer, 'Samsung Mobile', 'Phone'), initial_estimate=150000),
        dict(product(service, customer, 'HP Printer', 'Printer'), initial_estimate=200000)], 'doc-visit')
    for job in jobs:
        assert len([r for r in JobCards(service).rows(job) if r['kind'] == 'customer_receiving']) == 1
    receipt = Documents(service).visit_receipt(jobs)
    assert receipt.read_bytes().startswith(b'%PDF')
    assert len(service.db.rows("SELECT id FROM attachments WHERE kind='issued_document' AND title LIKE '%visit receiving%'")) == 1


def test_documents_render_on_a4_and_a5(service, customer):
    from repairshop.documents import Documents
    jobs = service.intake_visit([dict(product(service, customer, 'Dell Laptop'), initial_estimate=500000),
                                 dict(product(service, customer, 'HP Printer', 'Printer'), initial_estimate=200000)],
                                'paper-visit')
    docs = Documents(service)
    a4 = docs.visit_receipt(jobs, paper='A4')
    a5 = docs.visit_receipt(jobs, paper='A5')
    assert a4.read_bytes().startswith(b'%PDF') and a5.read_bytes().startswith(b'%PDF')
    # A5 is a genuinely different page, not the same bytes with a scale factor.
    assert a4.read_bytes() != a5.read_bytes()
    service.settings({'paper_size': 'A5'})
    assert docs.paper() == 'A5' and docs.paper('A4') == 'A4'


# ---- 9. post-confirmation messaging is never part of the intake ---------

def test_messaging_failure_does_not_roll_back_the_intake(service, customer, monkeypatch):
    jobs = service.intake_visit([dict(product(service, customer, 'Dell Laptop'), initial_estimate=500000)],
                                'messaging-visit')
    from repairshop.documents import Documents
    Documents(service).visit_receipt(jobs)
    attachment = service.db.one("SELECT id FROM attachments WHERE kind='issued_document' ORDER BY id DESC")['id']
    def explode(*args, **kwargs):
        raise RuntimeError('WhatsApp provider unreachable')
    monkeypatch.setattr(service, 'audit', explode)
    with pytest.raises(RuntimeError):
        service.queue_customer_document(attachment, customer, ['whatsapp'], 'intake_receipt', 'Hi', 'op-1')
    monkeypatch.undo()
    assert service.job(jobs[0])['id'] == jobs[0]
    assert Visits(service).for_customer(customer)[0]['products'] == 1
    assert service.db.one('SELECT count(*) n FROM outbox')['n'] >= 0
    queued = service.queue_customer_document(attachment, customer, ['whatsapp', 'email'], 'intake_receipt', 'Hi', 'op-2')
    assert {r['channel']: r['state'] for r in queued} == {'whatsapp': 'pending', 'email': 'pending'}


def test_print_and_photo_settings_are_validated(service):
    service.settings({'paper_size': 'A5', 'include_photos': True})
    assert service.db.setting('paper_size') == 'A5' and service.db.setting('include_photos') is True
    with pytest.raises(RuleError, match='A4 or A5'):
        service.settings({'paper_size': 'Letter'})
    with pytest.raises(RuleError, match='Yes or No'):
        service.settings({'include_photos': 'maybe'})


# ---- 12. conditional warranty lifecycle --------------------------------

def guided(service, customer, warranty_status, expiry=None):
    payload = dict(product(service, customer, 'Dell Laptop'))
    payload['intake_warranty'] = dict(source='external', status=warranty_status, expiry=expiry)
    job = service.intake(**payload)
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Inspected at the counter'})
    return job, life


def test_valid_intake_warranty_still_shows_the_warranty_stage(service, customer):
    job, life = guided(service, customer, 'VALID', '2099-01-01')
    assert service.job(job)['stage'] == 'warranty_check'
    assert 'verify_warranty' in life.snapshot(job)['actions']
    assert any(step['key'] == 'warranty_check' for step in life.snapshot(job)['tracker'])


def test_expired_or_absent_warranty_skips_the_warranty_stage(service, customer):
    for status in ('EXPIRED', 'NONE'):
        job, life = guided(service, customer, status)
        assert service.job(job)['stage'] == 'route_selection'
        v = life.snapshot(job)
        assert v['data']['warranty_status'] == 'out_of_warranty'
        assert not any(step['key'] == 'warranty_check' for step in v['tracker'])
        assert service.db.one("""SELECT 1 n FROM audit WHERE entity='job' AND entity_id=?
            AND action='warranty_stage_skipped'""", (job,))


def test_warranty_eligibility_uses_the_intake_snapshot_not_today(service, customer):
    # Collected while covered; the cover lapses before the service centre looks at it.
    snapshot = {'intake_warranty': {'source': 'external', 'status': 'VALID',
                                    'expiry': '2026-09-16', 'checked_on': '2026-09-14'}}
    assert intake_warranty(snapshot)['eligible'] is True
    assert intake_warranty(snapshot)['expiry'] == '2026-09-16'
    assert intake_warranty({'intake_warranty': {'status': 'EXPIRED'}})['eligible'] is False
    # A job recorded before this feature existed keeps the manual check.
    assert intake_warranty({})['eligible'] is True


# ---- 13/14/15. third party directory, reference, quotations ------------

def third_party(service, name='ABC Mobile Repair'):
    return service.save_master('vendor', name, contact='9998887771', specialization='Mobile board repair', **ADDRESS)


def test_third_party_directory_stores_structured_address_and_specialization(service):
    ident = third_party(service)
    row = service.db.one('SELECT * FROM masters WHERE id=?', (ident,))
    for key, value in ADDRESS.items():
        assert row[key] == value
    assert row['specialization'] == 'Mobile board repair'
    assert row['photo_id'] is None


def test_third_party_address_requires_a_mobile_number(service):
    with pytest.raises(RuleError, match='mobile'):
        service.save_master('vendor', 'No Contact Repair', **ADDRESS)


def test_postal_address_is_rejected_for_non_party_directories(service):
    with pytest.raises(RuleError, match='third parties'):
        service.save_master('category', 'Tablet', **ADDRESS)


def external_repair(service, customer, estimate=0, party='ABC Mobile Repair'):
    job = service.intake(**product(service, customer, 'Samsung Mobile', 'Phone'), initial_estimate=estimate,
                         accessories=[dict(type='accessory', description='Charger', quantity=1, condition='Working')])
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Charging port damage'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'No proof'})
    life.execute(job, 'select_route', {'route': 'third_party', 'confirmed': True,
                                       'contact_id': third_party(service, party), 'reference': 'TP-1245'})
    return job, life


def at_estimate(service, customer, estimate=0):
    """Third-party repair progressed to the point where a customer estimate is due."""
    job, life = external_repair(service, customer, estimate=estimate)
    life.execute(job, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(job)], consent=True,
                                               condition='Intact', expected_return='2099-01-01'))
    life.execute(job, 'dispatch', dict(counterparty='Repairer', condition='Intact', acknowledgment='D1'))
    life.execute(job, 'diagnose', dict(notes='Charging port failure confirmed', repairable=True))
    return job, life


def test_assignment_keeps_the_job_as_the_internal_reference_and_an_external_one(service, customer):
    job, life = external_repair(service, customer)
    assignment = service.db.one('SELECT * FROM assignments WHERE job_id=? ORDER BY id DESC', (job,))
    # The owner types only the third party's own ticket; the job number is authoritative.
    assert assignment['reference'] == 'TP-1245'
    v = life.snapshot(job)
    assert v['number'].startswith('REP-')
    assert v['assignment']['reference'] == 'TP-1245'


def test_third_party_quotation_is_versioned_and_v1_stays_readable(service, customer):
    job, life = external_repair(service, customer)
    quotes = PartyQuotes(service)
    v1 = quotes.issue(job, [dict(kind='part', name='Display', quantity=1, unit_cost=200000, customer_charge=250000),
                            dict(kind='part', name='Connector', quantity=1, unit_cost=35000, customer_charge=50000)],
                      labour=100000, transport=25000, reference='TPQ-1')
    current = quotes.current(job)
    assert current['id'] == v1 and current['version'] == 1
    assert current['parts_total'] == 235000 and current['total'] == 360000
    with pytest.raises(RuleError, match='why'):
        quotes.issue(job, [dict(kind='part', name='Battery', quantity=1, unit_cost=120000)], labour=100000)
    v2 = quotes.issue(job, [dict(kind='part', name='Display', quantity=1, unit_cost=200000, customer_charge=250000),
                            dict(kind='part', name='Connector', quantity=1, unit_cost=35000, customer_charge=50000),
                            dict(kind='part', name='Battery', quantity=1, unit_cost=120000, customer_charge=150000)],
                      labour=100000, transport=25000, reason='Third party found a failed battery')
    history = quotes.history(job)
    assert [r['version'] for r in history] == [1, 2]
    assert history[0]['state'] == 'superseded' and history[1]['state'] == 'current'
    assert history[0]['total'] == 360000 and history[1]['total'] == 480000
    assert [l['name'] for l in history[0]['lines']] == ['Display', 'Connector']
    assert [l['name'] for l in history[1]['lines']] == ['Display', 'Connector', 'Battery']
    assert history[1]['supersedes_id'] == v1
    assert history[1]['revision_reason'] == 'Third party found a failed battery'


def test_issued_third_party_quotation_cannot_be_rewritten_or_deleted(service, customer):
    job, life = external_repair(service, customer)
    ident = PartyQuotes(service).issue(job, [dict(kind='part', name='Display', quantity=1, unit_cost=200000)])
    for statement, args in (('UPDATE party_quotes SET total=1 WHERE id=?', (ident,)),
                            ('DELETE FROM party_quotes WHERE id=?', (ident,)),
                            ('UPDATE party_quote_lines SET unit_cost=1 WHERE quote_id=?', (ident,)),
                            ('DELETE FROM party_quote_lines WHERE quote_id=?', (ident,))):
        with pytest.raises(sqlite3.IntegrityError):
            with service.db.transaction() as c:
                c.execute(statement, args)


def test_third_party_parts_are_not_added_to_shop_inventory(service, customer):
    job, life = external_repair(service, customer)
    PartyQuotes(service).issue(job, [dict(kind='part', name='Display', quantity=1, unit_cost=200000,
                                          customer_charge=250000, warranty='3 months third-party')])
    assert not service.db.rows('SELECT id FROM stock_items')
    assert not service.db.rows('SELECT id FROM repair_parts WHERE job_id=?', (job,))
    assert not service.db.rows('SELECT id FROM stock_movements')


def test_third_party_cost_and_customer_charge_stay_separate(service, customer):
    job, life = external_repair(service, customer)
    PartyQuotes(service).issue(job, [dict(kind='part', name='Display', quantity=1, unit_cost=200000, customer_charge=250000)],
                               labour=100000, transport=20000)
    quotes = PartyQuotes(service)
    assert quotes.internal_total(job) == 320000
    onward = quotes.customer_lines(job)
    assert len(onward) == 1 and onward[0]['amount'] == 250000
    # The internal labour and transport are not pushed at the customer automatically.
    assert sum(l['amount'] for l in onward) != quotes.internal_total(job)


# ---- 19/20. approval breakdown and the approval ceiling ----------------

def test_approved_quotation_breaks_down_by_service_parts_and_transport(service, customer):
    job, life = at_estimate(service, customer, estimate=500000)
    quote = service.issue_quote(job, 'Charging port repair', [
        {'description': 'Service / labour', 'amount': 150000, 'kind': 'service'},
        {'description': 'Display', 'amount': 250000, 'kind': 'part'},
        {'description': 'Connector', 'amount': 50000, 'kind': 'part'},
        {'description': 'Outbound courier', 'amount': 25000, 'kind': 'transport'},
        {'description': 'Return courier', 'amount': 25000, 'kind': 'transport'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    summary = Billing(service).summary(job)
    totals = summary['approved_breakdown']['totals']
    assert totals['service'] == 150000
    assert totals['parts'] == 300000
    assert totals['transport'] == 50000
    assert summary['approved_total'] == 500000
    assert summary['approved_version'] == 1
    decision = service.db.one('SELECT * FROM decisions WHERE quote_id=?', (quote,))
    assert decision['amount'] == 500000


def test_final_bill_cannot_silently_exceed_the_approved_quotation(service, customer):
    job, life = at_estimate(service, customer)
    first = service.issue_quote(job, 'Repair', [{'description': 'Repair', 'amount': 500000}])
    service.decide_quote(first, 'approved', 'Device owner', 'in_person')
    # Extra cost appears: a revised quotation supersedes the approval and cannot be billed
    # until the customer has approved the new version.
    revised = service.issue_quote(job, 'Repair plus battery', [{'description': 'Repair and battery', 'amount': 650000}])
    with pytest.raises(RuleError, match='approved quotation'):
        service.invoice(revised, uuid.uuid4().hex)
    assert not service.db.rows("SELECT id FROM entries WHERE kind='invoice'")
    # The ceiling itself refuses any amount above the current approval.
    with service.db.transaction() as c:
        with pytest.raises(RuleError, match='exceeds approved quotation version 1'):
            Billing(service).guard_final_bill(c, job, 650000)
        Billing(service).guard_final_bill(c, job, 500000)
    service.decide_quote(revised, 'approved', 'Device owner', 'in_person')
    entry = service.invoice(revised, uuid.uuid4().hex)
    assert service.db.one('SELECT amount FROM entries WHERE id=?', (entry,))['amount'] == 650000


# ---- 21. physical return verification ----------------------------------

def dispatched(service, customer):
    job, life = external_repair(service, customer, estimate=500000)
    life.execute(job, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(job)], consent=True,
                                               condition='Intact', expected_return='2099-01-01',
                                               transport_mode='COURIER',
                                               transport={'courier_name': 'Blue Dart', 'docket_number': 'BD1'}))
    life.execute(job, 'dispatch', dict(counterparty='Courier', condition='Intact', acknowledgment='D1'))
    life.execute(job, 'diagnose', dict(notes='Port failure', repairable=True))
    quote = service.issue_quote(job, 'Port repair', [{'description': 'Port', 'amount': 300000}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    life.execute(job, 'start_repair')
    life.execute(job, 'complete_repair', dict(notes='Port replaced', parts='Port'))
    return job, life


def test_return_screen_lists_every_dispatched_item(service, customer):
    job, life = dispatched(service, customer)
    expected = Returns(service).expected(job)
    assert {r['description'] for r in expected['items']} == {'Samsung Mobile', 'Charger'}
    assert all(r['available'] for r in expected['items'])
    assert expected['party'] == 'ABC Mobile Repair'


def test_receipt_is_blocked_until_short_units_are_explained(service, customer):
    job, life = dispatched(service, customer)
    items = {r['item_id']: r['expected'] for r in Returns(service).expected(job)['items']}
    charger = next(i for i, _ in items.items()
                   if service.db.one('SELECT description FROM items WHERE id=?', (i,))['description'] == 'Charger')
    short = dict(items); short[charger] = 0
    with pytest.raises(RuleError, match='not been verified'):
        Returns(service).verify(job, short, 'op-short', storage='shop:Front desk')
    assert not service.db.rows('SELECT id FROM return_verifications')
    ident = Returns(service).verify(job, short, 'op-short-2', storage='shop:Front desk',
                                    discrepancies=[dict(item_id=charger, kind='missing', received=0,
                                                        notes='Third party could not find the charger')])
    rows = Returns(service).verifications(job)
    assert len(rows) == 1 and rows[0]['id'] == ident and not rows[0]['complete']
    assert rows[0]['discrepancies'][0]['kind'] == 'missing'


def test_discrepancy_needs_a_reason_and_a_dispatched_item(service, customer):
    job, life = dispatched(service, customer)
    items = {r['item_id']: r['expected'] for r in Returns(service).expected(job)['items']}
    first = next(iter(items))
    with pytest.raises(RuleError, match='Explain'):
        Returns(service).verify(job, items, 'op-a', storage='shop:Front desk',
                                discrepancies=[dict(item_id=first, kind='damaged', notes='  ')])
    with pytest.raises(RuleError, match='supported discrepancy'):
        Returns(service).verify(job, items, 'op-b', storage='shop:Front desk',
                                discrepancies=[dict(item_id=first, kind='exploded', notes='x')])


def test_verification_alone_never_moves_custody(service, customer):
    job, life = dispatched(service, customer)
    before = service.db.rows('''SELECT h.* FROM holdings h JOIN items i ON i.id=h.item_id
        WHERE i.job_id=? ORDER BY h.item_id,h.location''', (job,))
    items = {r['item_id']: r['expected'] for r in Returns(service).expected(job)['items']}
    Returns(service).verify(job, items, 'op-no-move', storage='shop:Front desk')
    after = service.db.rows('''SELECT h.* FROM holdings h JOIN items i ON i.id=h.item_id
        WHERE i.job_id=? ORDER BY h.item_id,h.location''', (job,))
    assert before == after


def test_confirmed_receive_verifies_and_then_moves_custody(service, customer):
    job, life = dispatched(service, customer)
    life.execute(job, 'receive', dict(counterparty='Counter staff', condition='Intact', acknowledgment='R1',
                                      storage='shop:Front desk', repair_result='REPAIRED',
                                      receiver_kind='storage', operation_id='op-receive'))
    assert all(h['location'].startswith('shop:') for h in life.holdings(job))
    rows = Returns(service).verifications(job)
    assert len(rows) == 1 and rows[0]['complete'] and rows[0]['storage'] == 'shop:Front desk'
    assert service.db.one("""SELECT 1 n FROM audit WHERE entity='job' AND entity_id=?
        AND action='return_verified'""", (job,))


# ---- 22/23. final billing and the review screen ------------------------

def test_final_bill_draws_on_installed_parts_and_approved_third_party_parts(service, customer):
    job, life = dispatched(service, customer)
    PartyQuotes(service).issue(job, [dict(kind='part', name='Charging port', quantity=1,
                                          unit_cost=100000, customer_charge=150000, warranty='3 months')])
    summary = Billing(service).summary(job)
    assert [l['description'] for l in summary['third_party_customer_lines']] == ['Charging port']
    assert summary['third_party_customer_lines'][0]['amount'] == 150000
    assert summary['installed_parts'] == []


def test_review_billing_shows_estimate_approved_bill_advance_and_balance(service, customer):
    job, life = at_estimate(service, customer, estimate=500000)
    service.post('customer', customer, 'receipt', 100000, uuid.uuid4().hex, job_id=job, notes='Intake advance')
    quote = service.issue_quote(job, 'Repair', [{'description': 'Service / labour', 'amount': 650000, 'kind': 'service'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    service.invoice(quote, uuid.uuid4().hex)
    s = Billing(service).summary(job)
    assert s['initial_estimate'] == 500000
    assert s['approved_total'] == 650000
    assert s['final_bill'] == 650000
    assert s['advance'] == 100000
    assert s['other_payments'] == 0
    assert s['balance_due'] == 550000
    rows = dict(Billing(service).readable(job))
    assert rows['Initial estimate at intake'] == rupees(500000)
    assert rows['Final bill'] == rupees(650000)
    assert rows['Balance due'] == rupees(550000)
    assert rows['Service (approved)'] == rupees(650000)


def test_each_job_in_a_visit_keeps_its_own_billing(service, customer):
    laptop, mobile = service.intake_visit([
        dict(product(service, customer, 'Dell Laptop'), initial_estimate=500000, guided=False),
        dict(product(service, customer, 'Samsung Mobile', 'Phone'), initial_estimate=150000, guided=False)], 'billing-visit')
    for job, amount in ((laptop, 500000), (mobile, 200000)):
        quote = service.issue_quote(job, 'Repair', [{'description': 'Repair', 'amount': amount}])
        service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
        service.invoice(quote, uuid.uuid4().hex)
    assert Billing(service).summary(laptop)['final_bill'] == 500000
    assert Billing(service).summary(mobile)['final_bill'] == 200000
    assert Billing(service).summary(laptop)['initial_estimate'] == 500000
    # Independent ledgers: neither job's bill absorbs the other.
    per_job = service.db.rows("""SELECT job_id,sum(amount) n FROM entries
        WHERE account_type='customer' AND kind='invoice' GROUP BY job_id ORDER BY job_id""")
    assert [r['n'] for r in per_job] == [500000, 200000]


# ---- end-to-end regression ---------------------------------------------

def test_full_third_party_repair_from_intake_to_close(service, customer):
    """One visit, two products, one sent to a third party, billed, delivered and closed."""
    from repairshop.documents import Documents
    laptop, mobile = service.intake_visit([
        dict(product(service, customer, 'Dell Laptop'), initial_estimate=500000,
             customer_requirement='Back up documents first.',
             accessories=[dict(type='accessory', description='Charger', quantity=1, condition='Working')]),
        dict(product(service, customer, 'Samsung Mobile', 'Phone'), initial_estimate=150000)],
        'end-to-end', notes='Walk-in')
    assert Documents(service).visit_receipt([laptop, mobile]).read_bytes().startswith(b'%PDF')
    life = Lifecycle(service)
    life.execute(mobile, 'inspect')
    life.execute(mobile, 'inspection_done', {'notes': 'Charging port damage'})
    life.execute(mobile, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'No proof'})
    life.execute(mobile, 'select_route', {'route': 'third_party', 'confirmed': True,
                                          'contact_id': third_party(service), 'reference': 'TP-9'})
    life.execute(mobile, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(mobile)], consent=True,
                                                  condition='Intact', expected_return='2099-01-01',
                                                  transport_mode='BUS',
                                                  transport={'bus_name': 'Shivneri', 'bus_number': 'MH12AB1234'}))
    life.execute(mobile, 'dispatch', dict(counterparty='Bus office', condition='Intact', acknowledgment='D9'))
    life.execute(mobile, 'diagnose', dict(notes='Port failure', repairable=True))
    PartyQuotes(service).issue(mobile, [dict(kind='part', name='Charging port', quantity=1,
                                             unit_cost=90000, customer_charge=140000)],
                               labour=60000, transport=20000, reference='TPQ-9')
    quote = service.issue_quote(mobile, 'Charging port repair', [
        {'description': 'Service / labour', 'amount': 110000, 'kind': 'service'},
        {'description': 'Charging port', 'amount': 140000, 'kind': 'part'},
        {'description': 'Bus transport', 'amount': 20000, 'kind': 'transport'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    life.execute(mobile, 'start_repair')
    life.execute(mobile, 'complete_repair', dict(notes='Port replaced', parts='Charging port'))
    life.execute(mobile, 'receive', dict(counterparty='Counter staff', condition='Intact', acknowledgment='R9',
                                         storage='shop:Front desk', repair_result='REPAIRED',
                                         receiver_kind='storage', operation_id='e2e-receive'))
    assert Returns(service).verifications(mobile)[0]['complete']
    life.execute(mobile, 'qc', dict(result='passed', notes='Charging verified',
                                    checks={k: 'passed' for k in ('functional', 'power', 'charging',
                                                                  'display', 'connectivity', 'complaint')},
                                    repair_warranty='30 days', warranty_until='2099-01-01'))
    life.execute(mobile, 'bill', {'confirmed': True})
    s = Billing(service).summary(mobile)
    assert s['initial_estimate'] == 150000 and s['approved_total'] == 270000 and s['final_bill'] == 270000
    assert s['approved_breakdown']['totals'] == {'service': 110000, 'parts': 140000, 'transport': 20000, 'other': 0}
    # Third-party cost stays internal and is not what the customer was billed.
    assert PartyQuotes(service).internal_total(mobile) == 170000
    service.post('customer', customer, 'receipt', 270000, uuid.uuid4().hex, job_id=mobile)
    life.execute(mobile, 'handover', dict(demonstrated=True, accepted=True, accessories_returned=True,
                                          payment_checked=True, received_by='Device owner',
                                          acknowledgment='Signed receipt'))
    life.execute(mobile, 'close')
    assert service.job(mobile)['stage'] == 'closed'
    # The sibling job is untouched and the visit reports partial completion.
    assert service.job(laptop)['stage'] == 'received'
    assert Visits(service).for_customer(customer)[0]['status'] == 'Partly completed'
    assert Billing(service).summary(laptop)['final_bill'] == 0


def test_backup_archive_carries_the_new_records(service, customer, tmp_path):
    import zipfile
    from repairshop.backup import Backups
    job, life = at_estimate(service, customer, estimate=500000)
    PartyQuotes(service).issue(job, [dict(kind='part', name='Display', quantity=1, unit_cost=200000)])
    service.save_customer('Structured Person', '9990000031', **ADDRESS)
    archive = Backups(service).create('manual', tmp_path / 'archives')
    restored = tmp_path / 'restored.db'
    with zipfile.ZipFile(archive) as z:
        restored.write_bytes(z.read('shop.db'))
    with sqlite3.connect(restored) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert c.execute('SELECT count(*) FROM party_quotes').fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM party_quote_lines').fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM customers WHERE pincode='411001'").fetchone()[0] == 1
        assert c.execute('SELECT initial_estimate FROM jobs WHERE id=?', (job,)).fetchone()[0] == 500000
