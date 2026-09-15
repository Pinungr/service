"""Part 9: one configured shop, one working day, checked against the real stored result."""
import re
import uuid
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.documents import Documents
from repairshop.domain import staff_custody
from repairshop.lifecycle import Lifecycle
from repairshop.queries import Queries

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')
MEDIA_BOX = re.compile(rb'/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*\]')


def held(service, job):
    return service.db.one("""SELECT h.location FROM holdings h JOIN items i ON i.id=h.item_id
        WHERE i.job_id=? AND i.type='device' AND h.quantity>0""", (job,))['location']


def test_a_configured_shop_runs_a_whole_day_without_asking_twice(service, tmp_path):
    # --- the owner configures the shop once -------------------------------
    service.settings({'paper_size': 'A5', 'whatsapp_enabled': True, 'email_enabled': True,
                      'auto_whatsapp_intake_receipt': True, 'auto_email_intake_receipt': True,
                      'whatsapp_attach_pdf': True, 'email_attach_pdf': True})
    rahul = service.save_staff('rahul', 'Rahul', 'counter', 'TestPassword123') or \
        service.db.one("SELECT id FROM users WHERE username='rahul'")['id']
    amit = service.save_staff('amit', 'Amit', 'technician', 'TestPassword123') or \
        service.db.one("SELECT id FROM users WHERE username='amit'")['id']
    sneha = service.save_staff('sneha', 'Sneha', 'counter', 'TestPassword123') or \
        service.db.one("SELECT id FROM users WHERE username='sneha'")['id']
    customer = service.save_customer('Configured Owner', '9990013001', 'owner@example.invalid',
                                     whatsapp_consent=True, email_consent=True, **ADDRESS)
    image = QImage(32, 32, QImage.Format.Format_RGB32); image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, customer)

    # --- Rahul takes the product in --------------------------------------
    service.login('rahul', 'TestPassword123')
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True, initial_estimate=300000,
                         operation_id=uuid.uuid4().hex)
    assert service.job(job)['actor'] == rahul, 'received by Rahul'
    assert held(service, job) == staff_custody(rahul), 'and held by Rahul'
    assert not service.db.rows("SELECT 1 FROM movements WHERE to_location LIKE 'shop:%'")

    # --- the configured paper size is used without anyone choosing -------
    receipt = Documents(service).visit_receipt([job])
    assert {(round(float(w)), round(float(h))) for w, h in MEDIA_BOX.findall(receipt.read_bytes())} == {(420, 595)}
    attachment = service.db.one("SELECT id FROM attachments WHERE kind='issued_document' ORDER BY id DESC")['id']

    # --- the configured notifications are queued automatically -----------
    outcomes = {r['channel']: r['state'] for r in service.auto_notify(
        'intake_receipt', attachment, customer, 'Received', uuid.uuid4().hex, job_id=job)}
    assert outcomes == {'whatsapp': 'pending', 'email': 'pending'}
    assert all(r['attachment_id'] == attachment for r in
               service.db.rows("SELECT attachment_id FROM outbox WHERE event='intake_receipt'"))

    # --- records land on the right side of the wall ----------------------
    CustomerRecords(service).sync_customer(customer)
    assert list((service.db.root / 'Customers').rglob('customer-job-summary.txt'))
    assert list((service.db.root / 'Internal').rglob('internal-job-details.txt'))

    # --- assignment, then a real handover --------------------------------
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Power fault'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'None'})
    life.execute(job, 'select_route', {'route': 'in_house', 'confirmed': True, 'technician_id': amit})
    assert held(service, job) == staff_custody(rahul), 'assignment alone does not move it'
    life.execute(job, 'hand_technician', dict(bench='Bench 2', condition='Intact',
                                              acknowledgment='Amit signed'))
    assert held(service, job) == 'technician:' + str(amit)

    # --- Amit sees only his own counts -----------------------------------
    service.login('amit', 'TestPassword123')
    assert sum(r['jobs'] for r in Queries(service).dashboard()['stages']) == 1
    service.login('owner', 'CorrectHorse123!')
    everything = sum(r['jobs'] for r in Queries(service).dashboard()['stages'])
    assert everything >= 1

    # --- third-party return lands with whoever receives it ---------------
    service.login('sneha', 'TestPassword123')
    life = Lifecycle(service)
    life.execute(job, 'return_technician', dict(condition='Intact', acknowledgment='Back at counter'))
    assert held(service, job) == staff_custody(sneha), 'Sneha took it back, so Sneha holds it'
    assert not service.db.rows("SELECT 1 FROM holdings WHERE location LIKE 'shop:%'")
    assert not service.db.rows("SELECT 1 FROM movements WHERE to_location LIKE 'shop:%'")
