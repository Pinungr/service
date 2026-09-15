"""One full release rehearsal: three products, three repair routes, money, evidence, backup.

This walks the scenario a shop actually performs in a day and checks the database,
lifecycle, custody, money, audit, role, attachment and notification state as it goes, so
the fixes are verified on the real business path rather than only in isolation.
"""
import uuid
import zipfile
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.backup import Backups
from repairshop.billing import Billing
from repairshop.customer_records import CustomerRecords
from repairshop.documents import Documents
from repairshop.domain import RuleError
from repairshop.lifecycle import Lifecycle
from repairshop.messaging import Outbox
from repairshop.party_quotes import PartyQuotes
from repairshop.returns import Returns
from repairshop.visits import Visits

ADDRESS = dict(address_line1='12 Station Road', address_line2='Near the clock tower',
               pincode='411001', district='Pune', state='Maharashtra')
CHECKS = {k: 'passed' for k in ('functional', 'power', 'charging', 'display', 'connectivity', 'complaint')}


def picture(colour):
    image = QImage(48, 48, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    return image


class Captured:
    """A stand-in provider that records what it was asked to deliver."""

    def __init__(self):
        self.sent = []

    def send(self, row, payload):
        self.sent.append(dict(channel=row['channel'], destination=row['destination'],
                              attachment=payload.get('_attachment_path')))
        return 'PROVIDER-' + uuid.uuid4().hex[:6]


def test_a_full_day_at_the_counter(service, tmp_path):
    records = CustomerRecords(service)
    life = Lifecycle(service)
    docs = Documents(service)

    # --- customer, photo, and a visit with three products --------------------
    customer = service.save_customer('Release Rehearsal', '9990001234', 'rehearsal@example.invalid',
                                     whatsapp_consent=True, email_consent=True, **ADDRESS)
    records.save_photo(picture('#68a398'), customer)
    charger_photo = records.save_photo(picture('#445566'), customer, 'accessory', 'Charger')
    stored = service.db.one('SELECT * FROM customers WHERE id=?', (customer,))
    assert stored['pincode'] == '411001' and stored['district'] == 'Pune'

    def product(device, estimate, **extra):
        return dict(customer_id=customer, device=device, complaint='Will not power on',
                    guided=True, assessment_consent=True, initial_estimate=estimate, **extra)

    laptop, mobile, printer = service.intake_visit([
        product('Dell Laptop', 1500000, advance=300000, deposit=300000,
                customer_requirement='Back up my documents first.',
                accessories=[dict(type='accessory', description='Charger', quantity=1,
                                  condition='Working', notes='Original 65W', photo_id=charger_photo)]),
        product('Samsung Mobile', 500000, advance=200000, deposit=200000),
        product('HP Printer', 200000)], uuid.uuid4().hex, notes='Walk-in, three products')

    # --- visit totals keep estimate and advance apart (P0-1) -----------------
    visit = Visits(service).for_job(laptop)
    assert visit['estimated_total'] == 2200000, 'the estimate is the sum of the initial estimates'
    assert visit['advance_total'] == 500000, 'the advance is the money actually received'
    assert visit['products'] == 3
    assert service.db.one('SELECT job_id FROM attachments WHERE id=?', (charger_photo,))['job_id'] == laptop

    # --- documents at both paper sizes (P1-2) --------------------------------
    import re
    boxes = re.compile(rb'/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*\]')

    def sizes(path):
        return {(round(float(w)), round(float(h))) for w, h in boxes.findall(path.read_bytes())}

    assert sizes(docs.visit_receipt([laptop, mobile, printer], paper='A4')) == {(595, 842)}
    assert sizes(docs.visit_receipt([laptop, mobile, printer], paper='A5')) == {(420, 595)}
    receipt = service.db.one("SELECT id FROM attachments WHERE kind='issued_document' ORDER BY id DESC")['id']

    # --- delivery reports the truth per channel, and carries the PDF (P1-1/5) -
    outcomes = {r['channel']: r['state'] for r in service.queue_customer_document(
        receipt, customer, ['whatsapp', 'email'], 'intake_receipt',
        'Your products have been received.', uuid.uuid4().hex, job_id=laptop)}
    assert outcomes == {'whatsapp': 'pending', 'email': 'pending'}
    provider = Captured()
    worker = Outbox(service)
    worker.adapters = {'whatsapp': provider, 'email': provider}
    while worker.process_one():
        pass
    carried = [s for s in provider.sent if s['attachment']]
    assert {s['channel'] for s in carried} == {'whatsapp', 'email'}, 'both channels carry the receipt'
    assert all(s['attachment'].endswith('.pdf') for s in carried)

    # --- route 1: warranty service centre -----------------------------------
    life.execute(printer, 'inspect')
    life.execute(printer, 'inspection_done', {'notes': 'Head fault confirmed'})
    life.execute(printer, 'verify_warranty', {'warranty_status': 'under_warranty', 'notes': 'Invoice seen'})
    centre = service.save_master('centre', 'HP Authorized Centre', contact='9998887770', **ADDRESS)
    life.execute(printer, 'select_route', {'route': 'warranty_centre', 'confirmed': True, 'contact_id': centre})
    assert life.snapshot(printer)['route'] == 'warranty_centre'

    # --- route 2: in-house technician, scoped to that technician (P0-2) ------
    technician = service.save_staff('amit', 'Amit', 'technician', 'TestPassword123') or \
        service.db.one("SELECT id FROM users WHERE username='amit'")['id']
    bench = service.save_master('technician', 'Amit (bench)', user_id=technician)
    service.save_staff('ravi', 'Ravi', 'technician', 'TestPassword123')
    life.execute(laptop, 'inspect')
    life.execute(laptop, 'inspection_done', {'notes': 'Power rail fault'})
    life.execute(laptop, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'Out of cover'})
    life.execute(laptop, 'select_route', {'route': 'in_house', 'confirmed': True, 'technician_master_id': bench,
                                          'handed_over': True, 'bench': 'Bench 2', 'condition': 'Intact',
                                          'acknowledgment': 'Technician received'})
    service.login('ravi', 'TestPassword123')
    with pytest.raises(RuleError, match='assigned'):
        service.job(laptop)
    assert Lifecycle(service).rows() == [], 'an unassigned technician sees no work'
    service.login('amit', 'TestPassword123')
    assert [r['id'] for r in Lifecycle(service).rows()] == [laptop]
    Lifecycle(service).execute(laptop, 'diagnose', dict(notes='Power rail failed', repairable=True,
                                                        parts='Power board', parts_available=True))
    service.login('owner', 'CorrectHorse123!')

    # --- route 3: third party, dispatched, quoted, returned and verified -----
    vendor = service.save_master('vendor', 'ABC Board Repair', contact='9998887771', **ADDRESS)
    life.execute(mobile, 'inspect')
    life.execute(mobile, 'inspection_done', {'notes': 'Charging port damage'})
    life.execute(mobile, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'No proof'})
    life.execute(mobile, 'select_route', {'route': 'third_party', 'confirmed': True,
                                          'contact_id': vendor, 'reference': 'TP-9'})
    life.execute(mobile, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(mobile)], consent=True,
                                                  condition='Intact', expected_return='2099-01-01',
                                                  transport_mode='BUS',
                                                  transport={'bus_name': 'Shivneri', 'bus_number': 'MH12AB1234'}))
    life.execute(mobile, 'dispatch', dict(counterparty='Bus office', condition='Intact', acknowledgment='D9'))
    life.execute(mobile, 'diagnose', dict(notes='Port failure', repairable=True))
    PartyQuotes(service).issue(mobile, [dict(kind='part', name='Charging port', quantity=1,
                                             unit_cost=90000, customer_charge=140000)],
                               labour=60000, transport=20000, reference='TPQ-9')

    # --- customer quotation and approval ------------------------------------
    quote = service.issue_quote(mobile, 'Charging port repair', [
        {'description': 'Service / labour', 'amount': 110000, 'kind': 'service'},
        {'description': 'Charging port', 'amount': 140000, 'kind': 'part'},
        {'description': 'Bus transport', 'amount': 20000, 'kind': 'transport'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    life.execute(mobile, 'start_repair')
    life.execute(mobile, 'complete_repair', dict(notes='Port replaced', parts='Charging port'))

    # --- physical return verification before custody moves -------------------
    expected = Returns(service).expected(mobile)
    assert expected['items'], 'the return screen is built from the outbound manifest'
    life.execute(mobile, 'receive', dict(counterparty='Counter staff', condition='Intact', acknowledgment='R9',
                                         repair_result='REPAIRED',
                                         receiver_kind='storage', operation_id='e2e-receive'))
    verification = Returns(service).verifications(mobile)[0]
    assert verification['complete'] and not verification['discrepancies']
    assert not Returns(service).open_discrepancies(mobile)

    # --- QC, billing against the approved quotation, payment -----------------
    life.execute(mobile, 'qc', dict(result='passed', notes='Charging verified', checks=CHECKS,
                                    repair_warranty='30 days', warranty_until='2099-01-01'))
    life.execute(mobile, 'bill', {'confirmed': True})
    money = Billing(service).summary(mobile)
    assert money['initial_estimate'] == 500000, 'the counter estimate survives the whole repair'
    assert money['approved_total'] == 270000 and money['final_bill'] == 270000
    assert money['approved_breakdown']['totals'] == {'service': 110000, 'parts': 140000,
                                                     'transport': 20000, 'other': 0}
    assert money['advance'] == 200000, 'the intake advance is tracked separately'
    assert money['balance_due'] == 70000, 'the advance is credited against the bill'
    assert PartyQuotes(service).internal_total(mobile) == 170000, 'third-party cost stays internal'
    service.post('customer', customer, 'receipt', 70000, uuid.uuid4().hex, job_id=mobile)
    assert Billing(service).summary(mobile)['balance_due'] == 0

    # --- handover and close ---------------------------------------------------
    life.execute(mobile, 'handover', dict(demonstrated=True, accepted=True, accessories_returned=True,
                                          payment_checked=True, received_by='Device owner',
                                          acknowledgment='Signed receipt'))
    life.execute(mobile, 'close')
    assert service.job(mobile)['stage'] == 'closed'

    # --- customer history and the visit projection ---------------------------
    overview = records.overview(customer)
    assert [v['number'] for v in overview['visits']] == [visit['number']]
    assert len(overview['visits'][0]['product_list']) == 3
    assert Visits(service).for_customer(customer)[0]['status'] == 'Partly completed'
    assert Visits(service).for_customer(customer)[0]['estimated_total'] == 2200000

    # --- the audit trail recorded the significant events ---------------------
    actions = {r['action'] for r in service.db.rows(
        "SELECT action FROM audit WHERE entity='job' AND entity_id=?", (mobile,))}
    assert {'received', 'party_quote_issued', 'return_verified'} <= actions

    # --- backup carries every new record, and restore validates --------------
    archive = Backups(service).create('manual', tmp_path / 'archives')
    Backups.validate(archive)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert 'shop.db' in names and 'manifest.json' in names
    assert any(n.startswith('Customers/') for n in names), 'customer evidence is in the archive'
    with pytest.raises(RuleError, match='RESTORE'):
        Backups(service).restore(archive, 'yes')
    Backups(service).restore(archive, 'RESTORE')
    assert service.db.one('SELECT estimated_total FROM visits WHERE id=?', (visit['id'],))['estimated_total'] == 2200000
    assert service.db.one('SELECT count(*) n FROM party_quotes')['n'] == 1
    assert service.db.one('SELECT count(*) n FROM return_verifications')['n'] == 1

def test_upgrading_a_real_database_corrects_stored_visit_totals(service, tmp_path, monkeypatch):
    """The production upgrade path: a v12 database with deposits stored as estimates."""
    import shutil, sqlite3
    from repairshop.customer_records import CustomerRecords
    from repairshop.persistence import Database, SCHEMA_VERSION

    customer = service.save_customer('Legacy Owner', '9990009999', **ADDRESS)
    CustomerRecords(service).save_photo(picture('#68a398'), customer)
    jobs = service.intake_visit([
        dict(customer_id=customer, device='Old Laptop', complaint='No power',
             initial_estimate=1500000, deposit=300000, advance=300000),
        dict(customer_id=customer, device='Old Mobile', complaint='No display',
             initial_estimate=500000, deposit=200000, advance=200000)], uuid.uuid4().hex)
    visit = service.db.one('SELECT visit_id FROM jobs WHERE id=?', (jobs[0],))['visit_id']

    # Recreate exactly what the shipped v12 code stored: the deposit sum as the estimate.
    with service.db.transaction() as c:
        c.execute('UPDATE visits SET estimated_total=500000 WHERE id=?', (visit,))
    service.db.engine.dispose()
    copy = tmp_path / 'legacy'
    shutil.copytree(service.db.root, copy)
    with sqlite3.connect(copy / 'shop.db') as c:
        c.execute('PRAGMA user_version=12')
        c.commit()

    upgraded = Database(copy)
    try:
        assert upgraded.one('PRAGMA user_version')['user_version'] == SCHEMA_VERSION
        row = upgraded.one('SELECT estimated_total,advance_total FROM visits WHERE id=?', (visit,))
        assert row['estimated_total'] == 2000000, 'the stored estimate is rebuilt from the jobs'
        # Deposits, advances and job records are all still exactly as they were.
        assert row['advance_total'] == 500000
        assert [r['deposit'] for r in upgraded.rows('SELECT deposit FROM jobs ORDER BY id')] == [300000, 200000]
        assert upgraded.one('SELECT count(*) n FROM jobs')['n'] == 2
        assert upgraded.one("SELECT count(*) n FROM entries WHERE kind='receipt'")['n'] == 2
        import json
        record = upgraded.one("""SELECT payload FROM audit WHERE entity='schema' AND entity_id=13
            ORDER BY id DESC LIMIT 1""")
        assert json.loads(record['payload'])['visits_corrected'] == 1, 'the correction is recorded in the audit log'
        # Re-running the upgrade changes nothing.
        upgraded.migrate()
        assert upgraded.one('SELECT estimated_total FROM visits WHERE id=?', (visit,))['estimated_total'] == 2000000
    finally:
        upgraded.engine.dispose()
