import json
from datetime import date, timedelta

import pytest

from repairshop.domain import RuleError
from repairshop.warranties import sale_warranty


@pytest.mark.parametrize('start,expiry,status,duration', [
    ('2026-01-01', '2027-01-01', 'VALID', 365),
    ('2026-01-01', '2026-09-12', 'EXPIRED', 254),
    ('2026-09-14', '2027-09-14', 'NOT_STARTED', 365),
    (None, None, 'UNKNOWN', None),
    ('2027-01-01', '2026-01-01', 'UNKNOWN', None),
    (None, '2026-09-13', 'VALID', None),
])
def test_sale_warranty_dates(start, expiry, status, duration):
    result = sale_warranty(dict(id=7, warranty_start=start, warranty_end=expiry), on='2026-09-13')
    assert result['status'] == status
    assert result['duration_days'] == duration
    assert result['verification'] == 'sale_dates_only'


def test_shop_intake_uses_sale_record_not_submitted_status(service, customer):
    expiry = (date.today() - timedelta(days=1)).isoformat()
    sale = service.save_sale(customer, 'Old laptop', warranty_end=expiry, provider='Recorded supplier')
    ident = service.intake(customer, 'Old laptop', 'Broken screen', sale_id=sale, guided=True,
                           intake_warranty={'source': 'shop', 'status': 'VALID', 'provider': 'Fake'})
    job = service.job(ident)
    data = json.loads(job['lifecycle_data'])
    assert data['intake_warranty']['status'] == 'EXPIRED'
    assert data['intake_warranty']['provider'] == 'Recorded supplier'
    assert data['intake_warranty']['sale_id'] == sale
    assert 'warranty_status' not in data
    assert job['stage'] == 'received'
    assert service.db.one('SELECT count(*) n FROM manual_warranty_checks')['n'] == 0
    assert service.db.one('SELECT count(*) n FROM warranty')['n'] == 0


def test_external_report_saved_with_audit_but_no_verified_coverage(service, customer):
    expiry = (date.today() + timedelta(days=30)).isoformat()
    ident = service.intake(customer, 'Laptop', 'No power', guided=True,
                           intake_warranty={'source': 'external', 'status': 'VALID', 'expiry': expiry,
                                            'provider': ' Manufacturer ', 'notes': 'Customer has a receipt'})
    snapshot = json.loads(service.job(ident)['lifecycle_data'])['intake_warranty']
    assert snapshot['expiry'] == expiry
    assert snapshot['provider'] == 'Manufacturer'
    assert snapshot['verification'] == 'customer_reported'
    audit = service.db.one("SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='intake_warranty_recorded'", (ident,))
    assert json.loads(audit['payload']) == snapshot
    assert service.job(ident)['stage'] == 'received'
    assert service.db.one('SELECT count(*) n FROM manual_warranty_checks')['n'] == 0


@pytest.mark.parametrize('metadata', [
    {'source': 'shop', 'status': 'VALID'},
    {'source': 'external', 'status': 'APPROVED'},
    {'source': 'external', 'status': 'VALID', 'expiry': 'invalid'},
    {'source': 'external', 'status': 'VALID', 'expiry': '2000-01-01'},
    {'source': 'external', 'status': 'VALID', 'coverage': 'manufacturer'},
])
def test_invalid_warranty_rolls_back_intake(service, customer, metadata):
    before = service.db.one('SELECT count(*) n FROM devices')['n']
    with pytest.raises(RuleError):
        service.intake(customer, 'Phone', 'No power', intake_warranty=metadata)
    assert service.db.one('SELECT count(*) n FROM jobs')['n'] == 0
    assert service.db.one('SELECT count(*) n FROM devices')['n'] == before


@pytest.mark.parametrize('status', ['EXPIRED', 'NONE', 'UNKNOWN'])
def test_hidden_external_details_do_not_leak_into_other_status(service, customer, status):
    ident = service.intake(customer, 'Phone', 'No power', intake_warranty={
        'source': 'external', 'status': status, 'expiry': '2099-01-01', 'provider': 'Old', 'notes': 'Old'})
    snapshot = json.loads(service.job(ident)['lifecycle_data'])['intake_warranty']
    assert snapshot['status'] == status
    assert snapshot['expiry'] is None
    assert snapshot['provider'] == snapshot['notes'] == ''


def test_intake_without_warranty_metadata_remains_supported(service, customer):
    ident = service.intake(customer, 'Phone', 'No power')
    assert 'intake_warranty' not in json.loads(service.job(ident)['lifecycle_data'])
