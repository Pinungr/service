"""Helpers for driving the real FastAPI application in tests (no browser, no PyQt)."""
import pytest
from fastapi.testclient import TestClient
from repairshop.api.app import create_app
from repairshop.api.config import Config
from repairshop.images import solid

HEADERS = {'X-Requested-With': 'RepairShop'}
OWNER = dict(shop='API Test Shop', name='Owner', username='owner', password='CorrectHorse123!')


class Client(TestClient):
    """A TestClient that sends the application's request header and fails loudly on errors."""

    def __init__(self, app):
        super().__init__(app, headers=HEADERS)

    def ok(self, method, url, **kwargs):
        response = self.request(method, url, **kwargs)
        assert response.status_code < 400, (response.status_code, response.text)
        return response.json()


@pytest.fixture
def api(tmp_path):
    app = create_app(Config(data_dir=tmp_path / 'shop', scheduler=False, frontend_dist=None))
    with Client(app) as client:
        client.ok('POST', '/api/auth/setup', json=OWNER)
        client.app_state = app.state.runtime
        yield client


def customer(api, name='Rajesh Customer', phone='9876500100'):
    ident = api.ok('POST', '/api/customers', json=dict(name=name, phone_number=phone, complete=False))['id']
    api.ok('POST', f'/api/customers/{ident}/photos', files={'file': ('me.png', solid(), 'image/png')}, data={'role': 'owner'})
    return ident


def category(api, name='Laptop'):
    return next(c['id'] for c in api.ok('GET', '/api/intake/reference')['categories'] if c['name'] == name)


def receive(api, customer_id, device='Dell Inspiron', cat='Laptop', **extra):
    cat_id = category(api, cat)
    service = api.ok('GET', f'/api/intake/categories/{cat_id}/services')[0]['id']
    photo = api.ok('GET', f'/api/customers/{customer_id}')['customer']['current_photo_id']
    product = dict(customer_id=customer_id, photo_id=photo, device=device, complaint='Does not power on',
                   category_id=cat_id, service_id=service, brand=extra.pop('brand', 'Dell'), model='5510', **extra)
    out = api.ok('POST', '/api/intake/visits', json=dict(products=[product]))
    return out['jobs'][0]['id'], out


def act(api, job, action, payload=None, operation_id=None):
    version = api.ok('GET', f'/api/repairs/{job}')['version']
    body = dict(expected_version=version, payload=payload or {})
    if operation_id:
        body['operation_id'] = operation_id
    return api.ok('POST', f'/api/repairs/{job}/actions/{action}', json=body)['repair']


def to_route(api, job, warranty='out_of_warranty'):
    act(api, job, 'inspect')
    act(api, job, 'inspection-done', dict(notes='Board looks fine'))
    act(api, job, 'verify-warranty', dict(warranty_status=warranty, notes='Checked invoice'))
