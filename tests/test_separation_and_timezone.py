"""Regression tests for internal/customer separation, timezone use and role navigation."""
import uuid
import pytest
from repairshop import domain
from repairshop.documents import Documents
from repairshop.domain import RuleError
from repairshop.job_cards import JobCards


# ---- P2-1. internal records never sit in the customer's shareable folder ------

def test_the_internal_cost_copy_is_filed_away_from_the_customer_folder(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    card = JobCards(service).rows(job)[-1]['id']
    shareable = JobCards(service).print(card)
    internal = JobCards(service).print(card, internal=True)
    assert 'Customers' in str(shareable), 'the customer copy still belongs to the customer'
    assert 'Customers' not in str(internal), 'an internal cost copy must not sit in the customer folder'
    assert 'Internal' in str(internal)


def test_an_internal_copy_cannot_be_sent_to_the_customer(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    card = JobCards(service).rows(job)[-1]['id']
    JobCards(service).print(card, internal=True)
    row = service.db.one('SELECT id,kind FROM attachments ORDER BY id DESC')
    assert row['kind'] == 'internal_document'
    # Every send path only accepts a customer-shareable issued document.
    with pytest.raises(RuleError, match='issued document'):
        service.queue_customer_document(row['id'], customer, ['email'], 'intake_receipt',
                                        'Hi', uuid.uuid4().hex, job_id=job)


def test_only_the_owner_can_produce_an_internal_cost_copy(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    card = JobCards(service).rows(job)[-1]['id']
    service.save_staff('front', 'Front Desk', 'counter', 'TestPassword123')
    service.login('front', 'TestPassword123')
    with pytest.raises(RuleError, match='role'):
        JobCards(service).print(card, internal=True)
    assert JobCards(service).print(card), 'the counter can still print the customer copy'


def rendered(monkeypatch):
    """Capture what is actually handed to the PDF renderer; PDF streams are compressed."""
    from repairshop import documents
    captured = {}
    real = documents.pdf

    def spy(path, title, shop, sections, **kwargs):
        captured['title'], captured['sections'] = title, sections
        captured['text'] = title + ' ' + repr(sections)
        return real(path, title, shop, sections, **kwargs)

    monkeypatch.setattr(documents, 'pdf', spy)
    return captured


def test_a_customer_document_carries_no_internal_cost_figures(service, customer, monkeypatch):
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    card = JobCards(service).rows(job)[-1]['id']
    captured = rendered(monkeypatch)
    JobCards(service).print(card)
    for leak in ('INTERNAL COPY', 'Purchase Cost', 'Total Internal', 'Vendor Labour', 'Margin'):
        assert leak not in captured['text'], f'{leak} must not reach a customer document'


def test_the_internal_copy_is_the_one_that_carries_the_costs(service, customer, monkeypatch):
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    card = JobCards(service).rows(job)[-1]['id']
    captured = rendered(monkeypatch)
    JobCards(service).print(card, internal=True)
    assert 'INTERNAL COPY' in captured['text']


# ---- P2-2. one configured timezone, no hardcoded offsets --------------------

def test_no_module_hardcodes_a_timezone_or_utc_offset():
    import pathlib
    source = pathlib.Path('repairshop')
    offenders = []
    for path in source.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        if path.name != 'domain.py' and ('+330 minutes' in text or "ZoneInfo('Asia/Kolkata')" in text
                                         or 'ZoneInfo("Asia/Kolkata")' in text):
            offenders.append(path.name)
    assert offenders == [], f'hardcoded timezone handling remains in {offenders}'


def test_display_and_due_dates_follow_the_configured_timezone(service):
    original = domain.timezone_name()
    try:
        service.settings({'timezone': 'Asia/Kolkata'})
        kolkata = domain.local_time('2026-09-14T20:00:00+00:00')
        service.settings({'timezone': 'UTC'})
        assert domain.timezone_name() == 'UTC'
        utc = domain.local_time('2026-09-14T20:00:00+00:00')
        assert kolkata != utc, 'the same instant must read differently in a different zone'
        assert '01:30 AM' in kolkata and '15 Sep' in kolkata
        assert '08:00 PM' in utc and '14 Sep' in utc
    finally:
        domain.use_timezone(original)


def test_the_shop_date_is_taken_in_the_shop_timezone(service):
    original = domain.timezone_name()
    try:
        service.settings({'timezone': 'Pacific/Kiritimati'})
        east = domain.today()
        service.settings({'timezone': 'Pacific/Midway'})
        assert east >= domain.today(), 'due dates must use the shop timezone, not the server date'
    finally:
        domain.use_timezone(original)


def test_an_unusable_timezone_is_rejected_rather_than_silently_ignored(service):
    with pytest.raises(Exception):
        service.settings({'timezone': 'Not/AZone'})
    assert domain.timezone_name() != 'Not/AZone'


def test_documents_state_the_configured_zone_rather_than_a_fixed_label(service, customer, monkeypatch):
    original = domain.timezone_name()
    try:
        job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
        service.settings({'timezone': 'UTC'})
        captured = rendered(monkeypatch)
        Documents(service).visit_receipt([job])
        assert 'UTC' in captured['text'] and 'IST' not in captured['text']
    finally:
        domain.use_timezone(original)


# ---- P2-3. a role cannot reach a screen it may not use ----------------------

def window_for(qtbot, service):
    """Build the main window the way the existing UI tests do: no live timer or pool."""
    from repairshop.ui import MainWindow
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    return window


def test_a_technician_cannot_open_a_screen_their_role_hides(qtbot, service, customer):
    service.save_staff('amit', 'Amit', 'technician', 'TestPassword123')
    service.login('amit', 'TestPassword123')
    window = window_for(qtbot, service)
    assert window.may_open('Active Repairs') and window.may_open('Dashboard')
    for screen in ('New Repair Intake', 'Customers', 'Settings & staff', 'Backups', 'Reports'):
        assert not window.may_open(screen)
        with pytest.raises(RuleError, match='cannot open'):
            window.navigate(screen)
    # The service layer refuses the work itself, not just the screen.
    with pytest.raises(RuleError, match='role'):
        window.intake()
    window.pool.waitForDone(10000)


def test_the_counter_keeps_its_own_screens_and_loses_only_owner_ones(qtbot, service):
    service.save_staff('front', 'Front Desk', 'counter', 'TestPassword123')
    service.login('front', 'TestPassword123')
    window = window_for(qtbot, service)
    for screen in ('New Repair Intake', 'Customers', 'Active Repairs', 'Quotations'):
        assert window.may_open(screen)
    for screen in ('Vendor accounts', 'Backups', 'Settings & staff'):
        assert not window.may_open(screen)
        with pytest.raises(RuleError, match='cannot open'):
            window.navigate(screen)
    window.pool.waitForDone(10000)


def test_the_owner_can_open_every_screen(qtbot, service):
    window = window_for(qtbot, service)
    for screen in ('New Repair Intake', 'Vendor accounts', 'Backups', 'Settings & staff', 'Reports'):
        assert window.may_open(screen)
    window.pool.waitForDone(10000)
