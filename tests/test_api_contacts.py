"""Contacts & Services through the API: configure once, select many times, keep history."""
from api_support import api, customer, receive, act, to_route  # noqa: F401


def create(api, **values):
    return api.ok('POST', '/api/contacts', json=values)


def test_partner_supplier_and_bus_service_crud(api):
    repairer = create(api, kind='vendor', name='Rajesh Laptop Services', mobile='9876543210', specialization='Laptop')
    assert repairer['mobile'] == '+919876543210' and repairer['kind_label'] == 'Third-Party Repairer'
    updated = api.ok('PATCH', f"/api/contacts/{repairer['id']}", json=dict(contact_person='Rajesh Kumar', city='Pune'))
    assert updated['contact_person'] == 'Rajesh Kumar' and updated['name'] == 'Rajesh Laptop Services'
    centre = create(api, kind='centre', name='HP Centre', mobile='9000000001', brands='HP', turnaround_days=5)
    assert centre['brands'] == ['HP'] and 'Usual turnaround 5 days' in centre['summary']
    supplier = create(api, kind='supplier', name='Lamington Spares', mobile='9000000002', specialization='Screens')
    bus = create(api, kind='transporter', name='Sharma Travels', mobile='9990012345', route_from='Pune', route_to='Bhubaneswar',
                 pickup_point='Wakad', drop_point='Baramunda', vehicle_number='MH12AB1234')
    assert 'Pune → Bhubaneswar' in bus['summary'] and 'Usual bus: MH12AB1234' in bus['summary']
    for kind, ident in (('vendor', repairer['id']), ('centre', centre['id']), ('supplier', supplier['id']), ('transporter', bus['id'])):
        assert ident in {c['id'] for c in api.ok('GET', '/api/contacts', params=dict(kind=kind))}
    response = api.post('/api/contacts', json=dict(kind='transporter', name='X Bus', mobile='9000000003', brands='HP'))
    assert response.status_code == 400 and response.json()['error']['code'] == 'NOT_APPLICABLE'


def test_quick_create_saves_globally_and_is_ready_to_select(api):
    job, _ = receive(api, customer(api))
    option = api.ok('POST', '/api/contacts/quick-create', json=dict(kind='vendor', name='Chip Lab', mobile='9000000010',
                                                                    specialization='Chip-level', job_id=job))
    assert option['name'] == 'Chip Lab' and 'Chip Lab' in option['summary']
    assert option['id'] in {c['id'] for c in api.ok('GET', '/api/contacts', params=dict(kind='vendor'))}
    assert any(e['action'] == 'contact_created' for e in api.ok('GET', f'/api/repairs/{job}/timeline'))


def test_duplicate_detection_offers_use_existing_or_create_anyway(api):
    create(api, kind='vendor', name='Rajesh Laptop Services', mobile='9876543210', city='Pune')
    response = api.post('/api/contacts/quick-create', json=dict(kind='vendor', name='RLS Repairs', mobile='+91 98765 43210'))
    assert response.status_code == 409
    error = response.json()['error']
    assert error['code'] == 'DUPLICATE_CONTACT' and error['matches'][0]['reasons'] == ['same mobile']
    again = api.ok('POST', '/api/contacts/quick-create', json=dict(kind='vendor', name='RLS Repairs', mobile='9876543210',
                                                                   allow_duplicate=True))
    assert again['name'] == 'RLS Repairs'
    exact = api.post('/api/contacts/quick-create', json=dict(kind='vendor', name='rajesh laptop services', mobile='9000000020',
                                                             allow_duplicate=True))
    assert exact.status_code == 400 and 'exactly this name' in exact.json()['error']['message']


def test_inactive_contacts_leave_selectors_but_stay_in_history(api):
    partner = create(api, kind='vendor', name='Old Lab', mobile='9000000030')
    job, _ = receive(api, customer(api))
    to_route(api, job)
    act(api, job, 'select-route', dict(route='third_party', vendor_id=partner['id']))
    api.ok('POST', f"/api/contacts/{partner['id']}/deactivate")
    options = api.ok('GET', '/api/contacts/options', params=dict(kind='vendor'))
    assert partner['id'] not in {o['id'] for o in options['recommended'] + options['others']}
    assert partner['id'] in {c['id'] for c in api.ok('GET', '/api/contacts', params=dict(kind='vendor', include_inactive=True))}
    assert api.ok('GET', f'/api/repairs/{job}')['assignment']['party'] == 'Old Lab'
    assert api.ok('POST', f"/api/contacts/{partner['id']}/activate")['active'] is True


def test_repairer_recommendations_rank_but_never_hide(api):
    laptop = next(c['id'] for c in api.ok('GET', '/api/intake/reference')['categories'] if c['name'] == 'Laptop')
    create(api, kind='vendor', name='Speaker Shop', mobile='9000000040', specialization='Speakers')
    create(api, kind='vendor', name='Laptop Lab', mobile='9000000041', supports=[laptop])
    job, _ = receive(api, customer(api))
    options = api.ok('GET', '/api/contacts/options', params=dict(kind='vendor', job_id=job))
    assert [o['name'] for o in options['recommended']] == ['Laptop Lab']
    assert [o['name'] for o in options['others']] == ['Speaker Shop']


def test_history_keeps_the_partner_as_it_was(api):
    """Requirement: editing the master never rewrites an earlier assignment or dispatch."""
    partner = create(api, kind='vendor', name='Rajesh Laptop Services', mobile='9876543210', address_line1='Shop 4, Wakad', city='Wakad')
    job, _ = receive(api, customer(api))
    to_route(api, job)
    act(api, job, 'select-route', dict(route='third_party', vendor_id=partner['id']))
    items = [h['id'] for h in api.ok('GET', f'/api/repairs/{job}/items')['holdings'] if h['type'] == 'device']
    act(api, job, 'prepare-dispatch', dict(transport=dict(mode='IN_HAND', fields=dict(person_name='Shop runner', mobile='9990011001', role='Staff')),
                                           condition='Intact', items=items, consent=True))
    act(api, job, 'dispatch', dict(counterparty='Shop runner', condition='Intact', acknowledgment='D1', carrier='Shop runner'))
    api.ok('PATCH', f"/api/contacts/{partner['id']}", json=dict(mobile='9999999999', address_line1='Office 9, Baner', city='Baner'))
    old = api.ok('GET', f'/api/repairs/{job}')['assignment']
    assert old['contact'] == '+919876543210' and 'Wakad' in old['partner']['address'] and 'Baner' not in old['summary']
    sent = api.ok('GET', f'/api/repairs/{job}/dispatch')['current']
    assert sent['contact_snapshot']['phone'] == '+919876543210' and 'Wakad' in sent['contact_snapshot']['address']
    second, _ = receive(api, customer(api, 'Another', '9876500999'), 'HP Pavilion')
    to_route(api, second)
    act(api, second, 'select-route', dict(route='third_party', vendor_id=partner['id']))
    new = api.ok('GET', f'/api/repairs/{second}')['assignment']
    assert new['contact'] == '+919999999999' and 'Baner' in new['partner']['address']


def test_bus_default_number_is_prefilled_and_actual_bus_kept(api):
    bus = create(api, kind='transporter', name='Sharma Travels', mobile='9990012345', vehicle_number='MH12AB1234')
    partner = create(api, kind='vendor', name='Lab', mobile='9000000050')
    job, _ = receive(api, customer(api))
    to_route(api, job)
    act(api, job, 'select-route', dict(route='third_party', vendor_id=partner['id']))
    options = api.ok('GET', '/api/contacts/options', params=dict(kind='transporter'))['others']
    assert options[0]['snapshot']['vehicle_number'] == 'MH12AB1234'
    items = [h['id'] for h in api.ok('GET', f'/api/repairs/{job}/items')['holdings'] if h['type'] == 'device']
    act(api, job, 'prepare-dispatch', dict(transport=dict(mode='BUS', service_id=bus['id'], fields=dict(bus_number='OD02ZZ0001')),
                                           condition='Intact', items=items, consent=True))
    current = api.ok('GET', f'/api/repairs/{job}/dispatch')['current']
    assert current['transport']['bus_number'] == 'OD02ZZ0001' and current['transporter_snapshot']['vehicle_number'] == 'MH12AB1234'
    methods = {m['key']: m for m in api.ok('GET', '/api/dispatch/methods')['methods']}
    assert methods['BUS']['uses_bus_service'] and methods['COURIER']['free_text_company']
    assert set(methods) == {'BUS', 'COURIER', 'IN_HAND'}


def test_shop_setup_lists(api):
    service = api.ok('POST', '/api/setup/service', json=dict(name='Battery replacement'))['id']
    assert service in {r['id'] for r in api.ok('GET', '/api/setup/service')}
    api.ok('PATCH', f'/api/setup/service/{service}', json=dict(name='Battery replacement', active=False))
    assert not next(r for r in api.ok('GET', '/api/setup/service') if r['id'] == service)['active']
    assert api.get('/api/setup/transport_method').status_code == 422
