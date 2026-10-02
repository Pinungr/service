"""The HTTP platform: health, sessions, CSRF, the error contract, permissions and SPA serving."""
from fastapi.testclient import TestClient
from repairshop.api.app import create_app
from repairshop.api.config import Config
from api_support import api, customer, receive, act, Client, HEADERS, OWNER  # noqa: F401


def test_health_reports_schema_without_paths(api):
    body = api.ok('GET', '/api/health')
    assert body == dict(status='ok', database='ok', schema=15, expected_schema=15, version=body['version'])
    assert 'shop' not in str(body).lower() or 'shop.db' not in str(body)


def test_first_run_setup_happens_once(api):
    response = api.post('/api/auth/setup', json=OWNER)
    assert response.status_code == 409 and response.json()['error']['code'] == 'SETUP_DONE'
    assert api.ok('GET', '/api/auth/status') == dict(setup_required=False, shop_name='API Test Shop', authenticated=True)


def test_login_logout_and_session_cookie(api):
    me = api.ok('GET', '/api/auth/me')
    assert me['role'] == 'owner' and 'backup_restore' in me['permissions']
    api.ok('POST', '/api/auth/logout')
    response = api.get('/api/auth/me')
    assert response.status_code == 401
    assert response.json() == {'error': {'code': 'AUTHENTICATION_REQUIRED', 'message': 'Please sign in.', 'field': None}}
    bad = api.post('/api/auth/login', json=dict(username='owner', password='wrong-password!'))
    assert bad.status_code == 401 and bad.json()['error']['code'] == 'INVALID_CREDENTIALS'
    good = api.post('/api/auth/login', json=dict(username='owner', password=OWNER['password']))
    assert good.status_code == 200
    cookie = good.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie


def test_unsafe_requests_without_the_application_header_are_refused(tmp_path):
    app = create_app(Config(data_dir=tmp_path / 'shop', scheduler=False, frontend_dist=None))
    with TestClient(app) as client:
        response = client.post('/api/auth/setup', json=OWNER)
        assert response.status_code == 403 and response.json()['error']['code'] == 'CSRF_REJECTED'
        assert client.get('/api/health').status_code == 200


def test_error_contract_for_validation_conflict_and_unknown(api):
    response = api.post('/api/customers', json=dict(name='X' * 300))
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
    response = api.get('/api/repairs/424242')
    assert response.status_code == 404 and response.json()['error']['code'] == 'NOT_FOUND'
    response = api.get('/api/not-an-endpoint')
    assert response.status_code == 404 and response.json()['error']['code'] == 'NOT_FOUND'
    response = api.post('/api/customers', json=dict(name='', phone_number='9876500111', complete=False))
    assert response.status_code == 400 and response.json()['error']['code'] == 'BUSINESS_RULE'
    assert 'Traceback' not in response.text


def test_version_conflict_is_409_and_never_overwrites(api):
    job, _ = receive(api, customer(api))
    stale = api.ok('GET', f'/api/repairs/{job}')['version']
    act(api, job, 'inspect')
    response = api.post(f'/api/repairs/{job}/actions/inspection-done',
                        json=dict(expected_version=stale, payload=dict(notes='Late notes')))
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'VERSION_CONFLICT' and response.json()['error']['refresh'] is True
    assert api.ok('GET', f'/api/repairs/{job}')['stage'] == 'inspection'


def test_an_action_not_available_now_is_rejected_by_the_lifecycle(api):
    job, _ = receive(api, customer(api))
    version = api.ok('GET', f'/api/repairs/{job}')['version']
    response = api.post(f'/api/repairs/{job}/actions/start-repair', json=dict(expected_version=version))
    assert response.status_code == 409 and response.json()['error']['code'] == 'INVALID_LIFECYCLE_ACTION'
    response = api.post(f'/api/repairs/{job}/actions/set-stage', json=dict(expected_version=version))
    assert response.status_code == 404 and response.json()['error']['code'] == 'UNKNOWN_ACTION'


def test_retrying_an_action_with_the_same_operation_id_applies_it_once(api):
    job, _ = receive(api, customer(api))
    version = api.ok('GET', f'/api/repairs/{job}')['version']
    body = dict(expected_version=version, operation_id='retry-op-0001')
    first = api.ok('POST', f'/api/repairs/{job}/actions/inspect', json=body)
    again = api.ok('POST', f'/api/repairs/{job}/actions/inspect', json=body)
    assert first['replayed'] is False and again['replayed'] is True
    assert again['repair']['version'] == first['repair']['version']
    events = [e for e in api.ok('GET', f'/api/repairs/{job}/timeline') if e['action'] == 'lifecycle']
    assert len(events) == 1


def staff_client(api, role):
    api.ok('POST', '/api/staff', json=dict(username=role, name=role.title(), role=role, password='StaffPassword123'))
    other = Client(api.app)
    other.ok('POST', '/api/auth/login', json=dict(username=role, password='StaffPassword123'))
    return other


def test_permissions_are_enforced_by_the_backend(api):
    technician = staff_client(api, 'technician')
    for method, url in (('GET', '/api/backups'), ('GET', '/api/staff'), ('GET', '/api/reports/margins'),
                        ('GET', '/api/accounts/customer/entries'), ('GET', '/api/settings/messaging')):
        response = technician.request(method, url)
        assert response.status_code == 403, url
        assert response.json()['error']['code'] == 'PERMISSION_DENIED'
    response = technician.post('/api/staff', json=dict(username='x', name='X', role='owner', password='StaffPassword123'))
    assert response.status_code == 403


def test_a_technician_cannot_open_another_repair_by_id(api):
    job, _ = receive(api, customer(api))
    technician = staff_client(api, 'technician')
    assert technician.get(f'/api/repairs/{job}').status_code == 403
    assert technician.get(f'/api/repairs/{job}/journey').status_code == 403
    assert technician.ok('GET', '/api/repairs')['items'] == []
    assert technician.ok('GET', '/api/search', params={'q': '9876500100'}) == []


def test_deactivated_staff_lose_their_session_immediately(api):
    counter = staff_client(api, 'counter')
    assert counter.get('/api/dashboard').status_code == 200
    ident = next(u['id'] for u in api.ok('GET', '/api/staff') if u['username'] == 'counter')
    api.ok('PUT', f'/api/staff/{ident}', json=dict(username='counter', name='Counter', role='counter', active=False))
    assert counter.get('/api/dashboard').status_code == 401


def test_files_are_served_by_id_with_access_checks_and_no_paths(api):
    person = customer(api)
    overview = api.ok('GET', f'/api/customers/{person}')
    photo = overview['customer']['current_photo_id']
    response = api.get(f'/api/files/{photo}')
    assert response.status_code == 200 and response.headers['content-type'] == 'image/jpeg'
    assert response.content[:3] == b'\xff\xd8\xff'
    assert 'Customers/' not in str(overview) and 'managed' not in str(overview).lower()
    # Technicians take products in, so customer photos are theirs to see; a repair they
    # are not assigned to is not.
    job, out = receive(api, person)
    receipt = next(d for d in out['documents'] if d['job_id'] == job)
    technician = staff_client(api, 'technician')
    assert technician.get(f'/api/files/{photo}').status_code == 200
    assert technician.get(f"/api/files/{receipt['id']}").status_code == 403
    assert api.get(f"/api/files/{receipt['id']}").content[:5] == b'%PDF-'
    assert api.get('/api/files/99999').status_code == 404


def test_uploads_must_be_real_images(api):
    person = api.ok('POST', '/api/customers', json=dict(name='No Photo', phone_number='9876500222', complete=False))['id']
    response = api.post(f'/api/customers/{person}/photos', files={'file': ('x.png', b'not an image', 'image/png')})
    assert response.status_code == 400 and 'could not be read' in response.json()['error']['message']


def test_spa_routes_fall_back_to_index_and_api_stays_api(tmp_path):
    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<div id="root"></div>', encoding='utf-8')
    (dist / 'assets' / 'app.js').write_text('console.log(1)', encoding='utf-8')
    app = create_app(Config(data_dir=tmp_path / 'shop', scheduler=False, frontend_dist=dist))
    with TestClient(app, headers=HEADERS) as client:
        for route in ('/', '/repairs/42', '/contacts', '/customers/7'):
            response = client.get(route)
            assert response.status_code == 200 and 'root' in response.text, route
        assert client.get('/assets/app.js').text == 'console.log(1)'
        assert client.get('/api/unknown').status_code == 404
        assert client.get('/..%2Fshop%2Fshop.db').text == '<div id="root"></div>'


def test_duplicate_customer_phone_needs_confirmation(api):
    customer(api, 'First Person', '9876500333')
    response = api.post('/api/customers', json=dict(name='Second Person', phone_number='9876500333', complete=False))
    assert response.status_code == 409 and response.json()['error']['code'] == 'DUPLICATE_PHONE'
    assert [m['name'] for m in api.ok('GET', '/api/customers/phone-matches', params={'phone': '9876500333'})] == ['First Person']
    created = api.ok('POST', '/api/customers', json=dict(name='Second Person', phone_number='9876500333',
                                                          complete=False, confirm_shared_phone=True))
    assert created['phone'] == '+919876500333'


def test_global_search_finds_by_mobile_and_job_number(api):
    job, _ = receive(api, customer(api, phone='9876500444'))
    number = api.ok('GET', f'/api/repairs/{job}')['number']
    assert [h['id'] for h in api.ok('GET', '/api/search', params={'q': '9876500444'})] == [job]
    hit = api.ok('GET', '/api/search', params={'q': number})[0]
    assert hit['id'] == job and hit['status'] == 'RECEIVED'


def test_dashboard_is_prepared_by_the_backend(api):
    receive(api, customer(api))
    board = api.ok('GET', '/api/dashboard')
    assert next(c for c in board['queue'] if c['key'] == 'received')['count'] == 1
    assert board['mine_only'] is False and board['messaging_mode'] == 'test'
