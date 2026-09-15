import pytest
from PyQt6.QtGui import QColor, QImage

from repairshop.customer_registration import CustomerRegistration
from repairshop.domain import RuleError
from repairshop.local_files import managed_path


def registration(qtbot, service, **kwargs):
    dialog = CustomerRegistration(service, **kwargs)
    qtbot.addWidget(dialog)
    dialog.fields['name'].setText('New Customer')
    dialog.fields['phone_number'].setText('9990000008')
    fill_address(dialog)
    return dialog


def fill_address(dialog, line1='12 Test Street', pincode='411001', district='Pune', state='Maharashtra'):
    dialog.fields['address_line1'].setText(line1)
    dialog.fields['pincode'].setText(pincode)
    dialog.state.setCurrentText(state)
    dialog.district.setCurrentText(district)


def test_registration_required_inline_errors_and_optional_contacts(qtbot, service):
    dialog = CustomerRegistration(service)
    qtbot.addWidget(dialog)
    dialog.save()
    assert dialog.saved_id is None
    assert dialog.field_errors['phone_number'].text() == 'Phone number is required.'
    assert dialog.field_errors['address_line1'].text() == 'Address Line 1 is required.'
    dialog.fields['name'].setText('New Customer')
    dialog.fields['phone_number'].setText('abc')
    fill_address(dialog)
    dialog.save()
    assert 'valid phone' in dialog.field_errors['phone_number'].text()
    dialog.fields['phone_number'].setText('9990000008')
    dialog.fields['email'].setText('broken-email')
    dialog.save()
    assert 'valid email' in dialog.field_errors['email'].text()
    dialog.fields['email'].clear()
    dialog.save()
    saved = service.db.one('SELECT * FROM customers WHERE id=?', (dialog.saved_id,))
    assert saved['phone'] == '+919990000008'
    assert saved['email'] == '' and saved['alternate'] == ''


def test_duplicate_requires_explicit_decision_and_can_use_existing(qtbot, service, customer):
    dialog = registration(qtbot, service)
    dialog.fields['phone_number'].setText('9990000001')
    dialog.save()
    assert dialog.saved_id is None
    assert not dialog.duplicates.isHidden()
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 1
    dialog.use_existing()
    assert dialog.saved_id == customer
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 1


def test_duplicate_confirmation_is_phone_specific_and_shared_numbers_allowed(qtbot, service, customer):
    dialog = registration(qtbot, service)
    dialog.fields['phone_number'].setText('9990000001')
    dialog.save()
    dialog.confirm_duplicate()
    dialog.fields['phone_number'].setText('9990000002')
    dialog.fields['phone_number'].setText('9990000001')
    dialog.save()
    assert dialog.saved_id is None
    dialog.confirm_duplicate()
    dialog.save()
    assert dialog.saved_id != customer
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 2


def test_upload_preview_persists_owner_photo_and_edit_preserves_it(qtbot, service, tmp_path):
    source = tmp_path / 'person.png'
    image = QImage(80, 60, QImage.Format.Format_RGB32)
    image.fill(QColor('#537b92'))
    assert image.save(str(source))
    dialog = registration(qtbot, service)
    dialog.load_photo(source)
    assert not dialog.preview.pixmap().isNull()
    dialog.fields['alternate'].setText('9990000099')
    dialog.fields['whatsapp_consent'].setChecked(True)
    dialog.save()
    row = service.db.one('SELECT * FROM customers WHERE id=?', (dialog.saved_id,))
    photo = service.db.one('SELECT * FROM attachments WHERE id=?', (row['current_photo_id'],))
    assert photo['person_role'] == 'owner'
    assert managed_path(service.db.root, photo['path']).is_file()
    edit = CustomerRegistration(service, row=row)
    qtbot.addWidget(edit)
    assert not edit.preview.pixmap().isNull()
    edit.fields['name'].setText('Updated Customer')
    edit.save()
    edited = service.db.one('SELECT * FROM customers WHERE id=?', (edit.saved_id,))
    assert edited['current_photo_id'] == photo['id']
    assert edited['alternate'] == '9990000099' and edited['whatsapp_consent'] == 1
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 1


def test_photo_save_failure_retry_reuses_created_customer(qtbot, service, monkeypatch):
    dialog = registration(qtbot, service)
    image = QImage(40, 40, QImage.Format.Format_RGB32)
    image.fill(QColor('#537b92'))
    dialog.set_photo(image)
    real_save = dialog.records.save_photo
    monkeypatch.setattr(dialog.records, 'save_photo', lambda *a, **kw: (_ for _ in ()).throw(OSError('Disk full')))
    dialog.save()
    ident = dialog.customer_id
    assert ident and dialog.saved_id is None
    assert 'Customer details were saved' in dialog.error.text()
    assert dialog.pending_image is not None
    monkeypatch.setattr(dialog.records, 'save_photo', real_save)
    dialog.save()
    assert dialog.saved_id == ident
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 1
    assert service.db.one('SELECT current_photo_id FROM customers WHERE id=?', (ident,))['current_photo_id']


def test_bad_upload_does_not_create_customer(qtbot, service, tmp_path):
    source = tmp_path / 'bad.png'
    source.write_text('not an image')
    dialog = registration(qtbot, service)
    with pytest.raises(RuleError, match='supported photo'):
        dialog.load_photo(source)
    assert dialog.pending_image is None
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 0


def test_camera_photo_is_staged_until_customer_save(qtbot, service, monkeypatch):
    image = QImage(40, 40, QImage.Format.Format_RGB32)
    image.fill(QColor('#537b92'))

    class CapturedCamera:
        def __init__(self, callback, parent):
            self.photo_id = callback(image, '2026-09-13T09:00:00+00:00')

        def exec(self):
            return True

    monkeypatch.setattr('repairshop.customer_registration.CameraDialog', CapturedCamera)
    dialog = registration(qtbot, service)
    dialog.capture()
    assert dialog.pending_image is not None
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 0
    dialog.save()
    photo = service.db.one('SELECT * FROM attachments WHERE customer_id=?', (dialog.saved_id,))
    assert photo['captured'] == '2026-09-13T09:00:00+00:00'


def test_cancel_registration_does_not_publish_staged_photo(qtbot, service):
    dialog = registration(qtbot, service)
    image = QImage(40, 40, QImage.Format.Format_RGB32)
    image.fill(QColor('#537b92'))
    dialog.set_photo(image)
    dialog.reject()
    assert dialog.saved_id is None
    assert service.db.one('SELECT count(*) AS n FROM customers')['n'] == 0
    assert service.db.one('SELECT count(*) AS n FROM attachments')['n'] == 0
