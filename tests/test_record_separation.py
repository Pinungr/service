"""Everything under Customers/ must be safe to hand to the customer.

The check is deliberately blunt: put known internal numbers and notes into a repair, then
scan the whole customer-shareable tree for them. Anything that leaks fails, whichever file
it leaked through.
"""
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.domain import RuleError
from repairshop.inventory import Inventory
from repairshop.lifecycle import Lifecycle
from repairshop.parts import Parts
from repairshop.party_quotes import PartyQuotes

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')

#: Values a customer must never see, each distinctive enough to grep for.
PURCHASE_COST = 80000        # what the shop paid for the part
CUSTOMER_PRICE = 220000      # what the customer is charged for it
VENDOR_LABOUR = 150000       # the third party's own labour charge
PRIVATE_NOTE = 'ZZINTERNALNOTE private technician remark about this customer'


def customer_of(service):
    ident = service.save_customer('Separation Owner', '9990010001', **ADDRESS)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    return ident


@pytest.fixture
def loaded(service):
    """A repair carrying every kind of internal value we care about."""
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True, initial_estimate=300000,
                         accessories=[dict(type='accessory', description='Charger', quantity=1,
                                           condition='Working')])
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Power rail fault'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'None'})
    vendor = service.save_master('vendor', 'ABC Board Repair', contact='9998887771', **ADDRESS)
    life.execute(job, 'select_route', {'route': 'third_party', 'confirmed': True, 'contact_id': vendor})
    life.execute(job, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(job)], consent=True,
                                               condition='Intact', expected_return='2099-01-01'))
    life.execute(job, 'dispatch', dict(counterparty='Courier', condition='Intact', acknowledgment='D1'))
    life.execute(job, 'diagnose', dict(notes='Board fault', repairable=True))

    # A stock part with a real purchase cost and margin.
    inventory = Inventory(service)
    stock = inventory.save(dict(name='Power board', purchase_cost=PURCHASE_COST,
                                customer_price=CUSTOMER_PRICE, storage='Shelf A'))
    inventory.adjust(stock, 2, 'INV-1')
    part = Parts(service).save(job, dict(source='stock', inventory_id=stock, quantity=1))
    inventory.transfer(part, 'reserve', 'Reserved')

    # The third party's own cost, which is never the customer's business.
    PartyQuotes(service).issue(job, [dict(kind='part', name='Power board', quantity=1,
                                          unit_cost=PURCHASE_COST, customer_charge=CUSTOMER_PRICE)],
                               labour=VENDOR_LABOUR, reference='TPQ-1')
    service.record_work(job, 'diagnosis', {'notes': PRIVATE_NOTE})
    quote = service.issue_quote(job, 'Board replacement',
                                [{'description': 'Power board', 'amount': CUSTOMER_PRICE, 'kind': 'part'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    CustomerRecords(service).sync_customer(customer)
    return dict(service=service, customer=customer, job=job)


def tree_text(root):
    """Every readable file under one folder, concatenated."""
    body = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            try:
                body.append(path.read_text(encoding='utf-8'))
            except (UnicodeDecodeError, OSError):
                body.append('')  # photos and PDFs are checked separately
    return '\n'.join(body)


def test_the_customer_package_contains_no_internal_commercial_data(loaded):
    service = loaded['service']
    shareable = tree_text(service.db.root / 'Customers')
    assert shareable, 'expected customer records to have been generated'
    for secret in (str(PURCHASE_COST), str(PURCHASE_COST / 100), '800.00',
                   str(VENDOR_LABOUR), '1,500.00', PRIVATE_NOTE):
        assert secret not in shareable, f'internal value {secret!r} leaked into Customers/'
    for heading in ('Purchase Cost', 'Margin', 'Repair Parts', 'Expenses', 'Assignments',
                    'Custody History', 'Audit', 'Vendor', 'Supplier'):
        assert heading not in shareable, f'internal section {heading!r} leaked into Customers/'


def test_the_internal_package_does_keep_the_operational_record(loaded):
    service = loaded['service']
    internal = tree_text(service.db.root / 'Internal')
    assert internal, 'expected internal records to have been generated'
    assert PRIVATE_NOTE in internal, 'the shop keeps its own technician notes'
    for heading in ('Repair Parts', 'Assignments', 'Custody History', 'Audit',
                    'Third Party Quotes', 'Purchase Cost'):
        assert heading in internal, f'{heading} should be in the internal record'
    # The values themselves are present, so the customer-side check above is meaningful.
    for secret in (str(PURCHASE_COST), str(VENDOR_LABOUR)):
        assert secret in internal, f'{secret} should be recorded internally'


def test_the_customer_package_still_contains_what_the_customer_needs(loaded):
    service = loaded['service']
    shareable = tree_text(service.db.root / 'Customers')
    for expected in ('Separation Owner', 'Dell Laptop', 'No power', 'Charger',
                     'Initial Estimate', 'Approved Quotation', 'Balance Due'):
        assert expected in shareable, f'{expected!r} should be in the customer record'


def test_the_two_trees_are_physically_separate(loaded):
    service = loaded['service']
    customers = list((service.db.root / 'Customers').rglob('*.txt'))
    internal = list((service.db.root / 'Internal').rglob('*.txt'))
    assert customers and internal
    assert not any('Internal' in p.parts for p in customers)
    assert not any('Customers' in p.parts for p in internal)
    assert {p.name for p in customers} >= {'customer-job-summary.txt', 'customer-details.txt'}
    assert {p.name for p in internal} == {'internal-job-details.txt'}


def test_an_internal_document_is_never_filed_with_the_customer(loaded):
    from repairshop.job_cards import JobCards
    service, job = loaded['service'], loaded['job']
    card = JobCards(service).rows(job)[0]['id']
    assert 'Customers' in str(JobCards(service).print(card))
    assert 'Customers' not in str(JobCards(service).print(card, internal=True))


def test_the_customer_package_survives_backup_and_restore(loaded, tmp_path):
    """Splitting the tree must not drop either half from the archive."""
    import zipfile
    from repairshop.backup import Backups
    service = loaded['service']
    archive = Backups(service).create('manual', tmp_path / 'archives')
    Backups.validate(archive)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert any(n.startswith('Customers/') for n in names)
    assert any(n.startswith('Internal/') for n in names)
    Backups(service).restore(archive, 'RESTORE')
    assert (service.db.root / 'Customers').exists() and (service.db.root / 'Internal').exists()
