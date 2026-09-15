"""Regression coverage for the last release-hardening fixes.

These checks cover the paths that previously escaped the central permission/settings
layer: customer exports, customer financial projections, automatic job-card delivery,
document-specific paper, manual statement channel gating, and device warranty reads.
"""
import re
import uuid
import pytest
from repairshop.customer_records import CustomerRecords
from repairshop.documents import Documents
from repairshop.domain import RuleError
from repairshop.lifecycle import Lifecycle
from repairshop.queries import Queries
from repairshop.warranties import Warranties

MEDIA_BOX = re.compile(rb'/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*\]')


def staff(service, username, role):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def received(service, customer, device):
    """A guided intake, which is the flow that offers the inspection step."""
    return service.intake(customer, device, 'Fault', guided=True, initial_estimate=0,
                          accessories=[dict(type='accessory', description='Charger', quantity=1)])


def assign(service, job, technician_id):
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Checked'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'None'})
    life.execute(job, 'select_route', {'route': 'in_house', 'confirmed': True,
                                       'technician_id': technician_id})


def diagnosed(service, job, technician_id):
    """Assigned and diagnosed, which is the point a quotation may be issued."""
    assign(service, job, technician_id)
    life = Lifecycle(service)
    if 'hand_technician' in life.snapshot(job)['actions']:
        life.execute(job, 'hand_technician', dict(bench='Bench 1', condition='Intact',
                                                  acknowledgment='Technician received'))
    life.execute(job, 'diagnose', dict(notes='Fault confirmed', repairable=True))


def test_technician_cannot_open_the_complete_customer_export(service, customer):
    staff(service, 'amit', 'technician')
    service.login('amit', 'TestPassword123')
    with pytest.raises(RuleError, match='customer export'):
        CustomerRecords(service).sync_customer(customer)


def test_counter_customer_sales_projection_never_contains_internal_cost(service, customer):
    service.save_sale(customer, 'Sold Laptop', amount=5000000, cost=4200000,
                      provider='SECRET SUPPLIER')
    staff(service, 'sneha', 'counter')
    service.login('sneha', 'TestPassword123')
    rows = Queries(service).customer_sales(customer)
    assert rows and 'cost' not in rows[0] and 'provider' not in rows[0]


def test_customer_quotes_are_scoped_to_the_logged_in_technician(service, customer):
    amit, ravi = staff(service, 'amit', 'technician'), staff(service, 'ravi', 'technician')
    one = received(service, customer, 'Laptop')
    two = received(service, customer, 'Printer')
    diagnosed(service, one, amit)
    diagnosed(service, two, ravi)
    service.issue_quote(one, 'Laptop work', [{'description': 'Repair', 'amount': 1000}])
    service.issue_quote(two, 'Printer work', [{'description': 'Repair', 'amount': 2000}])
    service.login('amit', 'TestPassword123')
    assert {r['job_id'] for r in Queries(service).customer_quotes(customer)} == {one}


def test_job_card_auto_notification_uses_the_configured_event(service, customer):
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_job_card': True,
                      'auto_job_card': True})
    job = service.intake(customer, 'Laptop', 'Fault', initial_estimate=0,
                         operation_id=uuid.uuid4().hex)
    rows = service.db.rows("SELECT * FROM outbox WHERE event='job_card' AND job_id=?", (job,))
    assert len(rows) == 1
    assert rows[0]['attachment_id'], 'the generated job-card PDF is attached'


def test_job_card_and_invoice_use_their_own_paper_defaults(service, customer):
    service.settings({'paper_size': 'A4', 'paper_job_card': 'A5', 'paper_invoice': 'A5'})
    job = service.intake(customer, 'Laptop', 'Fault', initial_estimate=0,
                         operation_id=uuid.uuid4().hex)
    card = service.db.one("SELECT path FROM attachments WHERE job_id=? AND kind='issued_document' ORDER BY id DESC LIMIT 1", (job,))
    dims = {(round(float(w)), round(float(h))) for w, h in MEDIA_BOX.findall((service.db.root / card['path']).read_bytes())}
    assert (420, 595) in dims
    with service.db.transaction() as c:
        c.execute("UPDATE jobs SET stage='ready_unrepaired',outcome='Customer declined repair' WHERE id=?", (job,))
    invoice = Documents(service).generate('final_invoice', job)
    dims = {(round(float(w)), round(float(h))) for w, h in MEDIA_BOX.findall(invoice.read_bytes())}
    assert (420, 595) in dims


def test_manual_statement_cannot_be_queued_while_email_is_disabled(service):
    service.settings({'email_enabled': False})
    with pytest.raises(RuleError, match='Email is switched off'):
        service.queue_document(99999, 99999, 'Statement', 'Attached', uuid.uuid4().hex)
    assert service.db.rows("SELECT * FROM outbox WHERE event='statement'") == []


def test_warranty_history_for_another_technicians_device_is_denied(service, customer):
    amit, ravi = staff(service, 'amit', 'technician'), staff(service, 'ravi', 'technician')
    one = received(service, customer, 'Laptop')
    two = received(service, customer, 'Printer')
    assign(service, one, amit)
    assign(service, two, ravi)
    device_two = service.job(two)['device_id']
    service.login('amit', 'TestPassword123')
    with pytest.raises(RuleError, match='not assigned to you'):
        Warranties(service).rows(device_two)
