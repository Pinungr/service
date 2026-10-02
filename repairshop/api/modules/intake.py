"""Receiving a customer's products at the counter.

Each product becomes its own repair job inside one visit, committed atomically by the
existing `intake_visit` service. Receipts and the optional customer message are
produced afterwards and can never undo the intake.
"""
import json
import uuid
from typing import Any
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from repairshop.customer_records import CustomerRecords
from repairshop.intake_products import prepare_visit, after_intake
from repairshop.readmodels import ReadModels
from repairshop.services import ITEM_CONDITIONS
from ..deps import permission, service
from ..schemas import Model, Ok
from .customers import read_upload

router = APIRouter(prefix='/intake', tags=['intake'])


class Accessory(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    quantity: int = Field(1, ge=1, le=999)
    serial: str = ''
    condition: str = 'Not Tested'
    notes: str = ''
    photo_id: int | None = None


class Product(BaseModel):
    """One physical product. Money is whole paise."""
    customer_id: int
    photo_id: int | None = None
    device_id: int | None = None
    sale_id: int | None = None
    parent_id: int | None = None
    category_id: int | None = None
    service_id: int | None = None
    device: str = Field(min_length=1, max_length=200)
    brand: str | None = None
    model: str | None = None
    serial: str = ''
    origin: str = 'elsewhere'
    complaint: str = Field(min_length=1)
    damage: str = ''
    customer_requirement: str = ''
    submitter: str = ''
    relationship: str = ''
    update_contact_id: int | None = None
    repair_due: str | None = None
    collection_due: str | None = None
    policy: str | None = None
    transport_agreed: int = 0
    assessment_agreed: int = 0
    assessment_consent: bool = False
    initial_estimate: int = 0
    deposit: int = 0
    advance: int = 0
    accessories: list[Accessory] = []
    product_photos: list[int] = []
    warranty_status: str | None = None
    warranty_expiry: str | None = None
    warranty_provider: str = ''
    warranty_notes: str = ''


class VisitIn(BaseModel):
    products: list[Product] = Field(min_length=1, max_length=50)
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80)
    draft_id: str | None = None
    notes: str = ''
    intake_ref: str | None = None


class Received(Model):
    id: int
    number: str
    device: str


class VisitOut(BaseModel):
    jobs: list[Received]
    visit: dict[str, Any] | None
    documents: list[dict[str, Any]]
    notes: list[str]


class Draft(Model):
    id: str
    customer_id: int | None = None
    customer: str | None = None
    updated: str
    payload: Any = None


class DraftIn(BaseModel):
    payload: dict[str, Any]


@router.get('/reference')
def reference(s=Depends(permission('intake'))):
    """Lists the counter form needs: categories, item conditions and the default return policy."""
    return dict(categories=s.masters('category'), conditions=list(ITEM_CONDITIONS),
                policies=[dict(value='NO_CUSTOMER_CHARGE', label='No customer charge'),
                          dict(value='AGREED_TRANSPORT_ONLY', label='Agreed transport only')],
                default_policy=s.db.setting('decline_policy', 'NO_CUSTOMER_CHARGE'))


@router.get('/categories/{ident}/services')
def services(ident: int, s=Depends(service)):
    return [dict(id=r['id'], name=r['name'], general=bool(r['general'])) for r in s.services_for_category(ident)]


@router.get('/categories/{ident}/accessories')
def accessories(ident: int, s=Depends(service)):
    return ReadModels(s).accessories(ident)


@router.post('/photos', response_model=Ok)
async def photo(file: UploadFile = File(...), customer_id: int = Form(...), role: str = Form('product'),
                description: str = Form(''), s=Depends(service)):
    """A product or accessory photographed before its device record exists; claimed at intake."""
    data = await read_upload(file)
    return Ok(id=CustomerRecords(s).save_photo(data, customer_id, role, description))


@router.get('/drafts', response_model=list[Draft])
def drafts(s=Depends(service)):
    return CustomerRecords(s).drafts()


@router.get('/drafts/{ident}', response_model=Draft)
def draft(ident: str, s=Depends(service)):
    from repairshop.domain import NotFound
    row = next((d for d in CustomerRecords(s).drafts() if d['id'] == ident), None)
    if not row:
        raise NotFound('Draft not found.')
    return dict(row, payload=json.loads(row['payload']))


@router.put('/drafts/{ident}', response_model=Ok)
def save_draft(ident: str, values: DraftIn, s=Depends(service)):
    CustomerRecords(s).save_draft(ident, values.payload)
    return Ok()


@router.post('/visits', response_model=VisitOut)
def receive(values: VisitIn, s=Depends(service)):
    products = [p.model_dump(exclude_none=True) for p in values.products]
    for p in products:
        p['accessories'] = [dict(a, checked=True) for a in p.get('accessories', [])]
        if values.intake_ref:
            p['intake_ref'] = values.intake_ref
    prepared = prepare_visit(products, amounts_in_paise=True)
    job_ids = s.intake_visit(prepared, values.operation_id, draft_id=values.draft_id, notes=values.notes)
    jobs = [s.job(i) for i in job_ids]
    from repairshop.visits import Visits
    visit = Visits(s).for_job(job_ids[0])
    follow = after_intake(s, job_ids)
    return VisitOut(jobs=jobs, visit={k: visit[k] for k in ('id', 'number', 'status')} if visit else None, **follow)
