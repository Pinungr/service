"""Stored files, generated documents and issued job cards.

The browser never sees a filesystem path. Files are addressed by attachment id and every
download repeats the access check of the record the file belongs to. PDFs are generated
by the existing document code; no figure is recomputed here.
"""
import json
import mimetypes
import os
import tempfile
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from repairshop.documents import Documents
from repairshop.job_cards import JobCards
from repairshop.readmodels import ReadModels
from ..deps import service
from ..errors import ApiError
from ..schemas import Model
from .customers import read_upload

router = APIRouter(tags=['documents'])
DOCUMENT_KINDS = ('job_card', 'intake_receipt', 'dispatch_manifest', 'return_manifest', 'quotation', 'bill',
                  'payment_receipt', 'refund_acknowledgment', 'collection_receipt', 'final_invoice', 'warranty_summary')


class StoredFile(Model):
    id: int
    title: str
    kind: str
    job_id: int | None = None
    created: str | None = None
    url: str = ''


class Attachment(Model):
    id: int
    kind: str
    title: str
    created: str
    captured: str | None = None
    job_id: int | None = None
    device_id: int | None = None
    person_role: str | None = None


class DocumentIn(BaseModel):
    kind: str
    source_id: int | None = None
    visibility: str = Field('customer', pattern='^(customer|internal)$')
    paper: str | None = Field(None, pattern='^(A4|A5)$')


class VisitReceiptIn(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=50)


class CardPrintIn(BaseModel):
    internal: bool = False


def stored(s, path):
    row = ReadModels(s).attachment_for(path)
    if not row:
        raise ApiError(500, 'DOCUMENT_NOT_RECORDED', 'The document was generated but not recorded.')
    return StoredFile(**row, url=f"/api/files/{row['id']}")


@router.get('/files/{ident}')
def download(ident: int, download: bool = False, s=Depends(service)):
    row, path = ReadModels(s).attachment_file(ident)
    media = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    name = (row['title'] or 'document').replace('/', '-').replace('\\', '-')[:80] + path.suffix
    return FileResponse(path, media_type=media, filename=name,
                        content_disposition_type='attachment' if download else 'inline')


@router.get('/repairs/{ident}/attachments', response_model=list[Attachment])
def attachments(ident: int, s=Depends(service)):
    return ReadModels(s).attachments(ident)


@router.post('/repairs/{ident}/attachments', response_model=StoredFile)
async def upload_evidence(ident: int, file: UploadFile = File(...), title: str = Form('Evidence', max_length=120), s=Depends(service)):
    """Attach a PDF / JPG / PNG to the repair. Content is checked against its extension."""
    data = await read_upload(file)
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ('.pdf', '.jpg', '.jpeg', '.png'):
        raise ApiError(400, 'UNSUPPORTED_FILE', 'Attach evidence as PDF, JPG/JPEG, or PNG.')
    handle, temporary = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        path = Documents(s).attach(temporary, title.strip() or 'Evidence', job_id=ident)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return stored(s, path)


@router.post('/repairs/{ident}/documents', response_model=StoredFile)
def generate(ident: int, values: DocumentIn, s=Depends(service)):
    if values.kind not in DOCUMENT_KINDS:
        raise ApiError(400, 'UNKNOWN_DOCUMENT', 'Choose a supported document.')
    kind = 'intake_receipt' if values.kind == 'job_card' else values.kind
    return stored(s, Documents(s).generate(kind, ident, values.source_id, values.paper, values.visibility))


@router.post('/visits/receipt', response_model=StoredFile)
def visit_receipt(values: VisitReceiptIn, s=Depends(service)):
    return stored(s, Documents(s).visit_receipt(values.job_ids))


@router.get('/repairs/{ident}/cards')
def cards(ident: int, s=Depends(service)):
    rows = JobCards(s).rows(ident)
    for row in rows:
        row['snapshot'] = json.loads(row['snapshot'])
    return rows


@router.post('/cards/{ident}/print', response_model=StoredFile)
def print_card(ident: int, values: CardPrintIn, s=Depends(service)):
    return stored(s, JobCards(s).print(ident, internal=values.internal))
