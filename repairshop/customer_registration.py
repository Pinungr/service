"""Customer registration with explicit duplicate decisions and local photo preview."""
from pathlib import Path
import re

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import QDialogButtonBox, QFileDialog, QLabel, QWidget, QVBoxLayout

from .camera import CameraDialog
from .customer_records import CustomerRecords
from .customer_ui import show_photo
from .domain import RuleError, now, phone
from .queries import Queries
from .ui_widgets import Form, FlowLayout, button, combo
from .intake_fields import INTAKE_STYLE


class CustomerRegistration(Form):
    def __init__(self, service, row=None, parent=None, initial=None):
        super().__init__('Customer registration' if not row else 'Customer details', parent,
                         'Required fields are marked *. Photos stay on this computer.')
        self.s = service
        self.setStyleSheet(INTAKE_STYLE)
        self.records = CustomerRecords(service)
        row = row or initial or {}
        self.customer_id = row.get('id')
        self.saved_id = None
        self.pending_image = None
        self.pending_captured = None
        self.confirmed_phone = None
        self.field_errors = {}
        self.resize(720, 850)
        self.section('Customer information')
        self._text('name', 'Full name *', row.get('name', ''))
        self.section('Contact information')
        self._text('phone_number', 'Phone / WhatsApp number *', row.get('phone', ''))
        self._text('alternate', 'Alternate phone number', row.get('alternate', ''))
        self._text('email', 'Email address', row.get('email', ''))
        self.check('whatsapp_consent', 'Agreed to WhatsApp updates', row.get('whatsapp_consent'))
        self.check('email_consent', 'Agreed to email updates', row.get('email_consent'))

        self.duplicates = QWidget()
        duplicates_layout = QVBoxLayout(self.duplicates)
        duplicates_layout.setContentsMargins(0, 0, 0, 0)
        self.duplicate_message = QLabel()
        self.duplicate_message.setWordWrap(True)
        self.duplicate_message.setTextFormat(Qt.TextFormat.PlainText)
        duplicates_layout.addWidget(self.duplicate_message)
        self.matches = combo([])
        duplicates_layout.addWidget(self.matches)
        choices = FlowLayout()
        self.use_existing_button = button('Use existing customer', self.use_existing)
        self.continue_button = button('Continue creating new customer', self.confirm_duplicate)
        choices.addWidget(self.use_existing_button)
        choices.addWidget(self.continue_button)
        duplicates_layout.addLayout(choices)
        self.layout.addRow(self.duplicates)
        self.duplicates.hide()
        self.fields['phone_number'].textChanged.connect(self.phone_changed)
        self.fields['phone_number'].editingFinished.connect(self.check_duplicates)

        self.section('Customer photo')
        photo_box = QWidget()
        photo_layout = QVBoxLayout(photo_box)
        photo_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel('No photo selected')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(105)
        photo_layout.addWidget(self.preview)
        controls = FlowLayout()
        controls.addWidget(button('Capture using camera', self.capture))
        controls.addWidget(button('Upload photo', self.upload))
        photo_layout.addLayout(controls)
        hint = QLabel('Optional here. A saved customer or submitting-person photo is required to create a repair job.')
        hint.setWordWrap(True)
        hint.setObjectName('subtitle')
        photo_layout.addWidget(hint)
        self.layout.addRow(photo_box)
        if row.get('current_photo_id'):
            photo = service.db.one('SELECT * FROM attachments WHERE id=?', (row['current_photo_id'],))
            show_photo(self.preview, service.db, photo, 150)

        self.section('Address')
        self._text('address', 'Address *', row.get('address', ''), multiline=True)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('Save customer')
        self.buttons.accepted.connect(self.save)

    def _text(self, key, label, value, multiline=False):
        widget = self.text(key, label, value, multiline=multiline)
        error = QLabel()
        error.setObjectName('errorBadge')
        error.setWordWrap(True)
        error.hide()
        self.field_errors[key] = error
        self.layout.addRow('', error)
        widget.installEventFilter(self)
        widget.textChanged.connect(lambda: self.validate_field(key) if not error.isHidden() else None)
        return widget

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusOut:
            key = next((key for key, widget in self.fields.items() if widget is watched), None)
            if key in self.field_errors:
                self.validate_field(key)
        return super().eventFilter(watched, event)

    def validate_field(self, key):
        value = self.values()[key]
        message = ''
        if key in ('name', 'phone_number', 'address') and not value:
            message = {'name': 'Full name is required.', 'phone_number': 'Phone number is required.',
                       'address': 'Address is required.'}[key]
        elif key == 'phone_number':
            try:
                if not phone(value):
                    raise RuleError('Enter a valid phone number.')
            except RuleError:
                message = 'Enter a valid phone number, including the country code when needed.'
        elif key == 'email' and value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            message = 'Enter a valid email address, for example name@example.com.'
        # Existing alternate contacts may contain several numbers or notes; retain them verbatim.
        error = self.field_errors[key]
        error.setText(message)
        error.setVisible(bool(message))
        return not message

    def phone_changed(self):
        self.confirmed_phone = None
        self.duplicates.hide()

    def check_duplicates(self):
        try:
            normalized = phone(self.fields['phone_number'].text())
        except RuleError:
            return False
        if not normalized:
            return False
        matches, offset = [], 0
        while True:
            page = Queries(self.s).customers(normalized, offset=offset)
            matches.extend(row for row in page if row['phone'] == normalized and row['id'] != self.customer_id)
            if len(page) < 50:
                break
            offset += 50
        self.matches.clear()
        for row in matches:
            self.matches.addItem(f"{row['name']} · {row['phone']} · {row['address'] or 'No address recorded'}", row['id'])
        unconfirmed = bool(matches) and normalized != self.confirmed_phone
        self.duplicate_message.setText('An existing customer with this phone number was found. Use their record, or confirm that this is a different person sharing the number.')
        self.duplicates.setVisible(unconfirmed)
        return unconfirmed

    def confirm_duplicate(self):
        self.confirmed_phone = phone(self.fields['phone_number'].text())
        self.duplicates.hide()
        self.error.hide()

    def use_existing(self):
        if self.matches.currentData():
            self.saved_id = self.matches.currentData()
            self.accept()

    def set_photo(self, image, captured=None):
        if not isinstance(image, QImage) or image.isNull():
            raise RuleError('Choose a supported photo that can be opened.')
        self.pending_image = image.copy()
        self.pending_captured = captured or now()
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(200, 130, Qt.AspectRatioMode.KeepAspectRatio,
                                                            Qt.TransformationMode.SmoothTransformation))
        self.error.hide()

    def capture(self):
        # The camera's worker only copies image data; all UI and persistence stay here.
        dialog = CameraDialog(lambda image, captured: (image.copy(), captured), self)
        if dialog.exec() and dialog.photo_id:
            self.set_photo(*dialog.photo_id)

    def upload(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose customer photo', '', 'Photos (*.jpg *.jpeg *.png *.bmp *.webp)')
        if path:
            try:
                self.load_photo(path)
            except Exception as exc:
                self.error.setText(str(exc))
                self.error.show()

    def load_photo(self, path):
        source = Path(path)
        if not source.is_file() or source.stat().st_size > 50 * 1024**2:
            raise RuleError('Choose a local photo smaller than 50 MB.')
        reader = QImageReader(str(source))
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 80_000_000:
            raise RuleError('Choose a supported photo with at most 80 million pixels.')
        self.set_photo(reader.read())

    def save(self):
        self.error.hide()
        invalid = [key for key in self.field_errors if not self.validate_field(key)]
        if invalid:
            self.fields[invalid[0]].setFocus()
            return
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        if not save_button.isEnabled():
            return
        save_button.setEnabled(False)
        try:
            if self.check_duplicates():
                self.error.setText('Choose an existing customer or confirm creating a new customer with this phone number.')
                self.error.show()
                return
            # Retain the ID immediately: a photo failure must never create another customer on retry.
            self.customer_id = self.s.save_customer(**self.values(), ident=self.customer_id)
            if self.pending_image is not None:
                try:
                    self.records.save_photo(self.pending_image, self.customer_id, captured=self.pending_captured)
                except Exception as exc:
                    raise RuleError('Customer details were saved, but the photo was not saved. Retry Save customer. ' + str(exc)) from exc
                self.pending_image = None
            self.saved_id = self.customer_id
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc))
            self.error.show()
        finally:
            save_button.setEnabled(True)


def register_customer(window, row=None, *, parent=None, initial=None):
    if row and row.get('id'):
        row = window.s.db.one('SELECT * FROM customers WHERE id=?', (row['id'],))
    dialog = CustomerRegistration(window.s, row=row, parent=parent or window, initial=initial)
    return dialog.saved_id if dialog.exec() else None
