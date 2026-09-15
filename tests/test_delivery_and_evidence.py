"""Regression tests for document delivery, paper size and photo-evidence integrity.

These pin behavior that was previously only promised: a WhatsApp message that said a
receipt was attached, a paper-size choice that did not reach the renderer, and photo
evidence accepted merely because it belonged to the same customer.
"""
import pathlib
import re
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.documents import Documents
from repairshop.domain import RuleError

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
    """The payload the receive dialog builds, including its shared custody fields."""
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    return dict(dict(counterparty='Priya at the counter', condition='Intact', acknowledgment='R1',
                     storage='shop:Front desk', notes='', repair_result='REPAIRED',
                     items=list(held), quantities={str(k): v for k, v in held.items()},
                     discrepancies=[], operation_id=uuid.uuid4().hex,
                     received_by='Priya at the counter'), **extra)


def test_a_named_person_can_take_the_return_at_the_counter(service, customer):
    """The receive dialog offers "A named person"; the name comes from the shared
    "Person receiving the items" field, which custody already requires."""
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    life.execute(job, 'receive', receive_payload(life, job, receiver_kind='person',
                                                 receiver_mobile='9990003333'))
    record = Returns(service).verifications(job)[0]
    assert record['receiver_kind'] == 'person'
    assert record['receiver_name'] == 'Priya at the counter'
    assert record['receiver_mobile'] == '9990003333'
    assert record['complete']


def test_shop_storage_remains_the_default_receiver(service, customer):
    from repairshop.returns import Returns
    job, life = dispatched_job(service, customer)
    life.execute(job, 'receive', receive_payload(life, job, receiver_kind='storage'))
    record = Returns(service).verifications(job)[0]
    assert record['receiver_kind'] == 'storage' and record['storage'] == 'shop:Front desk'


def test_a_receipt_without_the_receiving_person_is_refused(service, customer):
    job, life = dispatched_job(service, customer)
    payload = receive_payload(life, job, receiver_kind='person')
    payload['counterparty'] = payload['received_by'] = ''
    with pytest.raises(RuleError, match='receiving person'):
        life.execute(job, 'receive', payload)
