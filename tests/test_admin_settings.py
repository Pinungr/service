"""Settings the owner configures once, and the workflow then follows automatically.

The rule these tests protect: a global setting says what the shop *wants* to do. Whether
the customer can actually be reached, and whether they consented, is decided per customer
and is never overridden by a setting.
"""
import re
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop import app_settings
from repairshop.customer_records import CustomerRecords
from repairshop.documents import Documents
from repairshop.domain import RuleError

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')
MEDIA_BOX = re.compile(rb'/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*\]')


def sizes(path):
    return {(round(float(w)), round(float(h))) for w, h in MEDIA_BOX.findall(path.read_bytes())}


def customer_of(service, phone='9990011001', **consent):
    ident = service.save_customer('Settings Owner', phone, 'owner@example.invalid',
                                  **dict(ADDRESS, **consent))
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    return ident


def receipt_of(service, job):
    Documents(service).visit_receipt([job])
    return service.db.one("SELECT id FROM attachments WHERE kind='issued_document' ORDER BY id DESC")['id']


def intake_for(service, customer):
    return service.intake(customer, 'Dell Laptop', 'No power', initial_estimate=250000,
                          operation_id=uuid.uuid4().hex)


def outcomes(service, job, customer, event='intake_receipt'):
    return {r['channel']: r['state'] for r in service.auto_notify(
        event, receipt_of(service, job), customer, 'Hello', uuid.uuid4().hex, job_id=job)}


# ---- 31. documents follow the configured paper size --------------------------

def test_a_new_shop_defaults_to_a4(service, customer):
    job = intake_for(service, customer)
    assert app_settings.value(service.db, 'paper_size') == 'A4'
    assert sizes(Documents(service).visit_receipt([job])) == {(595, 842)}


def test_changing_the_default_paper_changes_the_next_receipt(service, customer):
    job = intake_for(service, customer)
    service.settings({'paper_size': 'A5'})
    assert sizes(Documents(service).visit_receipt([job])) == {(420, 595)}
    service.settings({'paper_size': 'A4'})
    assert sizes(Documents(service).visit_receipt([job])) == {(595, 842)}


def test_a_document_kind_can_have_its_own_paper_size(service, customer):
    job = intake_for(service, customer)
    service.settings({'paper_size': 'A5', 'paper_intake_receipt': 'A4'})
    docs = Documents(service)
    assert sizes(docs.visit_receipt([job])) == {(595, 842)}, 'the receipt uses its own size'
    assert docs.paper(document='job_card') == 'A5', 'others still use the shop default'
    service.settings({'paper_intake_receipt': ''})
    assert sizes(docs.visit_receipt([job])) == {(420, 595)}, 'blank falls back to the default'


def test_an_unsupported_paper_size_is_refused(service):
    with pytest.raises(RuleError, match='A4, A5'):
        service.settings({'paper_size': 'Letter'})


# ---- 31. notifications follow the configured events --------------------------

def test_nothing_is_sent_until_the_owner_enables_it(service):
    customer = customer_of(service, whatsapp_consent=True, email_consent=True)
    job = intake_for(service, customer)
    assert outcomes(service, job, customer) == {}, 'a new shop sends nothing automatically'
    assert not service.db.rows("SELECT 1 FROM outbox WHERE event='intake_receipt'")


def test_enabling_the_intake_receipt_queues_it_on_the_configured_channels(service):
    customer = customer_of(service, whatsapp_consent=True, email_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_intake_receipt': True,
                      'email_enabled': True, 'auto_email_intake_receipt': True})
    job = intake_for(service, customer)
    assert outcomes(service, job, customer) == {'whatsapp': 'pending', 'email': 'pending'}


def test_disabling_the_event_stops_the_next_one(service):
    customer = customer_of(service, whatsapp_consent=True, email_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_intake_receipt': True})
    first = intake_for(service, customer)
    assert outcomes(service, first, customer) == {'whatsapp': 'pending'}
    service.settings({'auto_whatsapp_intake_receipt': False})
    second = intake_for(service, customer)
    assert outcomes(service, second, customer) == {}


def test_turning_the_channel_off_disables_all_of_its_events(service):
    customer = customer_of(service, whatsapp_consent=True, email_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_intake_receipt': True,
                      'email_enabled': False, 'auto_email_intake_receipt': True})
    job = intake_for(service, customer)
    assert outcomes(service, job, customer) == {'whatsapp': 'pending'}, 'email stays off'


def test_each_event_is_configured_separately(service):
    customer = customer_of(service, whatsapp_consent=True, email_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_invoice': True})
    job = intake_for(service, customer)
    assert outcomes(service, job, customer, 'intake_receipt') == {}
    assert outcomes(service, job, customer, 'invoice') == {'whatsapp': 'pending'}


def test_the_pdf_is_attached_only_when_configured(service):
    customer = customer_of(service, whatsapp_consent=True, email_consent=True)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_intake_receipt': True,
                      'whatsapp_attach_pdf': False})
    job = intake_for(service, customer)
    outcomes(service, job, customer)
    assert service.db.one("SELECT attachment_id FROM outbox WHERE channel='whatsapp' AND event='intake_receipt'")['attachment_id'] is None
    service.settings({'whatsapp_attach_pdf': True})
    other = intake_for(service, customer)
    outcomes(service, other, customer)
    assert service.db.one("SELECT attachment_id FROM outbox WHERE channel='whatsapp' AND event='intake_receipt' ORDER BY id DESC")['attachment_id']


# ---- 32. a global setting never overrides customer consent -------------------

def test_a_customer_without_consent_is_blocked_however_the_shop_is_configured(service):
    customer = customer_of(service, whatsapp_consent=False, email_consent=False)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_intake_receipt': True,
                      'email_enabled': True, 'auto_email_intake_receipt': True})
    job = intake_for(service, customer)
    assert outcomes(service, job, customer) == {'whatsapp': 'blocked_consent', 'email': 'blocked_consent'}
    assert {r['state'] for r in service.db.rows("SELECT state FROM outbox WHERE event='intake_receipt'")} == {'blocked_consent'}


def test_consent_is_per_customer_not_per_shop(service):
    willing = customer_of(service, '9990011002', whatsapp_consent=True)
    unwilling = customer_of(service, '9990011003', whatsapp_consent=False)
    service.settings({'whatsapp_enabled': True, 'auto_whatsapp_intake_receipt': True})
    assert outcomes(service, intake_for(service, willing), willing) == {'whatsapp': 'pending'}
    assert outcomes(service, intake_for(service, unwilling), unwilling) == {'whatsapp': 'blocked_consent'}


def test_a_customer_with_no_contact_details_is_reported_as_skipped(service):
    ident = service.save_customer('No Contact', '9990011004', whatsapp_consent=True, **ADDRESS)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    service.settings({'email_enabled': True, 'auto_email_intake_receipt': True})
    job = intake_for(service, ident)
    assert outcomes(service, job, ident) == {'email': 'no_contact'}


# ---- 9. only the owner may change the defaults -------------------------------

def test_staff_and_technicians_cannot_change_the_shop_defaults(service):
    for username, role in (('front', 'counter'), ('amit', 'technician')):
        service.save_staff(username, username.title(), role, 'TestPassword123')
        service.login(username, 'TestPassword123')
        with pytest.raises(RuleError, match='settings'):
            service.settings({'paper_size': 'A5'})
        service.login('owner', 'CorrectHorse123!')
    assert app_settings.value(service.db, 'paper_size') == 'A4', 'nothing was changed'


def test_staff_still_read_the_defaults_through_normal_work(service, customer):
    service.settings({'paper_size': 'A5'})
    service.save_staff('front', 'Front', 'counter', 'TestPassword123')
    service.login('front', 'TestPassword123')
    job = intake_for(service, customer)
    assert sizes(Documents(service).visit_receipt([job])) == {(420, 595)}


# ---- 10. a missing key never breaks an existing installation -----------------

def test_an_installation_without_the_new_keys_gets_the_defaults(service):
    with service.db.transaction() as c:
        c.execute('DELETE FROM settings')
    for key, setting in app_settings.SETTINGS.items():
        assert app_settings.value(service.db, key) == setting.default
    assert app_settings.channels_for(service.db, 'intake_receipt') == []


def test_a_corrupt_stored_value_falls_back_instead_of_crashing(service):
    import json
    with service.db.transaction() as c:
        c.execute("INSERT INTO settings(key,value) VALUES ('paper_size',?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps('Foolscap'),))
    assert app_settings.value(service.db, 'paper_size') == 'A4'
