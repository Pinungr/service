"""Post-confirmation actions: confirm what was created, then optionally send or print.

This dialog runs only after the visit, its jobs and their documents are already
committed. Nothing here can undo the intake: a WhatsApp, email or printer failure is
reported in place and the repair records stay exactly as saved.
"""
import uuid
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox
from .ui_widgets import button, combo, FlowLayout
from .domain import rupees, RuleError


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
        layout.addWidget(QLabel('Would you like to send or print these now?'))
        self.whatsapp = QCheckBox('Send to the customer on WhatsApp')
        self.email = QCheckBox('Email the customer')
        self.print_copy = QCheckBox('Open for printing')
        contact = window.db.one('SELECT * FROM customers WHERE id=?', (rows[0]['customer_id'],)) or {}
        # A channel is only offered when the customer can actually be reached on it and
        # has consented, so the dialog never promises a message it is not allowed to send.
        blocked = {}
        for box, field, consent, label in ((self.whatsapp, 'phone', 'whatsapp_consent', 'WhatsApp'),
                                           (self.email, 'email', 'email_consent', 'email')):
            if not contact.get(field):
                blocked[box] = 'no ' + label + ' contact recorded'
            elif not contact.get(consent):
                blocked[box] = label + ' consent not given — record consent on the customer first'
            box.setEnabled(box not in blocked and bool(documents))
            if box in blocked and documents:
                box.setText(box.text() + ' — ' + blocked[box])
            layout.addWidget(box)
        self.print_copy.setEnabled(bool(documents))
        layout.addWidget(self.print_copy)
        choice = FlowLayout()
        layout.addLayout(choice)
        self.paper = combo([('A4', 'A4'), ('A5', 'A5')], window.db.setting('paper_size', 'A4'))
        choice.addWidget(QLabel('Paper size for printing'))
        choice.addWidget(self.paper)
        layout.addWidget(self.status)
        layout.addStretch()
        actions = QDialogButtonBox()
        send = actions.addButton('Do it', QDialogButtonBox.ButtonRole.AcceptRole)
        send.setObjectName('primary')
        send.clicked.connect(lambda: window.safe(self.deliver))
        finish = actions.addButton('Finish', QDialogButtonBox.ButtonRole.RejectRole)
        finish.clicked.connect(self.accept)
        layout.addWidget(actions)

    def deliver(self):
        """Every optional step is attempted independently and reported, never rolled back."""
        notes = []
        channels = [name for name, box in (('whatsapp', self.whatsapp), ('email', self.email))
                    if box.isChecked() and box.isEnabled()]
        if channels and self.documents:
            title, path, job_id = self.documents[-1]
            attachment = self.window.db.one(
                "SELECT id FROM attachments WHERE kind='issued_document' AND path LIKE ? ORDER BY id DESC LIMIT 1",
                ('%' + path.name,))
            customer_id = self.window.s.job(self.jobs[0])['customer_id']
            try:
                if not attachment:
                    raise RuleError('The issued document could not be located for sending.')
                results = self.window.s.queue_customer_document(
                    attachment['id'], customer_id, channels, 'intake_receipt',
                    'Your products have been received. The attached receipt lists each product, its '
                    'initial estimate and the advance recorded.', uuid.uuid4().hex, job_id=job_id)
                from .messaging import status_label
                notes += [r['channel'].title() + ': ' + status_label(r['state']) for r in results]
            except Exception as exc:
                notes.append('Could not queue the message: ' + str(exc) + ' The intake is saved.')
        if self.print_copy.isChecked() and self.documents:
            paper = self.paper.currentData() or 'A4'
            try:
                # The receipt is rendered again for the chosen sheet, so A5 is a genuinely
                # re-laid-out page rather than an A4 document described as A5.
                path = self.window.docs.visit_receipt(self.jobs, paper=paper)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                notes.append('Opened the ' + paper + ' receipt for printing.')
            except Exception as exc:
                notes.append('Could not prepare the ' + paper + ' document for printing: ' + str(exc))
        self.status.setText('\n'.join(notes) or 'Nothing selected.')
