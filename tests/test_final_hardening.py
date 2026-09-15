"""Final hardening: cross-job writes, customer privacy and notification settings.

Each test targets one confirmed defect from the end-to-end review and checks the real
result — the database row, the file on disk, the outbox state — rather than only the
return value of the call.
"""
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.documents import Documents
from repairshop.domain import RuleError
from repairshop.lifecycle import Lifecycle
from repairshop.queries import Queries

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')

#: Sentinels distinctive enough to grep for anywhere in the customer package.
SHOP_COST = 4200000          # SHOP_COST_SECRET
SALE_PRICE = 5000000
SUPPLIER = 'SUPPLIERSECRETXYZ Distribution'
PRIVATE_NOTE = 'PRIVATETECHNOTESECRET internal remark'


def staff(service, username, role):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def photo(service, customer, colour='#68a398'):
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    return CustomerRecords(service).save_photo(image, customer)


def customer_of(service, name, phone, **extra):
    ident = service.save_customer(name, phone, **dict(ADDRESS, **extra))
    photo(service, ident)
    return ident


def assigned_job(service, customer, technician, device='Dell Laptop'):
    job = service.intake(customer, device, 'No power', guided=True,
                         accessories=[dict(type='accessory', description='Charger', quantity=1)])
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Checked'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'None'})
    life.execute(job, 'select_route', {'route': 'in_house', 'confirmed': True,
                                       'technician_id': technician, 'handed_over': True,
                                       'bench': 'Bench', 'condition': 'Intact',
                                       'acknowledgment': 'Signed'})
    return job


@pytest.fixture
def two_jobs(service, tmp_path):
    """JOB-A belongs to Amit, JOB-B to Ravi."""
    amit, ravi = staff(service, 'amit', 'technician'), staff(service, 'ravi', 'technician')
    staff(service, 'sneha', 'counter')
    one = customer_of(service, 'Owner One', '9990014001')
    two = customer_of(service, 'Owner Two', '9990014002')
    evidence = tmp_path / 'evidence.pdf'
    evidence.write_bytes(b'%PDF-1.4 evidence')
    return dict(a=assigned_job(service, one, amit), b=assigned_job(service, two, ravi),
                one=one, two=two, evidence=evidence, amit=amit, ravi=ravi)


# ---- 3 / 35. no cross-job attachment writes ---------------------------------

def test_another_technician_cannot_attach_a_file_to_your_repair(service, two_jobs):
    before_rows = service.db.one('SELECT count(*) n FROM attachments')['n']
    before_files = len(list((service.db.root / 'Customers').rglob('*')))
    service.login('ravi', 'TestPassword123')
    with pytest.raises(RuleError, match='not assigned to you'):
        Documents(service).attach(two_jobs['evidence'], 'Sneaky evidence', job_id=two_jobs['a'])
    service.login('owner', 'CorrectHorse123!')
    assert service.db.one('SELECT count(*) n FROM attachments')['n'] == before_rows, 'no row was created'
    assert len(list((service.db.root / 'Customers').rglob('*'))) == before_files, 'no file was written'


def test_another_technician_cannot_attach_a_photo_to_your_repair(service, two_jobs):
    before = service.db.one('SELECT count(*) n FROM attachments')['n']
    service.login('ravi', 'TestPassword123')
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#aa3333'))
    with pytest.raises(RuleError, match='not assigned to you'):
        CustomerRecords(service).save_photo(image, two_jobs['one'], 'return', 'Damage',
                                            job_id=two_jobs['a'])
    service.login('owner', 'CorrectHorse123!')
    assert service.db.one('SELECT count(*) n FROM attachments')['n'] == before


def test_the_owning_technician_may_still_attach_to_their_own_repair(service, two_jobs):
    service.login('amit', 'TestPassword123')
    assert Documents(service).attach(two_jobs['evidence'], 'My evidence', job_id=two_jobs['a'])
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#33aa33'))
    assert CustomerRecords(service).save_photo(image, two_jobs['one'], 'return', 'Damage',
                                               job_id=two_jobs['a'])


def test_another_technician_cannot_recover_your_evidence_file(service, two_jobs):
    service.login('amit', 'TestPassword123')
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#33aa33'))
    attachment = CustomerRecords(service).save_photo(image, two_jobs['one'], 'return', 'Damage',
                                                     job_id=two_jobs['a'])
    service.login('ravi', 'TestPassword123')
    with pytest.raises(RuleError, match='not assigned to you'):
        CustomerRecords(service).recover_photo(attachment, two_jobs['evidence'])


# ---- 4 / 5. customer overview is scoped and money-aware ---------------------

def test_a_shared_customer_does_not_expose_another_technicians_repair(service):
    amit, ravi = staff(service, 'amit', 'technician'), staff(service, 'ravi', 'technician')
    shared = customer_of(service, 'Shared Owner', '9990014003')
    mine = assigned_job(service, shared, amit, 'Amit laptop')
    theirs = assigned_job(service, shared, ravi, 'Ravi printer')
    service.login('amit', 'TestPassword123')
    overview = CustomerRecords(service).overview(shared)
    seen = {j['id'] for j in overview['outstanding'] + overview['history']}
    assert seen == {mine}, 'only his own repair'
    assert theirs not in seen
    service.login('owner', 'CorrectHorse123!')
    everything = CustomerRecords(service).overview(shared)
    assert {j['id'] for j in everything['outstanding'] + everything['history']} == {mine, theirs}


def test_a_technician_sees_no_customer_balances(service, two_jobs):
    service.login('amit', 'TestPassword123')
    overview = CustomerRecords(service).overview(two_jobs['one'])
    assert all(j['balance'] is None for j in overview['outstanding'] + overview['history'])
    service.login('sneha', 'TestPassword123')
    counter = CustomerRecords(service).overview(two_jobs['one'])
    assert all(j['balance'] is not None for j in counter['outstanding'] + counter['history'])


# ---- 7 / 36. sale cost and supplier stay internal ---------------------------

@pytest.fixture
def sold(service):
    customer = customer_of(service, 'Buyer', '9990014004')
    service.save_sale(customer, 'Sold Laptop', amount=SALE_PRICE, cost=SHOP_COST,
                      provider=SUPPLIER, serial='SN-1')
    return customer


def test_a_technician_cannot_open_products_sold_at_all(service, sold):
    staff(service, 'amit', 'technician')
    service.login('amit', 'TestPassword123')
    with pytest.raises(RuleError, match='register sale'):
        Queries(service).sales()


def test_the_counter_sees_the_sale_price_but_not_the_shop_cost(service, sold):
    staff(service, 'sneha', 'counter')
    service.login('sneha', 'TestPassword123')
    rows = Queries(service).sales()
    assert rows and rows[0]['amount'] == SALE_PRICE
    assert 'cost' not in rows[0] and 'provider' not in rows[0]
    with pytest.raises(RuleError, match='internal cost'):
        service.save_sale(sold, 'Another', amount=100, cost=50)


def test_the_owner_sees_the_whole_sale_record(service, sold):
    rows = Queries(service).sales()
    assert rows[0]['cost'] == SHOP_COST and rows[0]['provider'] == SUPPLIER


# ---- 8. dispatch and receive lists are scoped -------------------------------

def test_the_custody_list_shows_only_your_own_products(service, two_jobs):
    service.login('amit', 'TestPassword123')
    assert {r['job_id'] for r in Queries(service).holdings()} == {two_jobs['a']}
    service.login('ravi', 'TestPassword123')
    assert {r['job_id'] for r in Queries(service).holdings()} == {two_jobs['b']}
    service.login('sneha', 'TestPassword123')
    assert {r['job_id'] for r in Queries(service).holdings()} == {two_jobs['a'], two_jobs['b']}


def test_the_movable_item_list_is_scoped_too(service, two_jobs):
    service.login('ravi', 'TestPassword123')
    assert {r['job_id'] for r in Queries(service).holdings(movable=True)} == {two_jobs['b']}
    with pytest.raises(RuleError, match='not assigned to you'):
        Queries(service).holdings(job_id=two_jobs['a'])


# ---- 13. the customer package carries no internal values --------------------

def test_no_sale_cost_or_supplier_reaches_the_customer_folder(service, sold):
    job = service.intake(sold, 'Sold Laptop', 'No power', operation_id=uuid.uuid4().hex)
    service.record_work(job, 'diagnosis', {'notes': PRIVATE_NOTE})
    CustomerRecords(service).sync_customer(sold)
    body = '\n'.join(p.read_text(encoding='utf-8', errors='replace')
                     for p in (service.db.root / 'Customers').rglob('*.txt'))
    assert body
    for secret in (str(SHOP_COST), '42,000.00', SUPPLIER, PRIVATE_NOTE):
        assert secret not in body, f'{secret!r} leaked into the customer folder'
    internal = '\n'.join(p.read_text(encoding='utf-8', errors='replace')
                         for p in (service.db.root / 'Internal').rglob('*.txt'))
    assert SUPPLIER in internal and PRIVATE_NOTE in internal, 'the shop keeps its own record'


def test_the_customer_product_file_keeps_what_the_customer_needs(service, sold):
    service.intake(sold, 'Sold Laptop', 'No power', operation_id=uuid.uuid4().hex)
    CustomerRecords(service).sync_customer(sold)
    product = next((service.db.root / 'Customers').rglob('product-details.txt'))
    body = product.read_text(encoding='utf-8')
    assert 'Sold Laptop' in body
    assert str(SHOP_COST) not in body and SUPPLIER not in body


# ---- 14 / 15 / 16. the global channel switch is authoritative ---------------

def queued(service, channel):
    return service.db.rows('SELECT state FROM outbox WHERE channel=?', (channel,))


def test_turning_a_channel_off_stops_every_queue_path(service):
    """Both the generic lifecycle notifier and the document sender obey the switch."""
    customer = customer_of(service, 'Silent Owner', '9990014005', whatsapp_consent=True,
                           email_consent=True)
    service.settings({'whatsapp_enabled': False, 'email_enabled': False})
    service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    assert queued(service, 'whatsapp') == [] and queued(service, 'email') == []
    service.settings({'whatsapp_enabled': True})
    service.intake(customer, 'Second Laptop', 'No power', operation_id=uuid.uuid4().hex)
    assert queued(service, 'whatsapp') != [], 'WhatsApp queues again once switched on'
    assert queued(service, 'email') == [], 'email is still off'


def test_a_disabled_channel_reports_itself_rather_than_pretending(service):
    customer = customer_of(service, 'Reported Owner', '9990014006', whatsapp_consent=True)
    service.settings({'whatsapp_enabled': False, 'auto_whatsapp_intake_receipt': True})
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    Documents(service).visit_receipt([job])
    attachment = service.db.one("SELECT id FROM attachments WHERE kind='issued_document' ORDER BY id DESC")['id']
    outcomes = {r['channel']: r['state'] for r in service.queue_customer_document(
        attachment, customer, ['whatsapp'], 'intake_receipt', 'Hi', uuid.uuid4().hex, job_id=job)}
    assert outcomes == {'whatsapp': 'channel_disabled'}


def test_a_message_queued_before_the_switch_is_held_not_sent(service):
    """Queued at 10:00, WhatsApp switched off at 10:05, worker runs at 10:10."""
    from repairshop.messaging import Outbox, status_label
    customer = customer_of(service, 'Held Owner', '9990014007', whatsapp_consent=True)
    service.settings({'whatsapp_enabled': True})
    service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    assert {r['state'] for r in queued(service, 'whatsapp')} == {'pending'}
    service.settings({'whatsapp_enabled': False})
    sent = []

    class Recorder:
        def send(self, row, payload):
            sent.append(row['id'])
            return 'PROVIDER-1'

    worker = Outbox(service)
    worker.adapters = {'whatsapp': Recorder(), 'email': Recorder()}
    while worker.process_one():
        pass
    assert sent == [], 'nothing was sent on a switched-off channel'
    states = {r['state'] for r in queued(service, 'whatsapp')}
    assert states == {'channel_disabled'}, 'held with a clear reason, not lost'
    assert status_label('channel_disabled') == 'Held — channel switched off in Settings'


# ---- 19. no setting can bypass consent --------------------------------------

def test_consent_is_not_a_setting_anyone_can_switch_off(service):
    from repairshop import app_settings
    assert not [k for k in app_settings.KEYS if 'consent' in k]
    with pytest.raises(RuleError, match='Unsupported setting'):
        service.settings({'require_whatsapp_consent': False})


def test_a_fully_enabled_shop_still_cannot_message_without_consent(service):
    customer = customer_of(service, 'No Consent', '9990014008', email='quiet@example.invalid',
                           whatsapp_consent=False, email_consent=False)
    service.settings({'whatsapp_enabled': True, 'email_enabled': True,
                      'auto_whatsapp_invoice': True, 'auto_email_invoice': True})
    service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    assert {r['state'] for r in queued(service, 'whatsapp')} == {'blocked_consent'}
    assert {r['state'] for r in queued(service, 'email')} == {'blocked_consent'}


# ---- 17 / 18. real events notify once ---------------------------------------

def test_a_quotation_notifies_the_customer_once(service):
    customer = customer_of(service, 'Quoted Owner', '9990014009', whatsapp_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_quotation': True})
    job = service.intake(customer, 'Dell Laptop', 'No power', assessment_consent=True,
                         operation_id=uuid.uuid4().hex)
    quote = service.issue_quote(job, 'Board repair',
                                [{'description': 'Board', 'amount': 500000, 'kind': 'part'}])
    rows = service.db.rows("SELECT * FROM outbox WHERE event='quotation'")
    assert len(rows) == 1 and rows[0]['state'] == 'pending'
    assert rows[0]['attachment_id'], 'the quotation PDF travels with it'
    # Re-announcing the same quotation must not queue it twice.
    service.announce('quotation', job, quote, 'again', 'quotation', source_id=quote)
    assert len(service.db.rows("SELECT * FROM outbox WHERE event='quotation'")) == 1


def test_an_invoice_notifies_the_customer_once(service):
    customer = customer_of(service, 'Billed Owner', '9990014010', whatsapp_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_invoice': True})
    job = service.intake(customer, 'Dell Laptop', 'No power', assessment_consent=True,
                         operation_id=uuid.uuid4().hex)
    quote = service.issue_quote(job, 'Board repair',
                                [{'description': 'Board', 'amount': 500000, 'kind': 'part'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    operation = uuid.uuid4().hex
    service.invoice(quote, operation)
    service.invoice(quote, operation)  # a retried workflow
    assert len(service.db.rows("SELECT * FROM outbox WHERE event='invoice'")) == 1


def test_nothing_is_announced_when_the_event_is_not_configured(service):
    customer = customer_of(service, 'Quiet Owner', '9990014011', whatsapp_consent=True)
    job = service.intake(customer, 'Dell Laptop', 'No power', assessment_consent=True,
                         operation_id=uuid.uuid4().hex)
    service.issue_quote(job, 'Board repair',
                        [{'description': 'Board', 'amount': 500000, 'kind': 'part'}])
    assert service.db.rows("SELECT * FROM outbox WHERE event='quotation'") == []


def test_a_messaging_failure_never_undoes_the_business_record(service, monkeypatch):
    """The quotation is saved even if its notification cannot be produced."""
    from repairshop import documents
    customer = customer_of(service, 'Resilient Owner', '9990014012', whatsapp_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_quotation': True})
    job = service.intake(customer, 'Dell Laptop', 'No power', assessment_consent=True,
                         operation_id=uuid.uuid4().hex)
    monkeypatch.setattr(documents.Documents, 'generate',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('printer exploded')))
    quote = service.issue_quote(job, 'Board repair',
                                [{'description': 'Board', 'amount': 500000, 'kind': 'part'}])
    monkeypatch.undo()
    assert service.db.one('SELECT id FROM quotes WHERE id=?', (quote,)), 'the quotation is saved'
    assert service.db.one("""SELECT 1 n FROM audit WHERE action='auto_notify_failed'
        AND entity_id=?""", (job,)), 'and the failure is recorded, not swallowed'


# ---- 20 / 21. the estimate requirement --------------------------------------

def test_the_estimate_requirement_refuses_a_blank_but_accepts_an_explicit_zero(service):
    """Documented rule: blank means "not asked"; 0 means "free of charge"."""
    customer = customer_of(service, 'Estimate Owner', '9990014013')
    service.settings({'require_initial_estimate': True})
    with pytest.raises(RuleError, match='requires an initial estimate'):
        service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    free = service.intake(customer, 'Free Laptop', 'No power', initial_estimate=0,
                          operation_id=uuid.uuid4().hex)
    priced = service.intake(customer, 'Priced Laptop', 'No power', initial_estimate=50000,
                            operation_id=uuid.uuid4().hex)
    assert service.job(free)['initial_estimate'] == 0
    assert service.job(priced)['initial_estimate'] == 50000


def test_each_product_in_a_visit_is_validated_independently(service):
    customer = customer_of(service, 'Visit Owner', '9990014014')
    service.settings({'require_initial_estimate': True})

    def product(device, **extra):
        return dict(customer_id=customer, device=device, complaint='Fault', **extra)

    with pytest.raises(RuleError, match='requires an initial estimate'):
        service.intake_visit([product('One', initial_estimate=50000), product('Two')],
                             uuid.uuid4().hex)
    assert service.db.rows('SELECT id FROM jobs') == [], 'the whole visit rolled back'


def test_the_requirement_is_off_by_default(service):
    customer = customer_of(service, 'Default Owner', '9990014015')
    assert service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)


# ---- 32. India business dates -----------------------------------------------

def test_collection_reminders_use_the_india_business_date(service, monkeypatch):
    """Before 05:30 IST the UTC date is still yesterday, which would make an overdue
    collection look not-yet-due. The reminder uses the shop's own date."""
    import repairshop.messaging as messaging
    customer = customer_of(service, 'Reminder Owner', '9990014016', whatsapp_consent=True)
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    service.stage(job, 'ready_repaired', reason='Ready', test_result='passed')
    with service.db.transaction() as c:
        c.execute('UPDATE jobs SET collection_due=? WHERE id=?', ('2000-01-01', job))
    service.settings({'reminder_days': 1})
    # Pin the shop date; the reminder key records the business day it used.
    monkeypatch.setattr(messaging, 'today', lambda: '2026-03-05')
    messaging.Outbox(service).schedule_reminders()
    keys = [r['event_key'] for r in service.db.rows(
        "SELECT event_key FROM outbox WHERE event='collection_reminder'")]
    assert keys and all(k.endswith('2026-03-05') for k in keys), \
        'the reminder is dated by the shop day, not by UTC'


def test_no_module_computes_a_business_date_from_utc():
    import pathlib
    import re
    offenders = []
    for path in pathlib.Path('repairshop').glob('*.py'):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if re.search(r'datetime\.now\(timezone\.utc\)\.date\(\)', line):
                offenders.append(f'{path.name}:{number}')
    assert offenders == [], f'UTC used for a business date in {offenders}'
