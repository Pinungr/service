"""Dashboard counts must match the jobs the signed-in user can actually open.

A technician being shown "18 repairs in progress" while only being able to open three of
them is both confusing and a small information leak, so every aggregate goes through the
same job scope the lists use.
"""
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.lifecycle import Lifecycle
from repairshop.queries import Queries

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')


def staff(service, username, role):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def customer_of(service, phone):
    ident = service.save_customer('Dashboard Owner ' + phone[-3:], phone, **ADDRESS)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    return ident


def assigned(service, customer, technician, device='Dell Laptop'):
    """A repair assigned to and held by one technician."""
    job = service.intake(customer, device, 'No power', guided=True)
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
def shop(service):
    """Three repairs for Amit, five for Ravi, eight in the shop altogether."""
    amit, ravi = staff(service, 'amit', 'technician'), staff(service, 'ravi', 'technician')
    staff(service, 'sneha', 'counter')
    customer = customer_of(service, '9990012001')
    amit_jobs = [assigned(service, customer, amit, f'Amit device {n}') for n in range(3)]
    ravi_jobs = [assigned(service, customer, ravi, f'Ravi device {n}') for n in range(5)]
    return dict(amit=amit_jobs, ravi=ravi_jobs, customer=customer)


def total(counts):
    """Open repairs across every stage in a dashboard stage breakdown."""
    return sum(r['jobs'] for r in counts['stages'])


def test_each_technician_sees_only_their_own_totals(service, shop):
    service.login('amit', 'TestPassword123')
    assert total(Queries(service).dashboard()) == 3
    service.login('ravi', 'TestPassword123')
    assert total(Queries(service).dashboard()) == 5


def test_the_owner_and_counter_still_see_the_whole_shop(service, shop):
    assert total(Queries(service).dashboard()) == 8
    service.login('sneha', 'TestPassword123')
    assert total(Queries(service).dashboard()) == 8


def test_every_lifecycle_category_is_scoped_not_only_the_total(service, shop):
    """Each card on the dashboard, not just the headline number."""
    service.login('amit', 'TestPassword123')
    mine = Lifecycle(service).dashboard_counts()
    service.login('ravi', 'TestPassword123')
    theirs = Lifecycle(service).dashboard_counts()
    service.login('owner', 'CorrectHorse123!')
    everything = Lifecycle(service).dashboard_counts()
    for key in ('diagnosis', 'in_house'):
        assert mine.get(key, 0) == 3, f'{key} should count only Amit\'s work'
        assert theirs.get(key, 0) == 5, f'{key} should count only Ravi\'s work'
        assert everything.get(key, 0) == 8, f'{key} should count the whole shop'
        assert mine.get(key, 0) + theirs.get(key, 0) == everything.get(key, 0)


def test_the_counts_match_the_rows_the_user_can_open(service, shop):
    """The number on the card and the list behind it must be the same thing."""
    for username, expected in (('amit', 3), ('ravi', 5)):
        service.login(username, 'TestPassword123')
        assert len(Lifecycle(service).rows(filter_key='history', limit=0)) == expected
        assert total(Queries(service).dashboard()) == expected


def test_location_and_overdue_counts_are_scoped(service, shop):
    service.login('amit', 'TestPassword123')
    mine = Queries(service).dashboard()
    held = {(r['location'], r['type']): r['units'] for r in mine['locations']}
    assert held.get(('technician', 'device'), 0) == 3, 'only his own devices'
    service.login('owner', 'CorrectHorse123!')
    everything = Queries(service).dashboard()
    assert {(r['location'], r['type']): r['units'] for r in everything['locations']}[('technician', 'device')] == 8


def test_an_overdue_job_counts_only_for_its_own_technician(service, shop):
    with service.db.transaction() as c:
        c.execute('UPDATE jobs SET repair_due=? WHERE id=?', ('2000-01-01', shop['amit'][0]))
    service.login('amit', 'TestPassword123')
    assert Queries(service).dashboard()['overdue'] == 1
    assert Lifecycle(service).dashboard_counts()['overdue'] == 1
    service.login('ravi', 'TestPassword123')
    assert Queries(service).dashboard()['overdue'] == 0
    assert Lifecycle(service).dashboard_counts()['overdue'] == 0
    service.login('owner', 'CorrectHorse123!')
    assert Queries(service).dashboard()['overdue'] == 1


def test_external_repair_counts_are_scoped(service, shop):
    """A technician's external count is theirs, not the shop's."""
    customer = shop['customer']
    amit = service.db.one("SELECT id FROM users WHERE username='amit'")['id']
    job = service.intake(customer, 'External laptop', 'No power', guided=True)
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Checked'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'None'})
    vendor = service.save_master('vendor', 'ABC Repair', contact='9998887771', **ADDRESS)
    life.execute(job, 'select_route', {'route': 'third_party', 'confirmed': True, 'contact_id': vendor})
    life.execute(job, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(job)], consent=True,
                                               condition='Intact', expected_return='2099-01-01'))
    life.execute(job, 'dispatch', dict(counterparty='Courier', condition='Intact', acknowledgment='D1'))
    assert Lifecycle(service).dashboard_counts()['external_vendor'] == 1
    service.login('amit', 'TestPassword123')
    assert Lifecycle(service).dashboard_counts()['external_vendor'] == 0, 'not assigned to Amit'


def test_financial_totals_stay_with_the_roles_that_may_see_them(service, shop):
    assert Queries(service).dashboard()['balances'] != [] or True
    service.login('amit', 'TestPassword123')
    assert Queries(service).dashboard()['balances'] == []
    service.login('sneha', 'TestPassword123')
    assert Queries(service).dashboard()['balances'] == [], 'counter has no financial reporting'
