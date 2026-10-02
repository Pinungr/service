"""Parts, inventory, warranty, accounts, documents, reports, notifications, backups and the scheduler."""
from api_support import api, customer, receive, act, to_route  # noqa: F401


def in_house(api):
    technician = api.ok('POST', '/api/setup/technician', json=dict(name='Asha'))['id']
    job, _ = receive(api, customer(api))
    to_route(api, job)
    act(api, job, 'select-route', dict(route='in_house', technician_master_id=technician))
    act(api, job, 'hand-technician', dict(condition='As received', acknowledgment='Asha', bench='B1'))
    act(api, job, 'diagnose', dict(notes='Battery dead', repairable=True))
    return job


def test_inventory_part_reserved_issued_and_installed(api):
    stock = api.ok('POST', '/api/inventory', json=dict(name='Battery 56Wh', purchase_cost=180000, customer_price=250000,
                                                       warranty_duration=6, warranty_provider='Shop'))['id']
    api.ok('POST', f'/api/inventory/{stock}/adjust', json=dict(quantity=3, reference='INV-1'))
    assert next(r for r in api.ok('GET', '/api/inventory') if r['id'] == stock)['available'] == 3
    job = in_house(api)
    part = api.ok('POST', f'/api/repairs/{job}/parts', json=dict(name='Battery 56Wh', source='stock', inventory_id=stock,
                                                                 customer_price=250000, purchase_cost=180000,
                                                                 warranty_duration=6, warranty_provider='Shop'))['id']
    api.ok('POST', f'/api/parts/{part}/transfer', json=dict(action='reserve', reference='Shelf A'))
    assert next(r for r in api.ok('GET', '/api/inventory') if r['id'] == stock)['reserved'] == 1
    preview = api.ok('POST', f'/api/repairs/{job}/quotes/preview', json=dict(lines=[dict(description='Labour', amount=50000)]))
    assert preview['total'] == 300000 and preview['previous_approved'] is None
    quote = api.ok('POST', f'/api/repairs/{job}/quotes', json=dict(scope='Battery', lines=[dict(description='Labour', amount=50000)]))['id']
    api.ok('POST', f'/api/quotes/{quote}/decision', json=dict(decision='approved', person='Owner', channel='call'))
    api.ok('POST', f'/api/parts/{part}/transfer', json=dict(action='issue', reference='Given to Asha'))
    act(api, job, 'start-repair')
    api.ok('POST', f'/api/parts/{part}/install', json=dict(installed_by='Asha'))
    rows = api.ok('GET', f'/api/repairs/{job}/parts')
    assert rows[0]['status'] == 'installed'
    act(api, job, 'complete-repair', dict(notes='Battery replaced'))
    warranty = api.ok('GET', f'/api/repairs/{job}/warranty')
    assert warranty['warranties'][0]['name'] == 'Battery 56Wh'
    assert any(m['kind'] == 'INSTALLED' for m in api.ok('GET', '/api/inventory/movements', params=dict(stock_id=stock)))


def test_accounts_ledger_and_reversal(api):
    person = customer(api)
    entry = api.ok('POST', '/api/accounts/customer/entries', json=dict(account_id=person, kind='receipt', amount=50000, method='UPI'))['id']
    ledger = api.ok('GET', f'/api/accounts/customer/{person}/ledger')
    assert ledger['closing'] == -50000 and ledger['rows'][0]['amount'] == -50000
    api.ok('POST', f'/api/entries/{entry}/reverse', json=dict(reason='Entered twice'))
    assert api.ok('GET', f'/api/accounts/customer/{person}/ledger')['closing'] == 0
    assert any(e['reversed'] for e in api.ok('GET', '/api/accounts/customer/entries'))


def test_documents_reports_and_exports(api):
    job, _ = receive(api, customer(api))
    card = api.ok('GET', f'/api/repairs/{job}/cards')[0]
    assert card['kind'] == 'customer_receiving' and card['snapshot']['master_job']
    printed = api.ok('POST', f"/api/cards/{card['id']}/print", json={})
    assert api.get(printed['url']).content[:5] == b'%PDF-'
    upload = api.ok('POST', f'/api/repairs/{job}/attachments', files={'file': ('slip.pdf', b'%PDF-1.4 test', 'application/pdf')},
                    data={'title': 'Purchase slip'})
    assert upload['title'] == 'Purchase slip'
    fake = api.post(f'/api/repairs/{job}/attachments', files={'file': ('slip.pdf', b'not a pdf', 'application/pdf')})
    assert fake.status_code == 400
    rows = api.ok('GET', '/api/reports/jobs')
    assert rows and rows[0]['number'].startswith('REP-')
    exported = api.get('/api/reports/jobs/export', params=dict(format='csv'))
    assert exported.status_code == 200 and 'number' in exported.text.splitlines()[0]


def test_notifications_queue_preview_and_scheduler(api):
    from repairshop.images import solid
    person = api.ok('POST', '/api/customers', json=dict(name='Consenting', phone_number='9876500888', complete=False,
                                                        whatsapp_consent=True))['id']
    api.ok('POST', f'/api/customers/{person}/photos', files={'file': ('me.png', solid(), 'image/png')})
    receive(api, person)
    messages = api.ok('GET', '/api/notifications')
    assert messages and messages[0]['event'] == 'received'
    preview = api.ok('GET', f"/api/notifications/{messages[0]['id']}")
    assert 'received' in preview['body'].lower()
    processed = api.ok('POST', '/api/notifications/process')
    assert processed['processed'] >= 1
    assert api.ok('GET', '/api/notifications')[0]['state'] in ('captured', 'blocked_consent', 'channel_disabled', 'blocked_configuration')
    runtime = api.app_state
    done = runtime.scheduler.tick()
    assert set(done) >= {'messages', 'folders', 'backups'}


def test_backups_are_listed_by_name_and_validated(api):
    created = api.ok('POST', '/api/backups', json=dict(kind='daily'))
    listing = api.ok('GET', '/api/backups')
    row = listing['backups'][0]
    assert row['name'] == created['created'] and 'path' not in row and ':' not in row['name']
    checked = api.ok('POST', f"/api/backups/{row['id']}/validate")
    assert checked['schema'] == 15
    response = api.post(f"/api/backups/{row['id']}/restore", json=dict(confirmation='yes'))
    assert response.status_code == 400


def test_settings_and_staff(api):
    api.ok('PUT', '/api/settings/shop', json=dict(shop_name='Renamed Shop', hours='9-7'))
    assert api.ok('GET', '/api/settings/shop')['shop_name'] == 'Renamed Shop'
    sections = api.ok('GET', '/api/settings/application')
    assert sections and sections[0]['settings']
    staff = api.ok('POST', '/api/staff', json=dict(username='ravi', name='Ravi', role='counter', password='StaffPassword123'))['id']
    assert staff in {u['id'] for u in api.ok('GET', '/api/staff')}


def test_existing_legacy_jobs_stay_readable(api):
    """A repair recorded without guided lifecycle evidence still opens and offers adoption."""
    from repairshop.services import Service
    rt = api.app_state
    s = Service(rt.db)
    s.login('owner', 'CorrectHorse123!')
    person = customer(api, 'Legacy Person', '9876500777')
    job = s.intake(person, 'Old laptop', 'Legacy fault', accessories=[], assessment_consent=True)
    repair = api.ok('GET', f'/api/repairs/{job}')
    assert repair['legacy'] is True and [a['key'] for a in repair['actions']] == ['adopt']
    assert api.ok('GET', f'/api/repairs/{job}/journey')['nodes']
    assert api.ok('GET', f'/api/repairs/{job}/records')['items']
