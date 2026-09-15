"""Regression tests for document delivery, paper size and photo-evidence integrity.

These pin behavior that was previously only promised: a WhatsApp message that said a
receipt was attached, a paper-size choice that did not reach the renderer, and photo
evidence accepted merely because it belonged to the same customer.
"""
import json
import pathlib
import re
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.documents import Documents
from repairshop.domain import RuleError
from repairshop.lifecycle import Lifecycle

ADDRESS = dict(address_line1='12 Station Road', address_line2='Near the clock tower',
               pincode='411001', district='Pune', state='Maharashtra')
MEDIA_BOX = re.compile(rb'/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]')


def pages(path):
    """Every page's (width, height) in points, read straight from the PDF."""
    return [(round(float(w)), round(float(h))) for _, _, w, h in MEDIA_BOX.findall(path.read_bytes())]


def photo(service, customer, colour='#68a398'):
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    return CustomerRecords(service).save_photo(image, customer)


def accessory_photo(service, customer, name='Charger'):
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#445566'))
    return CustomerRecords(service).save_photo(image, customer, 'accessory', name)


def receipt(service, job):
    Documents(service).visit_receipt([job])
    return service.db.one("SELECT id FROM attachments WHERE kind='issued_document' ORDER BY id DESC")['id']


# ---- P1-1. WhatsApp actually carries the PDF the message promises ------------

class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code, self._body = status_code, body if body is not None else {}

    def json(self):
        return self._body


def adapter(monkeypatch, calls, upload=None):
    from repairshop import messaging
    monkeypatch.setattr(messaging, 'secret', lambda name, value=None: 'test-token')

    def post(url, **kwargs):
        calls.append(dict(url=url, **kwargs))
        if url.endswith('/media'):
            return upload if upload is not None else FakeResponse(200, {'id': 'MEDIA-1'})
        return FakeResponse(200, {'messages': [{'id': 'WAMID-1'}]})

    monkeypatch.setattr(messaging.httpx, 'post', post)
    return messaging.WhatsApp({'phone_number_id': '123', 'api_version': 'v20.0'})


def payload(tmp_path):
    pdf = tmp_path / 'intake-receipt.pdf'
    pdf.write_bytes(b'%PDF-1.4 receipt')
    return {'body': 'Your device has been received.', 'template': {'name': 'intake', 'language': 'en'},
            '_attachment_path': str(pdf), '_attachment_name': pdf.name}


def test_whatsapp_uploads_the_pdf_and_sends_it_with_the_message(monkeypatch, tmp_path):
    """The message claimed a receipt was attached while the adapter sent text only."""
    calls = []
    assert adapter(monkeypatch, calls).send({'destination': '+919990000001'}, payload(tmp_path)) == 'WAMID-1'
    assert len(calls) == 2, 'the document must be uploaded before the message is sent'
    assert calls[0]['url'].endswith('/media')
    assert calls[0]['data']['messaging_product'] == 'whatsapp'
    assert calls[0]['files']['file'][0] == 'intake-receipt.pdf'
    header = calls[1]['json']['template']['components'][0]
    assert header['type'] == 'header'
    assert header['parameters'][0]['document'] == {'id': 'MEDIA-1', 'filename': 'intake-receipt.pdf'}
    assert calls[1]['json']['template']['components'][1]['parameters'][0]['text'].startswith('Your device')


def test_a_message_without_an_attachment_is_completely_unchanged(monkeypatch):
    calls = []
    adapter(monkeypatch, calls).send({'destination': '+919990000001'},
                                     {'body': 'Ready for collection.', 'template': {'name': 'ready', 'language': 'en'}})
    assert len(calls) == 1 and not calls[0]['url'].endswith('/media')
    assert [c['type'] for c in calls[0]['json']['template']['components']] == ['body']


def test_whatsapp_photo_uses_an_image_header(monkeypatch, tmp_path):
    calls = []
    image = tmp_path / 'repair.jpg'
    image.write_bytes(b'\xff\xd8\xff\xe0photo')
    body = {'body': 'Repair photo', 'template': {'name': 'repair_photo', 'language': 'en'},
            '_attachment_path': str(image), '_attachment_name': image.name,
            '_attachment_media': 'image'}
    assert adapter(monkeypatch, calls).send({'destination': '+919990000001'}, body) == 'WAMID-1'
    assert calls[0]['files']['file'][2] == 'image/jpeg'
    header = calls[1]['json']['template']['components'][0]
    assert header['parameters'][0] == {'type': 'image', 'image': {'id': 'MEDIA-1'}}


def test_a_rejected_upload_never_reports_a_delivered_message(monkeypatch, tmp_path):
    from repairshop.messaging import Permanent
    calls = []
    with pytest.raises(Permanent):
        adapter(monkeypatch, calls, upload=FakeResponse(400)).send({'destination': '+919990000001'}, payload(tmp_path))
    assert len(calls) == 1, 'no message may be sent after the document failed to upload'


def test_a_provider_outage_during_upload_is_retryable_because_nothing_was_sent(monkeypatch, tmp_path):
    from repairshop.messaging import Retryable
    calls = []
    with pytest.raises(Retryable):
        adapter(monkeypatch, calls, upload=FakeResponse(500)).send({'destination': '+919990000001'}, payload(tmp_path))
    assert len(calls) == 1


def test_an_interrupted_send_stays_uncertain_so_it_is_not_blindly_resent(monkeypatch, tmp_path):
    from repairshop import messaging
    monkeypatch.setattr(messaging, 'secret', lambda name, value=None: 'test-token')

    def post(url, **kwargs):
        if url.endswith('/media'):
            return FakeResponse(200, {'id': 'MEDIA-1'})
        raise messaging.httpx.TimeoutException('timeout')

    monkeypatch.setattr(messaging.httpx, 'post', post)
    with pytest.raises(messaging.Uncertain):
        messaging.WhatsApp({'phone_number_id': '123', 'api_version': 'v20.0'}).send(
            {'destination': '+919990000001'}, payload(tmp_path))


def test_a_missing_file_is_a_permanent_failure_rather_than_a_silent_text_message(monkeypatch, tmp_path):
    from repairshop.messaging import Permanent
    calls = []
    body = dict(payload(tmp_path), _attachment_path=str(tmp_path / 'gone.pdf'))
    with pytest.raises(Permanent):
        adapter(monkeypatch, calls).send({'destination': '+919990000001'}, body)
    assert calls == []


def test_the_queued_receipt_reaches_the_adapter_as_a_real_pdf(service, customer):
    from repairshop.messaging import Outbox
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    service.queue_customer_document(receipt(service, job), customer, ['whatsapp'], 'intake_receipt',
                                    'Hi', uuid.uuid4().hex, job_id=job)
    seen = {}

    class Recorder:
        def send(self, row, body):
            seen.update(body)
            return 'PROVIDER-1'

    worker = Outbox(service)
    worker.adapters = {'whatsapp': Recorder()}
    while worker.process_one():
        pass
    assert pathlib.Path(seen['_attachment_path']).is_file()
    assert seen['_attachment_path'].endswith('.pdf')
    assert seen['_attachment_name'].endswith('.pdf')
    assert service.db.one('SELECT state FROM outbox ORDER BY id DESC')['state'] == 'accepted'


def test_include_photos_attaches_only_this_jobs_customer_facing_photos_to_email(service, customer):
    from repairshop.messaging import Outbox
    evidence = accessory_photo(service, customer, 'Charger')
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                         accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=evidence)])
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#778899'))
    product = CustomerRecords(service).save_photo(image, customer, 'product',
        device_id=service.job(job)['device_id'], job_id=job)
    # This is a customer portrait and must never be sent by Include photos.
    portrait = photo(service, customer, '#101010')
    service.settings({'include_photos': True})
    service.queue_customer_document(receipt(service, job), customer, ['email'], 'intake_receipt',
                                    'Hi', uuid.uuid4().hex, job_id=job)
    seen = {}
    class Recorder:
        def send(self, row, body):
            seen.update(body)
            return 'MAIL-1'
    worker = Outbox(service, {'email': Recorder()})
    while worker.process_one():
        pass
    titles = {p['title'] for p in seen['_photo_paths']}
    assert len(seen['_photo_paths']) == 2
    assert any('Charger' in title for title in titles)
    assert product in {r['id'] for r in service.db.rows("SELECT id FROM attachments WHERE job_id=?", (job,))}
    assert portrait not in json.loads(service.db.one("SELECT payload FROM outbox WHERE channel='email'")['payload']).get('photo_attachment_ids', [])


def test_include_photos_queues_separate_tracked_whatsapp_photo_messages(service, customer):
    evidence = accessory_photo(service, customer, 'Charger')
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                         accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=evidence)])
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#223344'))
    product = CustomerRecords(service).save_photo(image, customer, 'product',
        device_id=service.job(job)['device_id'], job_id=job)
    service.settings({'include_photos': True,
                      'whatsapp': {'photo_template': 'repair_photo', 'photo_language': 'en'}})
    result = service.queue_customer_document(receipt(service, job), customer, ['whatsapp'], 'intake_receipt',
                                             'Hi', 'photo-op', job_id=job)[0]
    assert result['photos_queued'] == 2
    # Scoped to this event: intake also queues its own 'received' message, which is not
    # what this test is about.
    rows = service.db.rows("""SELECT attachment_id,payload FROM outbox
        WHERE channel='whatsapp' AND event='intake_receipt' ORDER BY id""")
    assert len(rows) == 3  # one receipt + two independently tracked photos
    photo_rows = [r for r in rows if json.loads(r['payload']).get('_attachment_media') == 'image']
    assert {r['attachment_id'] for r in photo_rows} == {evidence, product}
    assert all(json.loads(r['payload'])['template']['name'] == 'repair_photo' for r in photo_rows)


def test_switching_include_photos_off_cancels_queued_whatsapp_photos(service, customer):
    from repairshop.messaging import Outbox
    evidence = accessory_photo(service, customer, 'Charger')
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                         accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=evidence)])
    service.settings({'include_photos': True,
                      'whatsapp': {'photo_template': 'repair_photo', 'photo_language': 'en'}})
    service.queue_customer_document(receipt(service, job), customer, ['whatsapp'], 'intake_receipt',
                                    'Hi', 'photo-off-op', job_id=job)
    service.settings({'include_photos': False})
    class Recorder:
        def send(self, row, body):
            return 'OK'
    worker = Outbox(service, {'whatsapp': Recorder()})
    while worker.process_one():
        pass
    states = service.db.rows("SELECT payload,state FROM outbox WHERE channel='whatsapp' ORDER BY id")
    assert any(json.loads(r['payload']).get('_attachment_media') == 'image' and r['state'] == 'cancelled' for r in states)


def test_a_successful_send_is_never_duplicated_by_a_second_pass(service, customer):
    from repairshop.messaging import Outbox
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    attachment, operation = receipt(service, job), uuid.uuid4().hex
    sends = []

    class Recorder:
        def send(self, row, body):
            if body.get('_attachment_path'):
                sends.append(row['id'])
            return 'PROVIDER-1'

    worker = Outbox(service)
    worker.adapters = {'whatsapp': Recorder()}
    for _ in range(2):
        service.queue_customer_document(attachment, customer, ['whatsapp'], 'intake_receipt',
                                        'Hi', operation, job_id=job)
        while worker.process_one():
            pass
    assert len(sends) == 1, 'requeuing the same operation must not send the document twice'


# ---- P1-2. A4 and A5 are genuinely different pages ---------------------------

def test_a4_and_a5_receipts_are_rendered_at_their_real_page_sizes(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', initial_estimate=500000,
                         operation_id=uuid.uuid4().hex)
    docs = Documents(service)
    assert set(pages(docs.visit_receipt([job], paper='A4'))) == {(595, 842)}
    assert set(pages(docs.visit_receipt([job], paper='A5'))) == {(420, 595)}


def test_a_job_card_honours_the_requested_paper_size(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    docs = Documents(service)
    assert set(pages(docs.generate('intake_receipt', job, paper='A5'))) == {(420, 595)}
    assert set(pages(docs.generate('intake_receipt', job, paper='A4'))) == {(595, 842)}


def test_the_saved_paper_setting_is_used_when_no_size_is_requested(service, customer):
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex)
    service.settings({'paper_size': 'A5'})
    assert set(pages(Documents(service).visit_receipt([job]))) == {(420, 595)}
    service.settings({'paper_size': 'A4'})
    assert set(pages(Documents(service).visit_receipt([job]))) == {(595, 842)}


def test_a5_reflows_the_content_instead_of_overflowing_the_smaller_sheet(service, customer):
    job = service.intake(
        customer, 'Dell Laptop', 'No display', initial_estimate=500000,
        customer_requirement='Please back up my documents before any repair work is started.',
        accessories=[dict(type='accessory', description='Original 65W charger', quantity=1),
                     dict(type='accessory', description='Carry bag with spare cable', quantity=1)],
        operation_id=uuid.uuid4().hex)
    docs = Documents(service)
    a5, a4 = docs.visit_receipt([job], paper='A5'), docs.visit_receipt([job], paper='A4')
    assert set(pages(a5)) == {(420, 595)}
    # Identical content on a smaller sheet needs at least as many pages: it is re-laid
    # out for the page rather than scaled or cropped.
    assert len(pages(a5)) >= len(pages(a4))


# ---- P1-7. photo evidence belongs to the record it documents -----------------

def test_an_unrelated_historical_photo_cannot_become_accessory_evidence(service, customer):
    stale = photo(service, customer, '#112233')
    with pytest.raises(RuleError, match='accessory photo'):
        service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                       accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=stale)])


def test_another_customers_photo_cannot_become_accessory_evidence(service, customer):
    other = service.save_customer('Other Owner', '9990000041', **ADDRESS)
    theirs = accessory_photo(service, other)
    with pytest.raises(RuleError, match='accessory photo'):
        service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                       accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=theirs)])


def test_one_accessory_photo_cannot_be_reused_across_two_repairs(service, customer):
    evidence = accessory_photo(service, customer)
    service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                   accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=evidence)])
    with pytest.raises(RuleError, match='another repair'):
        service.intake(customer, 'Samsung Mobile', 'No display', operation_id=uuid.uuid4().hex,
                       accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=evidence)])


def test_accessory_evidence_is_claimed_by_the_repair_that_used_it(service, customer):
    evidence = accessory_photo(service, customer)
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                         accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=evidence)])
    assert service.db.one('SELECT job_id FROM attachments WHERE id=?', (evidence,))['job_id'] == job


def test_existing_accessory_photos_are_still_accepted_for_their_own_repair(service, customer):
    """Tightening the rule must not invalidate evidence already recorded correctly."""
    evidence = accessory_photo(service, customer)
    job = service.intake(customer, 'Dell Laptop', 'No display', operation_id=uuid.uuid4().hex,
                         accessories=[dict(type='accessory', description='Charger', quantity=1, photo_id=evidence)])
    row = service.db.one("SELECT photo_id FROM items WHERE job_id=? AND description='Charger'", (job,))
    assert row['photo_id'] == evidence


def test_return_evidence_must_belong_to_the_repair_being_verified(service, customer):
    from repairshop.returns import Returns
    stale = photo(service, customer, '#998877')
    returns = Returns(service)
    assert returns._clean_discrepancies(
        [dict(item_id=None, kind='damaged', notes='Scratched lid')], {}, set())[0]['photo_id'] is None
    with pytest.raises(RuleError, match='return evidence'):
        returns._clean_discrepancies(
            [dict(item_id=None, kind='damaged', notes='Scratched lid', photo_id=stale)], {}, set())
    assert returns._clean_discrepancies(
        [dict(item_id=None, kind='damaged', notes='Scratched lid', photo_id=stale)], {}, {stale})[0]['photo_id'] == stale

def dispatched_job(service, customer):
    """A third-party repair that has come back and is ready to be received."""
    from repairshop.lifecycle import Lifecycle
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True,
                         accessories=[dict(type='accessory', description='Charger', quantity=1)])
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Fault confirmed'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'No cover'})
    vendor = service.save_master('vendor', 'ABC Repair', contact='9998887771', **ADDRESS)
    life.execute(job, 'select_route', {'route': 'third_party', 'confirmed': True, 'contact_id': vendor})
    life.execute(job, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(job)], consent=True,
                                               condition='Intact', expected_return='2099-01-01'))
    life.execute(job, 'dispatch', dict(counterparty='Courier', condition='Intact', acknowledgment='D1'))
    life.execute(job, 'diagnose', dict(notes='Board fault', repairable=True))
    quote = service.issue_quote(job, 'Board repair',
                                [{'description': 'Board', 'amount': 500000, 'kind': 'part'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    life.execute(job, 'start_repair')
    life.execute(job, 'complete_repair', dict(notes='Repaired', parts='Board'))
    return job, life


def receive_payload(life, job, **extra):
    """The payload the receive dialog builds. It never names a receiver: the signed-in
    user takes the product back, so there is nothing to choose."""
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    return dict(dict(counterparty='Vendor courier', condition='Intact', acknowledgment='R1',
                     notes='', repair_result='REPAIRED',
                     items=list(held), quantities={str(k): v for k, v in held.items()},
                     discrepancies=[], operation_id=uuid.uuid4().hex), **extra)


def test_a_third_party_return_is_received_by_the_signed_in_user(service, customer):
    from repairshop.domain import staff_custody
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    service.save_staff('rahul', 'Rahul', 'counter', 'TestPassword123')
    rahul = service.db.one("SELECT id FROM users WHERE username='rahul'")['id']
    service.login('rahul', 'TestPassword123')
    life = Lifecycle(service)
    life.execute(job, 'receive', receive_payload(life, job))
    record = Returns(service).verifications(job)[0]
    assert record['received_by_user_id'] == rahul
    assert record['complete']
    held = service.db.one("""SELECT h.location FROM holdings h JOIN items i ON i.id=h.item_id
        WHERE i.job_id=? AND i.type='device' AND h.quantity>0""", (job,))['location']
    assert held == staff_custody(rahul), 'the receiver becomes the custodian'


def test_no_shop_destination_is_ever_created_by_a_return(service, customer):
    job, life = dispatched_job(service, customer)
    life.execute(job, 'receive', receive_payload(life, job))
    assert not service.db.rows("SELECT 1 FROM movements WHERE to_location LIKE 'shop:%'")


def test_a_return_cannot_name_somebody_else_as_the_receiver(service, customer):
    """The API has no receiver argument, so forging one is a TypeError, not a silent write."""
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    with pytest.raises(TypeError):
        Returns(service).verify(job, held, uuid.uuid4().hex, receiver_name='Somebody Else')

# ---- 14/15. return evidence belongs to its return event ---------------------

def return_photo(service, customer, job, what='Cracked screen'):
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#aa3333'))
    return CustomerRecords(service).save_photo(image, customer, 'return', what, job_id=job)


def test_an_intake_photo_cannot_stand_in_as_return_evidence(service, customer):
    """JOB-100's own intake photo is not proof of what came back from the repairer."""
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    stale = accessory_photo(service, customer)
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    item = next(iter(held))
    with pytest.raises(RuleError, match='return evidence'):
        Returns(service).verify(job, {**held, item: 0}, uuid.uuid4().hex,
                                discrepancies=[dict(item_id=item, kind='missing',
                                                    notes='Not returned', photo_id=stale)])


def test_a_photo_taken_as_return_evidence_is_accepted_and_linked(service, customer):
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    evidence = return_photo(service, customer, job)
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    item = next(iter(held))
    verification = Returns(service).verify(job, {**held, item: 0}, uuid.uuid4().hex,
                                           discrepancies=[dict(item_id=item, kind='missing',
                                                               notes='Not returned', photo_id=evidence)])
    row = service.db.one('SELECT * FROM return_evidence WHERE attachment_id=?', (evidence,))
    assert row['verification_id'] == verification
    assert row['discrepancy_id'] == service.db.one(
        'SELECT id FROM return_discrepancies WHERE verification_id=?', (verification,))['id']


def test_evidence_cannot_be_reused_for_a_second_return_event(service, customer):
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    evidence = return_photo(service, customer, job)
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    item = next(iter(held))
    Returns(service).verify(job, {**held, item: 0}, uuid.uuid4().hex,
                            discrepancies=[dict(item_id=item, kind='missing',
                                                notes='Not returned', photo_id=evidence)])
    with pytest.raises(RuleError, match='return evidence'):
        Returns(service).verify(job, {**held, item: 0}, uuid.uuid4().hex,
                                discrepancies=[dict(item_id=item, kind='damaged',
                                                    notes='Reusing the same photo', photo_id=evidence)])


def test_another_repairs_return_photo_is_not_evidence_here(service, customer):
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    other = service.intake(customer, 'Other Laptop', 'Fault', operation_id=uuid.uuid4().hex)
    theirs = return_photo(service, customer, other)
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    item = next(iter(held))
    with pytest.raises(RuleError, match='return evidence'):
        Returns(service).verify(job, {**held, item: 0}, uuid.uuid4().hex,
                                discrepancies=[dict(item_id=item, kind='missing',
                                                    notes='Wrong repair', photo_id=theirs)])


def test_return_evidence_is_append_only(service, customer):
    import sqlite3
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    evidence = return_photo(service, customer, job)
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    item = next(iter(held))
    Returns(service).verify(job, {**held, item: 0}, uuid.uuid4().hex,
                            discrepancies=[dict(item_id=item, kind='missing',
                                                notes='Not returned', photo_id=evidence)])
    for statement in ('UPDATE return_evidence SET attachment_id=1', 'DELETE FROM return_evidence'):
        with pytest.raises(sqlite3.IntegrityError):
            with service.db.transaction() as c:
                c.execute(statement)
