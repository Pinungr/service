"""Regression tests for the confirmed production-readiness defects.

Each test fails against the behavior that was shipped before the fix, so it pins the
corrected behavior rather than merely exercising the code path.
"""
import sqlite3
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.domain import RuleError
from repairshop.lifecycle import Lifecycle
from repairshop.persistence import SCHEMA_VERSION, statements
from repairshop.queries import Queries
from repairshop.visits import Visits

ADDRESS = dict(address_line1='12 Station Road', address_line2='Near the clock tower',
               pincode='411001', district='Pune', state='Maharashtra')


def photo(service, customer, colour='#68a398'):
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    return CustomerRecords(service).save_photo(image, customer)


def product(service, customer, device='Dell Laptop', **extra):
    return dict(customer_id=customer, device=device, complaint='Will not power on',
                guided=True, assessment_consent=True, **extra)


# ---- P0-1. visit estimated total is the repair estimate, never the deposit ----

def test_single_product_visit_estimate_is_the_initial_estimate_not_the_deposit(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', initial_estimate=1500000,
                         deposit=300000, advance=300000, operation_id=uuid.uuid4().hex)
    visit = Visits(service).for_job(job)
    assert visit['estimated_total'] == 1500000, 'estimate must come from initial_estimate'
    assert visit['advance_total'] == 300000, 'advance must still come from money received'
    assert service.job(job)['deposit'] == 300000, 'the deposit itself is untouched'


def test_multi_product_visit_totals_keep_estimate_and_advance_separate(service, customer):
    jobs = service.intake_visit([
        product(service, customer, 'Dell Laptop', initial_estimate=1500000, deposit=300000, advance=300000),
        product(service, customer, 'Samsung Mobile', initial_estimate=500000, deposit=200000, advance=200000)],
        uuid.uuid4().hex)
    visit = Visits(service).for_job(jobs[0])
    assert visit['estimated_total'] == 2000000
    assert visit['advance_total'] == 500000
    # The two figures are genuinely independent, not one derived from the other.
    assert visit['estimated_total'] != visit['advance_total']


def test_visit_estimate_ignores_a_deposit_recorded_without_any_estimate(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', deposit=750000,
                         operation_id=uuid.uuid4().hex)
    assert Visits(service).for_job(job)['estimated_total'] == 0
    assert service.job(job)['deposit'] == 750000


def test_visit_estimate_is_unaffected_by_quotation_and_final_bill(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', initial_estimate=1500000,
                         assessment_consent=True, operation_id=uuid.uuid4().hex)
    quote = service.issue_quote(job, 'Board replacement',
                                [{'description': 'Mainboard', 'amount': 2500000, 'kind': 'part'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    entry = service.invoice(quote, uuid.uuid4().hex)
    assert service.db.one('SELECT amount FROM entries WHERE id=?', (entry,))['amount'] == 2500000
    # The counter estimate stays exactly as recorded at intake.
    assert Visits(service).for_job(job)['estimated_total'] == 1500000


def test_backfilled_visit_estimates_are_recalculated_and_idempotent(service, customer):
    from repairshop.migration13 import recalculate_visit_estimates
    job = service.intake(customer, 'Dell Laptop', 'No display', initial_estimate=1500000,
                         deposit=300000, operation_id=uuid.uuid4().hex)
    visit = service.db.one('SELECT visit_id FROM jobs WHERE id=?', (job,))['visit_id']
    with service.db.transaction() as c:
        c.execute('UPDATE visits SET estimated_total=300000 WHERE id=?', (visit,))
    with service.db.transaction() as c:
        recalculate_visit_estimates(c)
        recalculate_visit_estimates(c)
    assert service.db.one('SELECT estimated_total FROM visits WHERE id=?', (visit,))['estimated_total'] == 1500000


# ---- P0-2. a technician reaches only their own assigned work ------------------

def assigned_job(service, customer, *, master=False, technician_user=None):
    """One guided job routed in-house to either a login technician or a directory one."""
    ident = service.intake(customer, 'Lifecycle laptop', 'No power', guided=True,
                           accessories=[dict(type='accessory', description='Adapter', quantity=1)])
    life = Lifecycle(service)
    life.execute(ident, 'inspect')
    life.execute(ident, 'inspection_done', {'notes': 'Power fault confirmed'})
    life.execute(ident, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'Reviewed'})
    route = {'route': 'in_house', 'confirmed': True, 'handed_over': True, 'bench': 'Bench 2',
             'condition': 'Intact', 'acknowledgment': 'Technician received'}
    if master:
        route['technician_master_id'] = service.save_master(
            'technician', 'Directory Amit', user_id=technician_user)
    else:
        route['technician_id'] = technician_user
    life.execute(ident, 'select_route', route)
    return ident


def staff(service, username, role='technician'):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def test_directory_technician_assignment_does_not_expose_the_job_to_every_technician(service, customer):
    """The loophole: a job assigned through technician_master_id skipped the owner check."""
    mine = staff(service, 'amit')
    staff(service, 'intruder')
    ident = assigned_job(service, customer, master=True, technician_user=mine)
    service.login('intruder', 'TestPassword123')
    with pytest.raises(RuleError, match='assigned'):
        service.job(ident)
    with pytest.raises(RuleError, match='assigned'):
        Lifecycle(service).snapshot(ident)
    with pytest.raises(RuleError, match='assigned'):
        Lifecycle(service).execute(ident, 'diagnose', dict(notes='Not mine', repairable=True))


def test_directory_technician_reaches_their_own_linked_job(service, customer):
    mine = staff(service, 'amit')
    ident = assigned_job(service, customer, master=True, technician_user=mine)
    service.login('amit', 'TestPassword123')
    assert service.job(ident)['id'] == ident
    Lifecycle(service).execute(ident, 'diagnose', dict(notes='Power board failed', repairable=True))


def test_login_technician_assignment_still_scopes_correctly(service, customer):
    mine = staff(service, 'amit')
    staff(service, 'intruder')
    ident = assigned_job(service, customer, technician_user=mine)
    service.login('amit', 'TestPassword123')
    assert service.job(ident)['id'] == ident
    service.login('intruder', 'TestPassword123')
    with pytest.raises(RuleError, match='assigned'):
        service.job(ident)


def test_unlinked_directory_technician_is_reachable_by_no_technician(service, customer):
    staff(service, 'intruder')
    ident = assigned_job(service, customer, master=True, technician_user=None)
    service.login('intruder', 'TestPassword123')
    with pytest.raises(RuleError, match='assigned'):
        service.job(ident)


def test_owner_and_counter_keep_full_job_access(service, customer):
    mine = staff(service, 'amit')
    staff(service, 'front', 'counter')
    ident = assigned_job(service, customer, master=True, technician_user=mine)
    assert service.job(ident)['id'] == ident
    service.login('front', 'TestPassword123')
    assert service.job(ident)['id'] == ident


def test_job_listings_only_show_a_technician_their_own_work(service, customer):
    mine = staff(service, 'amit')
    staff(service, 'intruder')
    ident = assigned_job(service, customer, master=True, technician_user=mine)
    service.login('amit', 'TestPassword123')
    assert [r['id'] for r in Queries(service).jobs()] == [ident]
    assert [r['id'] for r in Lifecycle(service).rows()] == [ident]
    service.login('intruder', 'TestPassword123')
    assert Queries(service).jobs() == []
    assert Lifecycle(service).rows() == []


def test_one_login_cannot_be_linked_to_two_directory_technicians(service):
    mine = staff(service, 'amit')
    service.save_master('technician', 'Directory Amit', user_id=mine)
    with pytest.raises(RuleError, match='already linked'):
        service.save_master('technician', 'Another Amit', user_id=mine)


def test_technician_link_requires_an_active_technician_login(service):
    counter = staff(service, 'front', 'counter')
    with pytest.raises(RuleError, match='technician login'):
        service.save_master('technician', 'Directory Amit', user_id=counter)
    with pytest.raises(RuleError, match='login account'):
        service.save_master('vendor', 'Some vendor', user_id=staff(service, 'amit'))


# ---- P0-3. every migration applies completely or not at all ------------------

def test_schema_version_is_current(service):
    assert service.db.one('PRAGMA user_version')['user_version'] == SCHEMA_VERSION


def test_statement_splitter_keeps_trigger_bodies_whole():
    script = """CREATE TABLE a(x);
CREATE TRIGGER guard BEFORE UPDATE ON a
    WHEN NEW.x IS NOT OLD.x
    BEGIN SELECT RAISE(ABORT,'no'); END;
CREATE TABLE b(y);"""
    parts = statements(script)
    assert len(parts) == 3
    assert parts[1].startswith('CREATE TRIGGER') and parts[1].endswith('END;')


def test_migration_helper_rolls_back_everything_on_failure(tmp_path):
    """`executescript` used to commit the open transaction and strand a half-migration."""
    from repairshop.persistence import migration, run_script
    path = tmp_path / 'atomic.db'
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE keep(x)')
    c.execute("INSERT INTO keep VALUES ('original')")
    c.execute('PRAGMA user_version=12')
    c.commit()
    with pytest.raises(sqlite3.OperationalError):
        with migration(c, 13):
            run_script(c, 'CREATE TABLE added(y);\nCREATE INDEX ix_added ON added(y);')
            c.execute("INSERT INTO keep VALUES ('half-done')")
            c.execute('SELECT * FROM a_table_that_does_not_exist')
    c.close()
    reopened = sqlite3.connect(path)
    assert reopened.execute('PRAGMA user_version').fetchone()[0] == 12, 'version must not advance'
    assert not reopened.execute("SELECT 1 FROM sqlite_master WHERE name='added'").fetchone()
    assert [r[0] for r in reopened.execute('SELECT x FROM keep')] == ['original']


def test_migration_helper_commits_schema_and_version_together(tmp_path):
    from repairshop.persistence import migration, run_script
    path = tmp_path / 'atomic.db'
    c = sqlite3.connect(path)
    c.execute('PRAGMA user_version=12')
    c.commit()
    with migration(c, 13):
        run_script(c, 'CREATE TABLE added(y);')
    c.close()
    reopened = sqlite3.connect(path)
    assert reopened.execute('PRAGMA user_version').fetchone()[0] == 13
    assert reopened.execute("SELECT 1 FROM sqlite_master WHERE name='added'").fetchone()


def test_failed_migration_can_simply_be_retried(tmp_path):
    """After a rollback the database is clean, so the same migration re-runs from scratch."""
    from repairshop.persistence import migration, run_script
    path = tmp_path / 'retry.db'
    c = sqlite3.connect(path)
    c.execute('PRAGMA user_version=12')
    c.commit()
    attempts = {'n': 0}

    def apply():
        with migration(c, 13):
            run_script(c, 'CREATE TABLE added(y);')
            attempts['n'] += 1
            if attempts['n'] == 1:
                raise sqlite3.OperationalError('simulated interruption')

    with pytest.raises(sqlite3.OperationalError):
        apply()
    apply()
    assert c.execute('PRAGMA user_version').fetchone()[0] == 13
    assert c.execute("SELECT 1 FROM sqlite_master WHERE name='added'").fetchone()


def test_real_migrations_11_to_13_never_leave_a_half_upgraded_database(tmp_path, monkeypatch):
    """Fail each migration mid-way and confirm the database stays entirely on the old version."""
    from repairshop import migration11, migration12, migration13
    from repairshop.persistence import Database
    for module, previous in ((migration11, 10), (migration12, 11), (migration13, 12)):
        source = Database(tmp_path / f'probe{previous}')
        source.migrate()
        path = tmp_path / f'probe{previous}' / 'shop.db'
        c = sqlite3.connect(path)
        c.execute(f'PRAGMA user_version={previous}')
        c.commit()
        before = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        monkeypatch.setattr(module, 'run_script',
                            lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError('interrupted')))
        with pytest.raises(sqlite3.OperationalError):
            module.migrate(c)
        monkeypatch.undo()
        c.close()
        reopened = sqlite3.connect(path)
        assert reopened.execute('PRAGMA user_version').fetchone()[0] == previous
        assert sorted(r[0] for r in reopened.execute("SELECT name FROM sqlite_master WHERE type='table'")) == before
        reopened.close()


# ---- P1-3. the service layer enforces the registration rules ------------------

def test_save_customer_rejects_records_the_registration_screen_would_reject(service):
    with pytest.raises(RuleError, match='full name'):
        service.save_customer('   ', '9990000010', **ADDRESS)
    with pytest.raises(RuleError, match='phone'):
        service.save_customer('No Phone', **ADDRESS)
    with pytest.raises(RuleError, match='Address Line 1'):
        service.save_customer('No Address', '9990000011')
    for field, message in (('pincode', 'PIN'), ('district', 'District'), ('state', 'State')):
        with pytest.raises(RuleError, match=message):
            service.save_customer('Partial', '9990000012', **dict(ADDRESS, **{field: ''}))
    for bad in ('41100', '4110011', 'ABC123', '41 1001'):
        with pytest.raises(RuleError, match='PIN'):
            service.save_customer('Bad PIN', '9990000013', **dict(ADDRESS, pincode=bad))
    with pytest.raises(RuleError, match='email'):
        service.save_customer('Bad Email', '9990000014', 'not-an-email', **ADDRESS)


def test_quick_counter_registration_stays_available_but_must_be_asked_for(service):
    ident = service.save_customer('Counter Walk-in', '9990000015', complete=False)
    assert service.db.one('SELECT pincode FROM customers WHERE id=?', (ident,))['pincode'] == ''
    with pytest.raises(RuleError, match='Address Line 1'):
        service.save_customer('Counter Walk-in Two', '9990000016')


def test_correcting_one_field_never_blanks_the_rest(service):
    ident = service.save_customer('Original Name', '9990000017', 'person@example.invalid',
                                  whatsapp_consent=True, email_consent=True, **ADDRESS)
    service.save_customer('Corrected Name', ident=ident)
    row = service.db.one('SELECT * FROM customers WHERE id=?', (ident,))
    assert row['name'] == 'Corrected Name'
    assert row['phone'].endswith('9990000017')
    assert row['email'] == 'person@example.invalid'
    assert row['pincode'] == '411001' and row['district'] == 'Pune'
    assert row['whatsapp_consent'] == 1 and row['email_consent'] == 1


def test_a_legacy_customer_without_an_address_can_still_be_corrected(service):
    ident = service.save_customer('Legacy Walk-in', '9990000018', complete=False)
    service.save_customer('Legacy Walk-in Renamed', ident=ident)
    assert service.db.one('SELECT name FROM customers WHERE id=?', (ident,))['name'] == 'Legacy Walk-in Renamed'
    # Supplying part of an address still has to produce a complete one.
    with pytest.raises(RuleError, match='District'):
        service.save_customer(ident=ident, address_line1='12 Station Road')


# ---- P1-4. billing permissions agree between lifecycle and service ------------

def priced_quote(service, customer, amount=500000):
    job = service.intake(customer, 'Dell Laptop', 'No display', assessment_consent=True,
                         operation_id=uuid.uuid4().hex)
    quote = service.issue_quote(job, 'Board repair',
                                [{'description': 'Mainboard', 'amount': amount, 'kind': 'part'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    return job, quote


def test_counter_can_complete_the_billing_it_is_allowed_to_start(service, customer):
    """Counter could enter billing review and then be refused at invoice generation."""
    _, quote = priced_quote(service, customer)
    service.save_staff('front', 'Front Desk', 'counter', 'TestPassword123')
    service.login('front', 'TestPassword123')
    entry = service.invoice(quote, uuid.uuid4().hex)
    assert service.db.one('SELECT amount FROM entries WHERE id=?', (entry,))['amount'] == 500000


def test_correcting_a_posted_entry_remains_an_owner_decision(service, customer):
    _, quote = priced_quote(service, customer)
    entry = service.invoice(quote, uuid.uuid4().hex)
    service.save_staff('front', 'Front Desk', 'counter', 'TestPassword123')
    service.login('front', 'TestPassword123')
    with pytest.raises(RuleError, match='role'):
        service.reverse(entry, 'Wrong amount', uuid.uuid4().hex)


def test_a_technician_can_never_perform_final_billing(service, customer):
    _, quote = priced_quote(service, customer)
    staff(service, 'amit')
    service.login('amit', 'TestPassword123')
    with pytest.raises(RuleError, match='role'):
        service.invoice(quote, uuid.uuid4().hex)


# ---- P1-5. notification status is reported honestly --------------------------

def receipt(service, job):
    from repairshop.documents import Documents
    Documents(service).visit_receipt([job])
    return service.db.one("SELECT id FROM attachments WHERE kind='issued_document' ORDER BY id DESC")['id']


def test_missing_consent_is_reported_as_blocked_not_queued(service):
    ident = service.save_customer('No Consent', '9990000019', 'quiet@example.invalid', **ADDRESS)
    photo(service, ident)
    job = service.intake(ident, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    outcomes = {r['channel']: r['state'] for r in service.queue_customer_document(
        receipt(service, job), ident, ['whatsapp', 'email'], 'intake_receipt', 'Hi', uuid.uuid4().hex, job_id=job)}
    assert outcomes == {'whatsapp': 'blocked_consent', 'email': 'blocked_consent'}
    assert {r['state'] for r in service.db.rows('SELECT state FROM outbox')} == {'blocked_consent'}


def test_a_channel_without_a_destination_is_reported_as_skipped(service):
    ident = service.save_customer('No Email', '9990000020', whatsapp_consent=True, **ADDRESS)
    photo(service, ident)
    job = service.intake(ident, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    outcomes = {r['channel']: r['state'] for r in service.queue_customer_document(
        receipt(service, job), ident, ['whatsapp', 'email'], 'intake_receipt', 'Hi', uuid.uuid4().hex, job_id=job)}
    assert outcomes == {'whatsapp': 'pending', 'email': 'no_contact'}


def test_every_delivery_state_reads_as_plain_language():
    from repairshop.messaging import status_label
    assert status_label('blocked_consent') == 'Blocked — consent missing'
    assert status_label('no_contact') == 'Skipped — no contact information'
    assert status_label('accepted') == 'Sent'
    assert status_label('pending') == 'Queued'
    assert status_label('permanent_failure') == 'Failed'
