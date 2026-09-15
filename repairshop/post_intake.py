"""Post-confirmation summary: what was created, and what the shop's settings did with it.

This dialog runs only after the visit, its jobs and their documents are already
committed. Nothing here can undo the intake: a WhatsApp, email or printer failure is
reported in place and the repair records stay exactly as saved.

The counter is not asked which paper to use or whether to message the customer. The
owner configures that once under Settings, and this screen reports what happened.
"""
import uuid
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox, QWidget
from . import app_settings
from .ui_widgets import button, combo, FlowLayout
from .domain import rupees, RuleError
from .messaging import status_label


class PostIntakeDialog(QDialog):
    def __init__(self, window, jobs, documents, document_error=''):
        super().__init__(window)
        self.window, self.jobs, self.documents = window, jobs, documents
        self.setWindowTitle('Intake created')
        self.resize(720, 640)
        layout = QVBoxLayout(self)
        rows = [window.s.job(ident) for ident in jobs]
        from .visits import Visits
        visit = Visits(window.s).for_job(jobs[0]) or {}
        heading = QLabel('INTAKE CREATED SUCCESSFULLY')
        heading.setObjectName('title')
        layout.addWidget(heading)
        estimate = sum(r['initial_estimate'] or 0 for r in rows)
        summary = QLabel('\n'.join(filter(None, [
            'Visit: ' + str(visit.get('number', 'Not recorded')),
            'Customer: ' + rows[0]['customer'],
            'Jobs: ' + ', '.join(r['number'] for r in rows),
            'Total initial estimate: ' + rupees(estimate)])))
        summary.setWordWrap(True)
        summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(summary)
        created = QLabel('Documents created:\n' + ('\n'.join('  ✓ ' + title for title, _, _ in documents)
                                                   or '  ✗ No document was created.'))
        created.setWordWrap(True)
        created.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(created)
        if document_error:
            problem = QLabel('The repair records were saved successfully, but a document could not be '
                             'created: ' + document_error + '\nYou can print it later from the repair workspace.')
            problem.setWordWrap(True)
            problem.setObjectName('errorBadge')
            layout.addWidget(problem)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        # Everything below is the occasional one-off: normal intakes need none of it.
        self.extra = QWidget()
        extra_layout = QVBoxLayout(self.extra)
        extra_layout.setContentsMargins(0, 0, 0, 0)
        extra_layout.addWidget(QLabel('Send or print an extra copy now. This does not change the '
                                      'shop settings, which only the owner can edit.'))
        self.whatsapp = QCheckBox('Also send on WhatsApp')
        self.email = QCheckBox('Also send by email')
        self.print_copy = QCheckBox('Open for printing')
        contact = window.db.one('SELECT * FROM customers WHERE id=?', (rows[0]['customer_id'],)) or {}
        for box, field, consent, label in ((self.whatsapp, 'phone', 'whatsapp_consent', 'WhatsApp'),
                                           (self.email, 'email', 'email_consent', 'email')):
            reason = ('no ' + label + ' contact recorded' if not contact.get(field)
                      else label + ' consent not given' if not contact.get(consent) else '')
            box.setEnabled(not reason and bool(documents))
            if reason and documents:
                box.setText(box.text() + ' — ' + reason)
            extra_layout.addWidget(box)
        self.print_copy.setEnabled(bool(documents))
        extra_layout.addWidget(self.print_copy)
        choice = FlowLayout()
        extra_layout.addLayout(choice)
        self.paper = combo([(size, size) for size in app_settings.PAPER_CHOICES],
                           window.docs.paper(document='intake_receipt'))
        choice.addWidget(QLabel('Paper size for this copy'))
        choice.addWidget(self.paper)
        send = button('Send / print the extra copy', lambda: window.safe(self.deliver))
        send.setObjectName('primary')
        extra_layout.addWidget(send)
        self.extra.hide()
        layout.addWidget(button('More options', lambda: self.extra.setVisible(not self.extra.isVisible())))
        layout.addWidget(self.extra)
        layout.addStretch()
        actions = QDialogButtonBox()
        finish = actions.addButton('Finish', QDialogButtonBox.ButtonRole.AcceptRole)
        finish.setObjectName('primary')
        finish.clicked.connect(self.accept)
        layout.addWidget(actions)
        self.apply_settings()

    def apply_settings(self):
        """Do what the shop is configured to do, then say what happened."""
        notes = []
        if self.documents:
            title, path, job_id = self.documents[-1]
            try:
                results = self.window.s.auto_notify(
                    'intake_receipt', self.attachment(path), self.window.s.job(self.jobs[0])['customer_id'],
                    'Your products have been received. The attached receipt lists each product, its '
                    'initial estimate and the advance recorded.', uuid.uuid4().hex, job_id=job_id)
                notes += [r['channel'].title() + ': ' + status_label(r['state']) for r in results]
                if not results:
                    notes.append('No customer message is configured for intake receipts.')
            except Exception as exc:
                notes.append('Could not queue the customer message: ' + str(exc)
                             + ' The intake is saved.')
            if app_settings.value(self.window.db, 'auto_print'):
                notes.append(self.open_for_print(self.window.docs.paper(document='intake_receipt')))
        self.status.setText('\n'.join(notes) or 'Intake saved.')

    def attachment(self, path):
        row = self.window.db.one(
            "SELECT id FROM attachments WHERE kind='issued_document' AND path LIKE ? ORDER BY id DESC LIMIT 1",
            ('%' + path.name,))
        if not row:
            raise RuleError('The issued document could not be located for sending.')
        return row['id']

    def open_for_print(self, paper):
        try:
            # Rendered again for the chosen sheet, so A5 is a real A5 page.
            path = self.window.docs.visit_receipt(self.jobs, paper=paper)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return 'Opened the ' + paper + ' receipt for printing.'
        except Exception as exc:
            return 'Could not prepare the ' + paper + ' document for printing: ' + str(exc)

    def deliver(self):
        """The manual one-off copy. Every step is attempted independently and reported."""
        notes = []
        channels = [name for name, box in (('whatsapp', self.whatsapp), ('email', self.email))
                    if box.isChecked() and box.isEnabled()]
        if channels and self.documents:
            title, path, job_id = self.documents[-1]
            customer_id = self.window.s.job(self.jobs[0])['customer_id']
            try:
                results = self.window.s.queue_customer_document(
                    self.attachment(path), customer_id, channels, 'intake_receipt',
                    'Your products have been received. The attached receipt lists each product, its '
                    'initial estimate and the advance recorded.', uuid.uuid4().hex, job_id=job_id)
                notes += [r['channel'].title() + ': ' + status_label(r['state']) for r in results]
            except Exception as exc:
                notes.append('Could not queue the message: ' + str(exc) + ' The intake is saved.')
        if self.print_copy.isChecked() and self.documents:
            notes.append(self.open_for_print(self.paper.currentData() or 'A4'))
        self.status.setText('\n'.join(notes) or 'Nothing selected.')
