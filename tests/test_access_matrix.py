"""Security matrix: knowing another repair's id must never be enough to read it.

Two technicians each own a repair. Every job-specific read is attempted as the owning
technician, as the other technician, and as an admin. Anything that answers for the wrong
technician is an information-disclosure bug, so each endpoint is listed explicitly rather
than tested through whatever path the UI happens to use.
"""
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.billing import Billing
from repairshop.costing import JobCosts
from repairshop.customer_records import CustomerRecords
from repairshop.dispatch import Dispatches
from repairshop.domain import RuleError
from repairshop.job_cards import JobCards
from repairshop.lifecycle import Lifecycle
from repairshop.parts import Parts
from repairshop.party_quotes import PartyQuotes
from repairshop.queries import Queries
from repairshop.returns import Returns
from repairshop.visits import Visits

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')


def staff(service, username, role):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def customer_of(service, name, phone):
    ident = service.save_customer(name, phone, **ADDRESS)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    return ident


def assigned_job(service, customer, technician, device='Dell Laptop'):
    """A guided repair assigned to, and physically held by, one technician."""
    job = service.intake(customer, device, 'No power', guided=True,
                         accessories=[dict(type='accessory', description='Charger', quantity=1)])
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Power fault'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'None'})
    life.execute(job, 'select_route', {'route': 'in_house', 'confirmed': True,
                                       'technician_id': technician, 'handed_over': True,
                                       'bench': 'Bench 1', 'condition': 'Intact',
                                       'acknowledgment': 'Technician signed'})
    return job


#: Every job-specific read the brief lists. Each takes the service and a job id.
READS = {
    'Service.job': lambda s, j: s.job(j),
    'Queries.history': lambda s, j: Queries(s).history(j),
    'Lifecycle.timeline': lambda s, j: Lifecycle(s).timeline(j),
    'Lifecycle.holdings': lambda s, j: Lifecycle(s).holdings(j),
    'Lifecycle.snapshot': lambda s, j: Lifecycle(s).snapshot(j),
    'Visits.for_job': lambda s, j: Visits(s).for_job(j),
    'JobCards.rows': lambda s, j: JobCards(s).rows(j),
    'Parts.rows': lambda s, j: Parts(s).rows(j),
    'Dispatches.current': lambda s, j: Dispatches(s).current(j),
    'Dispatches.history': lambda s, j: Dispatches(s).history(j),
    'PartyQuotes.current': lambda s, j: PartyQuotes(s).current(j),
    'PartyQuotes.history': lambda s, j: PartyQuotes(s).history(j),
    'Returns.expected': lambda s, j: Returns(s).expected(j),
    'Returns.verifications': lambda s, j: Returns(s).verifications(j),
    'Returns.open_discrepancies': lambda s, j: Returns(s).open_discrepancies(j),
}


@pytest.fixture
def matrix(service):
    """Admin, two technicians, and one repair belonging to each technician."""
    amit = staff(service, 'amit', 'technician')
    ravi = staff(service, 'ravi', 'technician')
    staff(service, 'sneha', 'counter')
    one = customer_of(service, 'Owner One', '9990008001')
    two = customer_of(service, 'Owner Two', '9990008002')
    job_a = assigned_job(service, one, amit)
    job_b = assigned_job(service, two, ravi, 'Samsung Mobile')
    return dict(amit=amit, ravi=ravi, job_a=job_a, job_b=job_b)


@pytest.mark.parametrize('name', sorted(READS))
def test_the_owning_technician_may_read_their_own_repair(service, matrix, name):
    service.login('amit', 'TestPassword123')
    READS[name](service, matrix['job_a'])


@pytest.mark.parametrize('name', sorted(READS))
def test_another_technician_is_denied_even_knowing_the_job_id(service, matrix, name):
    service.login('ravi', 'TestPassword123')
    with pytest.raises(RuleError, match='not assigned to you'):
        READS[name](service, matrix['job_a'])


@pytest.mark.parametrize('name', sorted(READS))
def test_the_owner_may_read_any_repair(service, matrix, name):
    READS[name](service, matrix['job_a'])


@pytest.mark.parametrize('name', sorted(READS))
def test_counter_staff_may_read_any_repair(service, matrix, name):
    service.login('sneha', 'TestPassword123')
    READS[name](service, matrix['job_a'])


def test_money_and_cost_views_are_denied_to_the_wrong_technician(service, matrix):
    service.login('ravi', 'TestPassword123')
    for view in (lambda: Billing(service).summary(matrix['job_a']),
                 lambda: JobCosts(service).summary(matrix['job_a'])):
        with pytest.raises(RuleError):
            view()


def test_internal_cost_stays_with_the_owner_even_for_their_own_repair(service, matrix):
    """A technician performing the repair still has no window onto shop margins."""
    service.login('amit', 'TestPassword123')
    with pytest.raises(RuleError, match='view internal cost'):
        JobCosts(service).summary(matrix['job_a'])
    with pytest.raises(RuleError, match='billing'):
        Billing(service).summary(matrix['job_a'])


def test_a_technician_cannot_act_on_another_technicians_repair(service, matrix):
    service.login('ravi', 'TestPassword123')
    with pytest.raises(RuleError, match='not assigned to you'):
        Lifecycle(service).execute(matrix['job_a'], 'diagnose',
                                   dict(notes='Not mine', repairable=True))


def test_job_listings_never_include_another_technicians_repair(service, matrix):
    service.login('ravi', 'TestPassword123')
    assert [r['id'] for r in Queries(service).jobs()] == [matrix['job_b']]
    assert [r['id'] for r in Lifecycle(service).rows()] == [matrix['job_b']]
    service.login('amit', 'TestPassword123')
    assert [r['id'] for r in Queries(service).jobs()] == [matrix['job_a']]


# ---- 10. a shared visit must not widen access -------------------------------

def test_a_shared_visit_does_not_expose_another_technicians_product(service):
    amit = staff(service, 'amit', 'technician')
    ravi = staff(service, 'ravi', 'technician')
    staff(service, 'sneha', 'counter')
    customer = customer_of(service, 'Multi Owner', '9990008003')

    def product(device):
        return dict(customer_id=customer, device=device, complaint='Fault', guided=True)

    laptop, printer = service.intake_visit([product('Dell Laptop'), product('HP Printer')],
                                           uuid.uuid4().hex)
    life = Lifecycle(service)
    for job, technician in ((laptop, amit), (printer, ravi)):
        life.execute(job, 'inspect')
        life.execute(job, 'inspection_done', {'notes': 'Checked'})
        life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'None'})
        life.execute(job, 'select_route', {'route': 'in_house', 'confirmed': True,
                                           'technician_id': technician, 'handed_over': True,
                                           'bench': 'Bench', 'condition': 'Intact',
                                           'acknowledgment': 'Signed'})
    visit = service.db.one('SELECT visit_id FROM jobs WHERE id=?', (laptop,))['visit_id']

    service.login('amit', 'TestPassword123')
    detail = Visits(service).detail(visit)
    assert [r['id'] for r in detail['jobs']] == [laptop], 'only his own product is listed'
    assert detail['products'] == 1, 'and the count reflects that'
    with pytest.raises(RuleError, match='not assigned to you'):
        service.job(printer)

    service.login('ravi', 'TestPassword123')
    assert [r['id'] for r in Visits(service).detail(visit)['jobs']] == [printer]

    service.login('sneha', 'TestPassword123')
    assert sorted(r['id'] for r in Visits(service).detail(visit)['jobs']) == sorted([laptop, printer])
    assert Visits(service).detail(visit)['products'] == 2


def test_a_visit_with_nothing_of_yours_is_not_readable(service):
    ravi = staff(service, 'ravi', 'technician')
    amit = staff(service, 'amit', 'technician')
    customer = customer_of(service, 'Single Owner', '9990008004')
    job = assigned_job(service, customer, amit)
    visit = service.db.one('SELECT visit_id FROM jobs WHERE id=?', (job,))['visit_id']
    service.login('ravi', 'TestPassword123')
    # The visit is filtered out entirely, so it reads as absent rather than forbidden:
    # a technician is not told that someone else's visit exists.
    with pytest.raises(RuleError, match='not found|assigned to you'):
        Visits(service).detail(visit)
    assert Visits(service).for_customer(customer) == [], 'and it is not listed either'
    assert Visits(service).search() == []
