"""Reports, notifications, backups, shop settings and staff."""
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from repairshop import app_settings
from repairshop.backup import Backups
from repairshop.documents import Documents
from repairshop.domain import RuleError, today
from repairshop.messaging import Outbox, status_label
from repairshop.queries import Queries
from repairshop.readmodels import ReadModels
from ..deps import permission, runtime, service
from ..errors import ApiError
from ..schemas import Ok

router = APIRouter(tags=['admin'])
REPORTS = ('jobs', 'custody', 'overdue', 'warranty', 'job_cards', 'repair_parts', 'part_warranties', 'warranty_claims',
           'customer_dues', 'vendor_dues', 'payments', 'transport', 'margins')
SHOP_KEYS = ('shop_name', 'address', 'hours', 'timezone', 'decline_policy', 'backup_destination', 'external_backup',
             'backup_retention', 'archive_days')


class ShopIn(BaseModel):
    shop_name: str | None = None
    address: str | None = None
    hours: str | None = None
    timezone: str | None = None
    decline_policy: Literal['NO_CUSTOMER_CHARGE', 'AGREED_TRANSPORT_ONLY'] | None = None
    backup_destination: str | None = None
    external_backup: str | None = None
    backup_retention: int | None = Field(None, ge=1)
    archive_days: Literal[60, 90] | None = None


class StaffIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    role: Literal['owner', 'counter', 'technician']
    password: str = ''
    active: bool = True


class ChannelsIn(BaseModel):
    """Messaging configuration. Tokens go to the operating system credential store, never the database."""
    messaging_mode: Literal['test', 'live'] = 'test'
    notifications_paused: bool = False
    whatsapp: dict[str, str] = {}
    smtp: dict[str, Any] = {}
    templates: dict[str, dict[str, str]] = {}
    reminder_days: int = Field(0, ge=0, le=90)
    email_subject: str = '{job_number} · {event}'
    message_template: str = '{shop_name}\n{job_number} · {device}\n{message}'
    whatsapp_token: str = ''
    smtp_credential: str = ''


class RecipientIn(BaseModel):
    kind: Literal['staff', 'vendor']
    entity_id: int
    channel: Literal['email', 'whatsapp']
    destination: str = Field(min_length=3)
    consent: bool = False
    active: bool = True


class QueueDocumentIn(BaseModel):
    attachment_id: int
    recipient_id: int
    subject: str = 'Your account statement'
    body: str = 'Please find the requested account statement attached.'
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80)


class SendCustomerIn(BaseModel):
    attachment_id: int
    channels: list[Literal['whatsapp', 'email']] = Field(min_length=1)
    message: str = Field(min_length=1)
    event: str = 'document'
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80)


class BackupIn(BaseModel):
    kind: Literal['daily', 'archive'] = 'daily'


class RestoreIn(BaseModel):
    confirmation: str


# ---- reports --------------------------------------------------------------------

def run_report(s, kind, start, end, route, customer_id, category_id, assignment):
    if kind not in REPORTS:
        raise ApiError(400, 'UNKNOWN_REPORT', 'Choose a supported report.')
    return Queries(s).report(kind, start or today()[:8] + '01', end or today(), route or '', customer_id, category_id, assignment)


@router.get('/reports')
def reports(s=Depends(permission('reports'))):
    return dict(kinds=list(REPORTS), routes=['in_house', 'third_party', 'warranty_centre'])


@router.get('/reports/{kind}')
def report(kind: str, start: str | None = None, end: str | None = None, route: str = '', customer_id: int | None = None,
           category_id: int | None = None, assignment: int | None = None, s=Depends(service)):
    return run_report(s, kind, start, end, route, customer_id, category_id, assignment)


@router.get('/reports/{kind}/export')
def export(kind: str, background: BackgroundTasks, format: Literal['xlsx', 'csv', 'pdf'] = 'xlsx', start: str | None = None,
           end: str | None = None, route: str = '', customer_id: int | None = None, category_id: int | None = None,
           assignment: int | None = None, s=Depends(service)):
    """Export a report with the existing exporter; the temporary file is removed after sending."""
    rows = run_report(s, kind, start, end, route, customer_id, category_id, assignment)
    folder = Path(tempfile.mkdtemp(prefix='repairshop-export-'))
    path = Documents(s).export(folder / f'{kind}.{format}', kind.replace('_', ' ').title(), rows)
    background.add_task(lambda: (path.unlink(missing_ok=True), folder.rmdir()))
    return FileResponse(path, filename=path.name)


# ---- notifications ------------------------------------------------------------------

@router.get('/notifications')
def notifications(s=Depends(service)):
    rows = ReadModels(s).outbox()
    for row in rows:
        row['status'] = status_label(row['state'])
    return rows


@router.get('/notifications/{ident}')
def notification(ident: int, s=Depends(service)):
    row = ReadModels(s).outbox_message(ident)
    payload = json.loads(row['payload'])
    return dict(id=row['id'], destination=row['destination'], channel=row['channel'], state=row['state'],
                status=status_label(row['state']), provider_id=row['provider_id'], error=row['error'],
                subject=payload.get('subject', ''), body=payload.get('body', ''))


@router.post('/notifications/{ident}/{action}', response_model=Ok)
def notification_action(ident: int, action: Literal['retry', 'cancel'], s=Depends(service)):
    Outbox(s).action(ident, action)
    return Ok(id=ident)


@router.post('/notifications/process')
def process_queue(s=Depends(permission('messaging'))):
    """Submit queued notifications now, as the signed-in user, instead of waiting for the next tick."""
    from ..scheduler import Scheduler
    return dict(processed=Scheduler._notifications(s))


@router.get('/settings/messaging')
def channels(s=Depends(permission('messaging_admin'))):
    db = s.db
    return dict(messaging_mode=db.setting('messaging_mode', 'test'), notifications_paused=db.setting('notifications_paused', False),
                whatsapp=db.setting('whatsapp', {}), smtp=db.setting('smtp', {}), templates=db.setting('templates', {}),
                reminder_days=db.setting('reminder_days', 0), email_subject=db.setting('email_subject', '{job_number} · {event}'),
                message_template=db.setting('message_template', '{shop_name}\n{job_number} · {device}\n{message}'))


@router.put('/settings/messaging', response_model=Ok)
def save_channels(values: ChannelsIn, s=Depends(permission('messaging_admin'))):
    from repairshop.messaging import secret
    data = values.model_dump()
    for key, name in (('whatsapp_token', 'whatsapp_token'), ('smtp_credential', 'smtp_credential')):
        token = data.pop(key)
        if token:
            secret(name, token)
    if 'port' in data['smtp']:
        data['smtp']['port'] = int(data['smtp']['port'] or 587)
    s.settings(data)
    return Ok()


@router.get('/settings/recipients')
def recipients(s=Depends(service)):
    return dict(recipients=ReadModels(s).recipients(), documents=ReadModels(s).issued_documents())


@router.post('/settings/recipients', response_model=Ok)
def save_recipient(values: RecipientIn, s=Depends(service)):
    return Ok(id=s.save_recipient(**values.model_dump()))


@router.post('/notifications/statements', response_model=Ok)
def queue_statement(values: QueueDocumentIn, s=Depends(service)):
    return Ok(id=s.queue_document(**values.model_dump()))


@router.post('/repairs/{ident}/send-document')
def send_document(ident: int, values: SendCustomerIn, s=Depends(service)):
    """A manual customer copy of an issued document. Optional and never part of a repair transaction."""
    job = s.job(ident)
    results = s.queue_customer_document(values.attachment_id, job['customer_id'], values.channels, values.event,
                                        values.message, values.operation_id, job_id=ident)
    return [dict(channel=r['channel'], state=r['state'], status=status_label(r['state'])) for r in results]


# ---- backups -----------------------------------------------------------------------------

def _archive(s, ident):
    row = next((r for r in ReadModels(s).backups(1000) if r['id'] == ident), None)
    if not row or row['state'] != 'verified':
        raise ApiError(404, 'NOT_FOUND', 'Choose a verified backup from the list.')
    path = Path(row['path'])
    if not path.is_absolute():
        path = s.db.root / path
    if not path.is_file():
        raise ApiError(404, 'NOT_FOUND', 'This backup file is no longer in its folder.')
    return path


@router.get('/backups')
def backups(s=Depends(service)):
    """Backups by file name only; the browser never learns where files live on disk."""
    rows = [dict({k: v for k, v in r.items() if k != 'path'}, name=Path(r['path']).name) for r in ReadModels(s).backups()]
    return dict(backups=rows, retention=s.db.setting('backup_retention', 30), archive_days=s.db.setting('archive_days', 90),
                external_configured=bool(s.db.setting('external_backup')))


@router.post('/backups')
def create_backup(values: BackupIn, s=Depends(permission('backup_restore'))):
    path = Backups(s).create(values.kind)
    return dict(created=Path(path).name)


@router.post('/backups/{ident}/validate')
def validate_backup(ident: int, s=Depends(permission('backup_restore'))):
    manifest = Backups.validate(_archive(s, ident))
    return dict(created=manifest['created'], schema=manifest['schema'], customers=manifest['customers'],
                jobs=manifest['jobs'], files=len(manifest['files']))


@router.post('/backups/{ident}/restore')
def restore_backup(ident: int, values: RestoreIn, rt=Depends(runtime), s=Depends(permission('backup_restore'))):
    """Replace live data with a verified backup. The previous state is retained; restart afterwards."""
    if values.confirmation != 'RESTORE':
        raise RuleError('Type RESTORE after reviewing the archive preview.')
    if rt.scheduler and rt.scheduler.busy:
        raise RuleError('Wait for background work to finish before restoring.')
    retained = Backups(s).restore(_archive(s, ident), values.confirmation)
    rt.sessions.items.clear()
    return dict(restart_required=True, previous_state=Path(retained).name)


@router.post('/backups/retry-external', response_model=Ok)
def retry_external(s=Depends(service)):
    Backups(s).retry_external()
    return Ok()


# ---- settings and staff ------------------------------------------------------------------

@router.get('/settings/shop')
def shop(s=Depends(service)):
    return {key: s.db.setting(key) for key in SHOP_KEYS}


@router.put('/settings/shop', response_model=Ok)
def save_shop(values: ShopIn, s=Depends(service)):
    s.settings(values.model_dump(exclude_none=True))
    return Ok()


@router.get('/settings/application')
def application(s=Depends(service)):
    return [dict(section=section, settings=[dict(key=key, label=setting.label, kind=setting.kind or 'choice',
                                                 choices=list(setting.choices or ()), value=app_settings.value(s.db, key))
                                            for key, setting in entries])
            for section, entries in app_settings.sections().items()]


@router.put('/settings/application', response_model=Ok)
def save_application(values: dict[str, Any], s=Depends(service)):
    s.settings(values)
    return Ok()


@router.get('/staff')
def staff(s=Depends(service)):
    return ReadModels(s).staff()


@router.get('/staff/colleagues')
def colleagues(s=Depends(service)):
    return ReadModels(s).colleagues()


@router.post('/staff', response_model=Ok)
def create_staff(values: StaffIn, s=Depends(service)):
    return Ok(id=s.save_staff(**values.model_dump()))


@router.put('/staff/{ident}', response_model=Ok)
def update_staff(ident: int, values: StaffIn, rt=Depends(runtime), s=Depends(service)):
    s.save_staff(**values.model_dump(), ident=ident)
    if not values.active or values.password:
        rt.sessions.end_user(ident)
    return Ok(id=ident)
