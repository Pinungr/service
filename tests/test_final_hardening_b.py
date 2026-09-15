"""Customer job card setting, sales dashboard card scoping, internal cost by permission."""
from repairshop.inventory import Inventory
from repairshop.queries import Queries

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')


def staff(service, username, role):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def test_the_shop_keeps_its_own_job_card_when_the_customer_copy_is_switched_off(service, customer):
    service.settings({'auto_job_card': False})
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True, initial_estimate=100000)
    assert service.db.one('SELECT * FROM job_cards WHERE event_key=?', (f'intake:{job}',)), \
        'the internal card record must be written whatever the setting says'
    assert not list((service.db.root / 'Customers').rglob('*.pdf')), \
        'the customer copy is the only thing the setting switches off'


def test_the_customer_copy_is_produced_when_the_setting_is_on(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True, initial_estimate=100000)
    assert service.db.one('SELECT * FROM job_cards WHERE event_key=?', (f'intake:{job}',))
    assert list((service.db.root / 'Customers').rglob('*.pdf')), 'expected a printed customer copy'


def test_products_awaiting_collection_is_hidden_from_staff_who_cannot_sell(service):
    assert Queries(service).dashboard()['sales'] is not None
    staff(service, 'amit', 'technician')
    service.login('amit', 'TestPassword123')
    assert Queries(service).dashboard()['sales'] is None, \
        'a technician has no business seeing shop sales awaiting collection'


def test_purchase_cost_is_masked_by_permission_not_by_role_name(service):
    stock = Inventory(service).save(dict(name='Power board', purchase_cost=80000,
                                         customer_price=220000, storage='Shelf A'))
    mine = [r for r in Inventory(service).rows() if r['id'] == stock]
    assert mine and mine[0]['purchase_cost'] == 80000
    staff(service, 'sneha', 'counter')
    service.login('sneha', 'TestPassword123')
    seen = [r for r in Inventory(service).rows() if r['id'] == stock]
    assert seen and not seen[0].get('purchase_cost'), 'counter must not see purchase cost'
