"""Routine lifecycle clicks should not open forms with no fields."""
import json

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from legacy_desktop.lifecycle_ui import JobWorkspace
from legacy_desktop.ui import MainWindow
from test_lifecycle import approve, complete, diagnosis, fresh, qc, route


class FormRequested(Exception):
    pass


def workspace(qtbot, service, ident):
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    dialog = JobWorkspace(window, ident)
    qtbot.addWidget(dialog)
    return window, dialog


def forbid_form(monkeypatch):
    def unexpected(*args, **kwargs):
        raise FormRequested('A routine action opened a form')
    monkeypatch.setattr('legacy_desktop.lifecycle_ui.Form', unexpected)


def test_initial_inspection_advances_and_refreshes_without_a_form(qtbot, service, customer, monkeypatch):
    ident, life = fresh(service, customer)
    window, dialog = workspace(qtbot, service, ident)
    version = dialog.view['version']
    forbid_form(monkeypatch)

    dialog.act('inspect')

    assert dialog.view['stage'] == 'inspection'
    assert dialog.view['version'] > version
    assert dialog.next is dialog.journey.current_action
    assert dialog.view['primary'] == 'inspection_done'
    event = service.db.one("SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='lifecycle' ORDER BY id DESC LIMIT 1", (ident,))
    assert json.loads(event['payload'])['action'] == 'inspect'
    window.pool.waitForDone(10000)


def test_start_repair_advances_without_a_form_and_keeps_audit(qtbot, service, customer, monkeypatch):
    ident, life = route(service, customer)
    diagnosis(life, ident)
    approve(service, ident)
    window, dialog = workspace(qtbot, service, ident)
    version = dialog.view['version']
    forbid_form(monkeypatch)

    dialog.act('start_repair')

    assert dialog.view['stage'] == 'under_repair'
    assert dialog.view['version'] > version
    event = service.db.one("SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='lifecycle' ORDER BY id DESC LIMIT 1", (ident,))
    assert json.loads(event['payload'])['action'] == 'start_repair'
    window.pool.waitForDone(10000)


def test_notify_uses_saved_channel_settings_without_a_form(qtbot, service, customer, monkeypatch):
    ident, life = route(service, customer)
    diagnosis(life, ident)
    approve(service, ident)
    complete(life, ident)
    qc(life, ident)
    life.execute(ident, 'bill', {'confirmed': True})
    assert 'notify' in life.snapshot(ident)['actions']
    window, dialog = workspace(qtbot, service, ident)
    forbid_form(monkeypatch)

    dialog.act('notify')

    assert dialog.view['data']['notified']
    event = service.db.one("SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='lifecycle' ORDER BY id DESC LIMIT 1", (ident,))
    assert json.loads(event['payload'])['action'] == 'notify'
    window.pool.waitForDone(10000)


def test_complete_inspection_still_requests_required_findings(qtbot, service, customer, monkeypatch):
    ident, life = fresh(service, customer)
    life.execute(ident, 'inspect')
    window, dialog = workspace(qtbot, service, ident)
    forbid_form(monkeypatch)

    with pytest.raises(FormRequested):
        dialog._act('inspection_done')
    assert service.job(ident)['stage'] == 'inspection'
    window.pool.waitForDone(10000)


def test_close_job_uses_specific_confirmation_and_cancel_is_safe(qtbot, service, customer, monkeypatch):
    ident, life = route(service, customer)
    diagnosis(life, ident)
    approve(service, ident)
    complete(life, ident)
    qc(life, ident)
    life.execute(ident, 'bill', {'confirmed': True})
    service.post('customer', customer, 'receipt', 120000, 'close-test-payment', job_id=ident)
    life.execute(ident, 'handover', dict(demonstrated=True, accepted=True,
        accessories_returned=True, payment_checked=True, received_by='Owner', acknowledgment='Signed'))
    window, dialog = workspace(qtbot, service, ident)
    forbid_form(monkeypatch)
    original_exec = QMessageBox.exec

    def click_button(text):
        def run(box):
            QTimer.singleShot(0, lambda: next(b for b in box.buttons() if b.text() == text).click())
            return original_exec(box)
        return run

    monkeypatch.setattr(QMessageBox, 'exec', click_button('Cancel'))
    dialog._act('close')
    assert service.job(ident)['stage'] == 'collected'

    monkeypatch.setattr(QMessageBox, 'exec', click_button('Close job'))
    dialog._act('close')
    assert service.job(ident)['stage'] == 'closed'
    window.pool.waitForDone(10000)
