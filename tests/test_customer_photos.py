import json
import sqlite3
import uuid
from pathlib import Path
import pytest
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QCheckBox
from repairshop.camera import CameraDialog, NO_CAMERA
from repairshop.customer_records import CustomerRecords
from repairshop.customer_ui import IntakeForm, CustomerOverview
from repairshop.domain import RuleError
from repairshop.local_files import managed_path, digest
from repairshop.persistence import Database, SCHEMA
from repairshop.services import Service
from repairshop.backup import Backups
from repairshop.ui import MainWindow


def held_at(service, item_id):
    """Where an item actually is now. Intake custody belongs to the signed-in receiver."""
    return service.db.one('SELECT location FROM holdings WHERE item_id=? AND quantity>0',
                          (item_id,))['location']


def with_me(service):
    """The custody identity of the signed-in user."""
    from repairshop.domain import staff_custody
    return staff_custody(service.user['id'])


def picture(color='#456f93'):
    image = QImage(100, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


class FakeCamera(QObject):
    changed = pyqtSignal()
    ready = pyqtSignal(bool)
    captured = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, devices=()):
        super().__init__()
        self.available = list(devices)
        self.stopped = 0
        self.started = []
        self.error = ''

    def devices(self):
        return self.available

    def start(self, ident, preview):
        self.started.append(ident)
        if self.error:
            self.failed.emit(self.error)
        else:
            self.ready.emit(True)

    def stop(self):
        self.stopped += 1

    def capture(self):
        if self.error:
            self.failed.emit(self.error)
        else:
            self.captured.emit(picture())


def collect_all(service, job):
    service.stage(job, 'ready_repaired', test_result='passed')
    for h in service.db.rows('SELECT h.* FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND h.quantity>0', (job,)):
        service.move(h['item_id'], h['quantity'], h['location'], 'customer', 'Owner', uuid.uuid4().hex, acknowledgment='Signed')
    service.stage(job, 'collected')


def test_no_camera_retry_selection_and_release(qtbot):
    backend = FakeCamera()
    dialog = CameraDialog(lambda *_: 1, backend=backend)
    qtbot.addWidget(dialog)
    assert dialog.status.text() == NO_CAMERA
    assert not dialog.capture_button.isEnabled()
    backend.available = [(b'camera1', 'USB webcam'), (b'camera2', 'Second webcam')]
    dialog.retry_button.click()
    assert dialog.capture_button.isEnabled()
    dialog.selection.setCurrentIndex(1)
    assert backend.started[-1] == b'camera2'
    backend.available = []
    backend.changed.emit()
    assert dialog.status.text() == NO_CAMERA
    before = backend.stopped
    dialog.cancel_button.click()
    assert dialog.closed and backend.stopped > before


@pytest.mark.parametrize('failure', ['Access denied', 'Camera busy', 'Disconnected', 'Capture failed'])
def test_camera_failure_is_recoverable(qtbot, failure):
    backend = FakeCamera([(b'camera', 'USB webcam')])
    dialog = CameraDialog(lambda *_: 1, backend=backend)
    qtbot.addWidget(dialog)
    backend.error = failure
    dialog.capture_button.click()
    assert failure in dialog.status.text()
    assert not dialog.save_button.isEnabled()
    backend.error = ''
    dialog.retry_button.click()
    assert dialog.capture_button.isEnabled()
    dialog.reject()


def test_capture_retake_and_local_persistence(qtbot, service, customer):
    backend = FakeCamera([(b'camera', 'USB webcam')])
    records = CustomerRecords(service)
    dialog = CameraDialog(lambda image, captured: records.save_photo(image, customer, captured=captured), backend=backend)
    qtbot.addWidget(dialog)
    dialog.capture_button.click()
    assert dialog.image is not None and dialog.save_button.isEnabled()
    dialog.retake_button.click()
    assert dialog.image is None and not dialog.save_button.isEnabled()
    dialog.capture_button.click()
    dialog.save_button.click()
    qtbot.waitUntil(lambda: dialog.photo_id is not None)
    photo = service.db.one('SELECT * FROM attachments WHERE id=?', (dialog.photo_id,))
    assert QImage(str(service.db.root / photo['path'])).isNull() is False
    assert photo['captured'] == dialog.captured_at
    assert photo['sha256'] == digest((service.db.root / photo['path']).read_bytes())
    assert dialog.closed


def test_failed_photo_save_keeps_image_and_allows_retry(qtbot):
    failures = [True]
    def save(*_):
        if failures[0]:
            raise OSError('disk full')
        return 22
    dialog = CameraDialog(save, backend=FakeCamera([(b'cam', 'USB')]))
    qtbot.addWidget(dialog)
    dialog.capture()
    dialog.save()
    qtbot.waitUntil(lambda: not dialog.saving)
    assert dialog.photo_id is None and dialog.image is not None
    assert 'not saved' in dialog.status.text() and 'disk full' in dialog.status.text()
    failures[0] = False
    dialog.save()
    qtbot.waitUntil(lambda: dialog.photo_id == 22)


def test_required_photo_and_legacy_record_access(service):
    customer = service.save_customer('Legacy person', '9990000003', complete=False)
    assert CustomerRecords(service).overview(customer)['photos'] == []
    with pytest.raises(RuleError, match='required customer photo'):
        service.intake(customer, 'Laptop', 'Fault')
    assert service.db.one('SELECT count(*) n FROM jobs')['n'] == 0


def test_owner_submitter_history_and_missing_photo(service, customer):
    records = CustomerRecords(service)
    original = service.db.one('SELECT current_photo_id FROM customers WHERE id=?', (customer,))['current_photo_id']
    submitter = records.save_photo(picture(), customer, 'submitter', 'Ravi')
    assert service.db.one('SELECT current_photo_id FROM customers WHERE id=?', (customer,))['current_photo_id'] == original
    with pytest.raises(RuleError, match='submitter'):
        service.intake(customer, 'Laptop', 'Fault', photo_id=submitter, submitter='Someone else')
    job = service.intake(customer, 'Laptop', 'Fault', photo_id=submitter, submitter='Ravi')
    assert service.job(job)['photo_id'] == submitter
    replacement = records.save_photo(picture('#ffffff'), customer)
    assert replacement not in (original, submitter)
    assert len(records.overview(customer)['photos']) == 3
    path = service.db.root / service.db.one('SELECT path FROM attachments WHERE id=?', (replacement,))['path']
    path.unlink()
    with pytest.raises(RuleError, match='missing or damaged'):
        service.intake(customer, 'Phone', 'Fault')


def test_duplicate_names_folder_stability_and_confined_paths(service, customer):
    records = CustomerRecords(service)
    twin = service.save_customer('Synthetic Customer', '9990000004', complete=False)
    first = records.sync_customer(customer)
    second = records.sync_customer(twin)
    assert first != second and first.is_dir() and second.is_dir()
    service.save_customer('Corrected: ../Name?', ident=customer)
    assert records.sync_customer(customer) == first
    assert 'Corrected:' in (first / 'customer-details.txt').read_text(encoding='utf-8')
    assert len(list((service.db.root / 'Customers').iterdir())) == 2
    for path in ['../escape.jpg', 'Customers/../../escape.jpg', 'C:/escape.jpg', 'managed/../outside.txt', 'Customers/a:stream']:
        with pytest.raises(RuleError):
            managed_path(service.db.root, path)


def test_same_category_separate_products_and_repeat_repair(service, customer):
    one = service.intake(customer, 'Laptop', 'Fault', intake_ref='One visit')
    two = service.intake(customer, 'Laptop', 'Fault', intake_ref='One visit')
    first_device = service.job(one)['device_id']
    assert first_device != service.job(two)['device_id']
    with pytest.raises(RuleError, match='outstanding'):
        service.intake(customer, 'Laptop', 'Repeat', device_id=first_device)
    collect_all(service, one)
    repeat = service.intake(customer, 'Laptop', 'Repeat', parent_id=one)
    assert service.job(repeat)['device_id'] == first_device
    assert service.job(repeat)['number'] != service.job(one)['number']
    records = CustomerRecords(service)
    folder = records.sync_customer(customer)
    assert len(list(folder.glob('*DEV-*'))) == 2
    first = service.db.one('SELECT folder FROM devices WHERE id=?', (first_device,))['folder']
    assert len(list((service.db.root / first / 'Repairs').iterdir())) == 2
    assert records.overview(customer)['counts']['outstanding'] == 2


def test_device_ownership_and_link_validation(service, customer, job):
    other = service.save_customer('Different Owner', '9990000005', complete=False)
    CustomerRecords(service).save_photo(picture(), other)
    with pytest.raises(RuleError, match='belong'):
        service.intake(other, 'Laptop', 'Fault', device_id=service.job(job)['device_id'])
    with pytest.raises(RuleError, match='linked'):
        service.intake(other, 'Laptop', 'Fault', parent_id=job)


def test_readiness_requires_every_accessory_and_tracks_partial_collection(service, customer, job):
    records = CustomerRecords(service)
    adapter = service.db.one("SELECT id FROM items WHERE job_id=? AND description='Adapter'", (job,))['id']
    service.move(adapter, 1, held_at(service, adapter), 'vendor:Repairer', 'Repairer', 'adapter-away')
    service.stage(job, 'ready_repaired', test_result='passed')
    data = records.overview(customer)
    assert data['counts']['outstanding'] == 1 and data['counts']['vendors'] == 1
    assert not data['all_ready'] and data['counts']['ready'] == 0
    service.move(adapter, 1, 'vendor:Repairer', with_me(service), 'Repairer', 'adapter-back')
    assert records.overview(customer)['all_ready']
    device = service.db.one("SELECT id FROM items WHERE job_id=? AND type='device'", (job,))['id']
    service.move(device, 1, held_at(service, device), 'customer', 'Owner', 'partial', acknowledgment='Signed')
    data = records.overview(customer)
    assert data['outstanding'][0]['collection_status'] == 'Partially collected'
    assert data['counts']['outstanding'] == 1 and data['all_ready']
    service.post('customer', customer, 'receipt', 10000, 'advance-balance', job_id=job)
    assert records.overview(customer)['all_ready']


def test_external_completion_not_ready_and_unrepaired_distinct(service, customer, job):
    records = CustomerRecords(service)
    device = service.db.one("SELECT id FROM items WHERE job_id=? AND type='device'", (job,))['id']
    service.move(device, 1, held_at(service, device), 'transit:Courier', 'Courier', 'dispatch')
    assert records.overview(customer)['counts']['in_transit'] == 1
    service.move(device, 1, 'transit:Courier', 'centre:Care', 'Care', 'arrival')
    service.stage(job, 'awaiting_return')
    data = records.overview(customer)
    assert not data['all_ready'] and data['counts']['service_centres'] == 1
    service.move(device, 1, 'centre:Care', with_me(service), 'Care', 'return')
    service.stage(job, 'ready_unrepaired', reason='Returned and checked; part unavailable')
    data = records.overview(customer)
    assert data['all_ready'] and data['outstanding'][0]['stage'] == 'ready_unrepaired'


def test_collected_history_does_not_block_current_readiness(service, customer, job):
    collect_all(service, job)
    repeat = service.intake(customer, 'ThinkPad', 'New fault', parent_id=job)
    service.stage(repeat, 'ready_repaired', test_result='passed')
    data = CustomerRecords(service).overview(customer)
    assert data['all_ready'] and len(data['history']) == 1
    assert data['counts']['outstanding'] == 1 and data['counts']['collected'] == 0


def test_a_hold_blocks_overall_readiness(service, customer, job):
    service.stage(job, 'ready_repaired', test_result='passed')
    service.hold(job, 'Accessory condition needs review')
    assert not CustomerRecords(service).overview(customer)['all_ready']


def test_final_intake_consumes_draft_and_retries_without_duplicate(service, customer):
    records = CustomerRecords(service)
    records.save_draft('durable-intake', {'customer_id': customer, 'device': 'Laptop', 'complaint': 'Fault'})
    first = service.intake(customer, 'Laptop', 'Fault', operation_id='durable-intake', draft_id='durable-intake')
    assert records.drafts() == []
    assert service.intake(customer, 'Laptop', 'Fault', operation_id='durable-intake') == first
    assert service.db.one('SELECT count(*) n FROM jobs')['n'] == 1


def test_empty_photo_folders_survive_archive_extraction(service, customer, job, tmp_path):
    records = CustomerRecords(service)
    records.sync_customer(customer)
    relative = service.db.one('SELECT folder FROM devices WHERE id=?', (service.job(job)['device_id'],))['folder'] + '/Product-Photos'
    archive = Backups(service).create()
    target = tmp_path / 'relocated'
    Backups.validate(archive, target)
    assert (target / relative).is_dir()


def test_interrupted_restore_preserves_both_customer_trees(service, customer, job):
    import os
    records = CustomerRecords(service)
    folder = records.sync_customer(customer)
    root = service.db.root
    with service.db.read() as c:
        c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    service.db.engine.dispose()
    recovery = root / 'restore-recovery-photo-test'
    previous = recovery / 'previous'
    previous.mkdir(parents=True)
    originals = ['shop.db', 'managed', 'Customers']
    for name in originals:
        os.replace(root / name, previous / name)
    (root / 'Customers').mkdir()
    (root / 'Customers' / 'candidate-only.txt').write_text('Candidate photo state')
    (root / 'restore-journal.json').write_text(json.dumps({'recovery': recovery.name, 'original_names': originals}))
    restored = Database(root)
    assert restored.one('SELECT id FROM jobs WHERE id=?', (job,))
    assert (folder / 'customer-details.txt').is_file()
    assert (recovery / 'interrupted-candidate' / 'Customers' / 'candidate-only.txt').is_file()


def test_product_photo_import_backup_relocation_recovery(service, customer, job, tmp_path):
    records = CustomerRecords(service)
    source = tmp_path / 'product.png'
    assert picture().save(str(source))
    ident = records.import_product_photo(source, customer, service.job(job)['device_id'], job)
    folder = records.sync_customer(customer)
    row = service.db.one('SELECT * FROM attachments WHERE id=?', (ident,))
    archive = Backups(service).create('archive')
    relocated = tmp_path / 'another-computer'
    Backups.validate(archive, relocated)
    target = Service(Database(relocated))
    target.login('owner', 'CorrectHorse123!')
    assert CustomerRecords(target).overview(customer)['outstanding'][0]['thumbnail'] == row['path']
    assert (relocated / row['path']).read_bytes() == (service.db.root / row['path']).read_bytes()
    assert (relocated / folder.relative_to(service.db.root) / 'customer-details.txt').is_file()
    lost = service.db.root / row['path']
    lost.unlink()
    with pytest.raises(RuleError, match='missing'):
        Backups(service).create()
    records.recover_photo(ident, relocated / row['path'])
    assert lost.is_file()
    with pytest.raises(RuleError, match='not the original'):
        records.recover_photo(ident, source)
    recovery = Backups(service).restore(archive, 'RESTORE')
    assert (recovery / 'previous' / 'Customers').is_dir()
    assert (service.db.root / row['path']).is_file()
    assert service.db.setting('notifications_paused')


def test_failed_file_save_has_no_false_photo_record(service, customer, monkeypatch):
    import repairshop.customer_records as module
    before = service.db.one('SELECT count(*) n FROM attachments')['n']
    def fail(*_, **__):
        raise OSError('disk full')
    monkeypatch.setattr(module, 'publish', fail)
    with pytest.raises(OSError, match='disk full'):
        CustomerRecords(service).save_photo(picture(), customer)
    assert service.db.one('SELECT count(*) n FROM attachments')['n'] == before


def test_summary_retry_preserves_unrelated_edits_and_db_history(service, customer, job):
    records = CustomerRecords(service)
    folder = records.sync_customer(customer)
    path = folder / 'customer-details.txt'
    path.write_text('Staff note outside app', encoding='utf-8')
    service.save_customer('Updated customer', ident=customer)
    with pytest.raises(RuleError, match='edited outside'):
        records.sync_customer(customer)
    assert path.read_text() == 'Staff note outside app'
    path.rename(folder / 'staff-note.txt')
    records.sync_customer(customer)
    assert 'Updated customer' in path.read_text(encoding='utf-8')
    assert service.job(job)['id'] == job


def test_backup_failure_stops_migration_before_schema_changes(tmp_path, monkeypatch):
    import repairshop.backup as module
    root = tmp_path / 'legacy'
    root.mkdir()
    c = sqlite3.connect(root / 'shop.db')
    c.executescript(SCHEMA + '\nPRAGMA user_version=1;')
    c.close()
    def fail(*_, **__):
        raise OSError('Backup drive full')
    monkeypatch.setattr(module, 'snapshot_archive', fail)
    with pytest.raises(OSError, match='Backup drive full'):
        Database(root)
    c = sqlite3.connect(root / 'shop.db')
    try:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 1
        assert 'folder' not in [r[1] for r in c.execute('PRAGMA table_info(customers)')]
    finally:
        c.close()


def test_intake_cancel_camera_fail_and_restart_preserve_draft(qtbot, service, customer, monkeypatch):
    import repairshop.customer_ui as ui
    real_camera = ui.CameraDialog
    created = []
    def simulated(*args, **kwargs):
        kwargs['backend'] = FakeCamera()
        dialog = real_camera(*args, **kwargs)
        created.append(dialog)
        QTimer.singleShot(20, dialog.reject)
        return dialog
    monkeypatch.setattr(ui, 'CameraDialog', simulated)
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.timer.stop()
    def fill():
        form = QApplication.activeModalWidget()
        assert isinstance(form, IntakeForm)
        form.fields['customer_id'].box.setCurrentIndex(1)
        form.fields['device'].setText('Draft laptop')
        form.fields['complaint'].setPlainText('Entered fault')
        form.fields['submitter'].setText('Relative')
        category = form.fields['category_id'].box
        category.setCurrentIndex(category.findText('Laptop'))
        checks = [w for w in form.findChildren(QCheckBox) if hasattr(w, 'quantity_control')]
        checks[0].setChecked(True)
        checks[0].quantity_control.setValue(2)
        capture = next(b for b in form.findChildren(__import__('PyQt6.QtWidgets', fromlist=['QPushButton']).QPushButton) if b.text() == 'Capture customer photo')
        capture.click()
        assert created[-1].status.text() == NO_CAMERA
        assert form.fields['complaint'].toPlainText() == 'Entered fault'
        form.reject()
    QTimer.singleShot(20, fill)
    window.intake()
    qtbot.waitUntil(lambda: not window.tasks)
    service.db.engine.dispose()
    reopened = Service(Database(service.db.root))
    reopened.login('owner', 'CorrectHorse123!')
    drafts = CustomerRecords(reopened).drafts()
    assert len(drafts) == 1
    payload = json.loads(drafts[0]['payload'])
    assert payload['device'] == 'Draft laptop' and payload['complaint'] == 'Entered fault'
    assert any(a['checked'] and a['quantity'] == 2 for a in payload['accessories'])
    def resume_check():
        form = QApplication.activeModalWidget()
        assert form.fields['device'].text() == 'Draft laptop'
        assert form.fields['submitter'].text() == 'Relative'
        checks = [w for w in form.findChildren(QCheckBox) if hasattr(w, 'quantity_control')]
        assert any(c.isChecked() and c.quantity_control.value() == 2 for c in checks)
        form.reject()
    QTimer.singleShot(20, resume_check)
    window.intake(draft=drafts[0])
    qtbot.waitUntil(lambda: not window.tasks)


def test_overview_shows_history_and_missing_photo_placeholder(qtbot, service, customer, job):
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.timer.stop()
    dialog = CustomerOverview(window, customer)
    qtbot.addWidget(dialog)
    assert dialog.grids['outstanding'].rowCount() == 1
    assert 'Outstanding products: 1' in dialog.counts.text()
    assert dialog.grids['history'].rowCount() == 0
    photo = service.db.one('SELECT path FROM attachments WHERE id=(SELECT current_photo_id FROM customers WHERE id=?)', (customer,))
    (service.db.root / photo['path']).unlink()
    dialog.reload()
    assert 'missing' in dialog.photo.text()
    qtbot.waitUntil(lambda: not window.tasks)
