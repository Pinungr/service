"""Complete repair routes through the HTTP API, checking custody at every handover."""
from api_support import api, customer, receive, act, to_route, category  # noqa: F401


PASSED_QC = dict(check_functional='passed', check_power='passed', check_complaint='passed', check_charging='not_applicable',
                 check_display='passed', check_connectivity='not_applicable', result='passed', notes='OK')


def devices_at(api, job):
    return {h['location'] for h in api.ok('GET', f'/api/repairs/{job}/items')['holdings'] if h['type'] == 'device'}


def quick(api, kind, name, mobile, job=None, **extra):
    return api.ok('POST', '/api/contacts/quick-create', json=dict(kind=kind, name=name, mobile=mobile, job_id=job, **extra))


def approve_estimate(api, job, amount=150000):
    quote = api.ok('POST', f'/api/repairs/{job}/quotes', json=dict(scope='Board repair', lines=[dict(description='Labour', amount=amount)]))['id']
    detail = api.ok('GET', f'/api/quotes/{quote}')
    assert detail['total'] == amount and detail['decisions'] == ['approved', 'declined']
    api.ok('POST', f'/api/quotes/{quote}/decision', json=dict(decision='approved', person='Device owner', channel='in_person'))
    return quote


def finish(api, job, expect_balance):
    repair = act(api, job, 'bill', dict(confirmed=True))
    assert repair['stage'] == 'ready_repaired' and repair['balance'] == expect_balance
    if expect_balance:
        api.ok('POST', '/api/accounts/customer/entries', json=dict(account_id=repair['customer_id'], kind='receipt',
                                                                   amount=expect_balance, job_id=job, method='Cash'))
    form = api.ok('GET', f'/api/repairs/{job}/actions/handover/form')
    assert next(f for f in form['fields'] if f['key'] == 'received_by')['default'] == repair['customer']
    repair = act(api, job, 'handover', dict(demonstrated=True, accepted=True, accessories_returned=True, payment_checked=True,
                                            received_by=repair['customer'], acknowledgment='Signed receipt R-1'))
    assert repair['stage'] == 'collected' and devices_at(api, job) == {'customer'}
    receipt = api.ok('POST', f'/api/repairs/{job}/documents', json=dict(kind='collection_receipt'))
    assert api.get(receipt['url']).content[:5] == b'%PDF-'
    return act(api, job, 'close')


def test_third_party_route_end_to_end(api):
    person = customer(api)
    job, intake = receive(api, person, accessories=[dict(description='Charger', quantity=1, condition='Working')])
    assert intake['visit']['number'].startswith('VIS-') and any('Visit intake receipt' == d['title'] for d in intake['documents'])
    to_route(api, job)
    repair = api.ok('GET', f'/api/repairs/{job}')
    assert repair['primary'] == 'select_route'
    form = api.ok('GET', f'/api/repairs/{job}/actions/select-route/form')
    routes = {o['value']: o for o in form['fields'][0]['options']}
    assert routes['third_party']['disabled'] is False and routes['warranty_centre']['disabled'] is True
    partner = quick(api, 'vendor', 'Rajesh Laptop Services', '9876543210', job, specialization='Laptop, Motherboard')
    repair = act(api, job, 'select-route', dict(route='third_party', vendor_id=partner['id'], reference='EXT-77',
                                               expected_return='2099-02-01', instructions='Keep customer data'))
    assert repair['assignment']['party'] == 'Rajesh Laptop Services' and repair['assignment']['reference'] == 'EXT-77'
    # Assignment is not custody: the device has not moved.
    assert all(l.startswith('staff:') for l in devices_at(api, job))
    bus = quick(api, 'transporter', 'Sharma Travels', '9990012345', route_from='Pune', route_to='Bhubaneswar',
                vehicle_number='MH12AB1234')
    form = api.ok('GET', f'/api/repairs/{job}/actions/prepare-dispatch/form')
    fields = {f['key']: f for f in form['fields']}
    assert fields['reference']['default'] == 'EXT-77' and fields['transport']['default'] == {'mode': 'BUS'}
    assert len(fields['items']['default']) == 1 and len(fields['items']['options']) == 2
    act(api, job, 'prepare-dispatch', dict(
        transport=dict(mode='BUS', service_id=bus['id'], fields=dict(bus_number='MH12XY9999', parcel_number='P-501', departure_time='21:30')),
        transport_amount=35000, paid_by='shop', condition='Intact', items=fields['items']['default'], consent=True))
    dispatch = api.ok('GET', f'/api/repairs/{job}/dispatch')['current']
    assert dispatch['transporter_snapshot']['route_to'] == 'Bhubaneswar' and dispatch['amount'] == 35000
    assert dispatch['transport']['bus_number'] == 'MH12XY9999'
    send = {f['key']: f.get('default') for f in api.ok('GET', f'/api/repairs/{job}/actions/dispatch/form')['fields']}
    assert send['carrier'] == 'Sharma Travels · MH12XY9999' and send['reference'] == 'P-501'
    act(api, job, 'dispatch', dict(counterparty='Ramesh', condition='Intact', acknowledgment='Parcel slip', carrier=send['carrier']))
    assert devices_at(api, job) == {'transit:Sharma Travels · MH12XY9999'}
    act(api, job, 'arrive', dict(counterparty='Rajesh', condition='Intact', acknowledgment='Received at Wakad'))
    assert devices_at(api, job) == {'vendor:Rajesh Laptop Services'}
    act(api, job, 'diagnose', dict(notes='Power IC failed', repairable=True))
    approve_estimate(api, job)
    act(api, job, 'start-repair')
    act(api, job, 'complete-repair', dict(notes='Power IC replaced', parts='Power IC'))
    expected = api.ok('GET', f'/api/repairs/{job}/actions/receive/form')
    returning = next(f for f in expected['fields'] if f['key'] == 'return_items')['options']
    assert [o['label'] for o in returning] == ['Dell Inspiron']
    act(api, job, 'receive', dict(counterparty='Rajesh', condition='Repaired', acknowledgment='Return slip', verified=True,
                                  repair_result='REPAIRED', return_items=[dict(item_id=o['value'], received=o['expected']) for o in returning]))
    assert all(l.startswith('staff:') for l in devices_at(api, job))
    act(api, job, 'qc', dict(check_functional='passed', check_power='passed', check_complaint='passed',
                             check_charging='not_applicable', check_display='passed', check_connectivity='passed',
                             result='passed', notes='All good'))
    closed = finish(api, job, 150000)
    assert closed['stage'] == 'closed'
    nodes = api.ok('GET', f'/api/repairs/{job}/journey')['nodes']
    assert all(n['status'] in ('completed', 'skipped') for n in nodes if n['key'] != 'closed')
    attempts = api.ok('GET', f'/api/repairs/{job}/dispatch')['attempts']
    assert attempts[0]['partner'] == 'Rajesh Laptop Services' and attempts[0]['result'] == 'REPAIRED'
    contact_history = [e for e in api.ok('GET', f'/api/repairs/{job}/timeline') if e['action'] == 'contact_created']
    assert len(contact_history) == 1


def test_service_centre_warranty_route(api):
    phone = category(api, 'Phone')
    centre = api.ok('POST', '/api/contacts', json=dict(kind='centre', name='Samsung Service Centre Pune', mobile='9000000012',
                                                        brands='Samsung', supports=[phone], warranty_service=True))
    api.ok('POST', '/api/contacts', json=dict(kind='centre', name='Apple Care Pune', mobile='9000000011', brands='Apple'))
    job, _ = receive(api, customer(api), 'Galaxy S21', 'Phone', brand='Samsung')
    to_route(api, job, 'under_warranty')
    options = api.ok('GET', '/api/contacts/options', params=dict(kind='centre', job_id=job))
    assert [o['name'] for o in options['recommended']] == ['Samsung Service Centre Pune']
    assert [o['name'] for o in options['others']] == ['Apple Care Pune']
    form = api.ok('GET', f'/api/repairs/{job}/actions/select-route/form')
    assert {o['value']: o['disabled'] for o in form['fields'][0]['options']} == {
        'warranty_centre': False, 'in_house': True, 'third_party': True}
    act(api, job, 'select-route', dict(route='warranty_centre', centre_id=centre['id'], reference='RMA-1'))
    act(api, job, 'prepare-dispatch', dict(transport=dict(mode='COURIER', fields=dict(courier_name='Blue Dart', docket_number='BD1')),
                                           condition='Intact', items=[i['id'] for i in api.ok('GET', f'/api/repairs/{job}/items')['holdings']
                                                                      if i['type'] == 'device'], consent=True))
    assert 'Blue Dart' in api.ok('GET', '/api/dispatch/courier-suggestions')
    act(api, job, 'dispatch', dict(counterparty='Courier', condition='Intact', acknowledgment='D1', carrier='Blue Dart'))
    act(api, job, 'arrive', dict(counterparty='Centre desk', condition='Intact', acknowledgment='A1'))
    assert devices_at(api, job) == {'centre:Samsung Service Centre Pune'}
    act(api, job, 'diagnose', dict(notes='Display fault under warranty', repairable=True))
    repair = act(api, job, 'warranty-result', dict(decision='accepted', rma='RMA-1', notes='Covered'))
    assert repair['stage'] == 'approved'
    act(api, job, 'start-repair')
    act(api, job, 'complete-repair', dict(notes='Display replaced'))
    items = next(f for f in api.ok('GET', f'/api/repairs/{job}/actions/receive/form')['fields'] if f['key'] == 'return_items')['options']
    act(api, job, 'receive', dict(counterparty='Centre', condition='Good', acknowledgment='R1', verified=True,
                                  return_items=[dict(item_id=o['value'], received=o['expected']) for o in items]))
    act(api, job, 'qc', PASSED_QC)
    assert finish(api, job, 0)['stage'] == 'closed'
    journey = api.ok('GET', f'/api/repairs/{job}/journey')['nodes']
    assert {n['key']: n['status'] for n in journey}['awaiting_estimate'] == 'skipped'


def test_in_house_route_with_technician_test_and_rework(api):
    technician = api.ok('POST', '/api/setup/technician', json=dict(name='Asha'))['id']
    job, _ = receive(api, customer(api))
    to_route(api, job)
    act(api, job, 'select-route', dict(route='in_house', technician_master_id=technician))
    act(api, job, 'hand-technician', dict(condition='As received', acknowledgment='Asha signed', bench='Bench 2'))
    assert devices_at(api, job) == {f'technician:master-{technician}'}
    act(api, job, 'diagnose', dict(notes='Keyboard ribbon', repairable=True))
    approve_estimate(api, job, 50000)
    act(api, job, 'start-repair')
    act(api, job, 'complete-repair', dict(notes='Ribbon reseated'))
    repair = act(api, job, 'test', dict(result='failed', notes='Keys still dead'))
    assert repair['stage'] == 'diagnosis'
    act(api, job, 'diagnose', dict(notes='Keyboard replaced needed', repairable=True))
    approve_estimate(api, job, 90000)
    act(api, job, 'start-repair')
    act(api, job, 'complete-repair', dict(notes='Keyboard replaced'))
    act(api, job, 'test', dict(result='passed', notes='All keys work'))
    act(api, job, 'return-technician', dict(condition='Repaired', acknowledgment='Back to counter'))
    assert all(l.startswith('staff:') for l in devices_at(api, job))
    act(api, job, 'qc', PASSED_QC)
    assert finish(api, job, 90000)['stage'] == 'closed'


def test_customer_decline_returns_unrepaired(api):
    partner = quick(api, 'vendor', 'Decline Lab', '9876511111')
    job, _ = receive(api, customer(api))
    to_route(api, job)
    act(api, job, 'select-route', dict(route='third_party', vendor_id=partner['id']))
    repair = act(api, job, 'decline', dict(reason='Customer declined repair', notes='Too expensive'))
    assert repair['stage'] == 'return_unrepaired'
    nodes = {n['key']: n['status'] for n in api.ok('GET', f'/api/repairs/{job}/journey')['nodes']}
    assert nodes['return_unrepaired'] in ('cancelled', 'current', 'waiting')
