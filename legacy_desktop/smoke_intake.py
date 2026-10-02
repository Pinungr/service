"""Diagnostic rendering of real forms, used only by explicit demo smoke runs."""
from PyQt6.QtWidgets import QApplication
from .customer_ui import IntakeForm
from .customer_registration import CustomerRegistration


def capture_intake(window, root):
    forms=[]
    original=IntakeForm.submit
    IntakeForm.submit=lambda form,callback: forms.append(form) or 0
    try:
        window.intake()
    finally:
        IntakeForm.submit=original
    form=forms[0]
    try:
        form.show()
        for step in range(4):
            form.wizard.go(step)
            QApplication.processEvents()
            form.grab().save(str(root/f'intake-step-{step+1}-smoke.png'))
    finally:
        form.keep_draft=None
        form.close()
        form.deleteLater()
    registration=CustomerRegistration(window.s,parent=window)
    registration.show();QApplication.processEvents()
    registration.grab().save(str(root/'customer-registration-smoke.png'))
    registration.close();registration.deleteLater()
