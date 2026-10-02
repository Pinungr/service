"""Contacts & Services: reusable partners, suppliers, bus services and shop setup lists.

Configure once, select many times. Every rule (required fields, duplicate detection,
recommendation ranking, snapshots, inactive handling) is the existing `Contacts`
service; this module only names the operations and shapes the responses.
"""
from typing import Any, Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from repairshop.contacts import Contacts, DuplicateContact, CONTACT_KINDS, SETUP_KINDS, PROFILE_FIELDS, label
from repairshop.readmodels import ReadModels
from ..deps import service
from ..errors import ApiError
from ..schemas import Model, Ok

router = APIRouter(tags=['contacts'])
Kind = Literal['vendor', 'centre', 'supplier', 'transporter']
SetupKind = Literal['technician', 'service', 'category', 'brand', 'model', 'accessory', 'payment_method']


class ContactSummary(Model):
    id: int
    kind: str
    name: str
    mobile: str
    contact_person: str = ''
    location: str = ''
    works_on: str = ''
    route_from: str = ''
    route_to: str = ''
    pickup_point: str = ''
    drop_point: str = ''
    vehicle_number: str = ''
    active: bool
    status: str


class ContactDetail(Model):
    id: int
    kind: str
    kind_label: str
    name: str
    mobile: str
    alternate: str = ''
    contact_person: str = ''
    email: str = ''
    address_line1: str = ''
    address_line2: str = ''
    city: str = ''
    district: str = ''
    state: str = ''
    pincode: str = ''
    specialization: str = ''
    notes: str = ''
    warranty_service: bool = False
    pickup: bool = False
    turnaround_days: int = 0
    route_from: str = ''
    route_to: str = ''
    pickup_point: str = ''
    drop_point: str = ''
    vehicle_number: str = ''
    photo_id: int | None = None
    supports: list[int] = []
    brands: list[str] = []
    active: bool
    summary: str
    activity: dict[str, Any]
    created: str | None = None
    updated: str | None = None


class ContactOption(Model):
    id: int
    name: str
    secondary: str
    headline: str
    summary: str
    recommended: bool
    reasons: list[str]
    snapshot: dict[str, Any]


class Options(BaseModel):
    recommended: list[ContactOption]
    others: list[ContactOption]


class ContactIn(BaseModel):
    """Only name and mobile are required; everything else can be completed later."""
    kind: Kind | None = None
    name: str | None = Field(None, max_length=200)
    mobile: str | None = Field(None, max_length=40)
    alternate: str | None = None
    contact_person: str | None = None
    email: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    district: str | None = None
    state: str | None = None
    pincode: str | None = None
    specialization: str | None = None
    notes: str | None = None
    warranty_service: bool | None = None
    pickup: bool | None = None
    turnaround_days: int | None = Field(None, ge=0, le=365)
    route_from: str | None = None
    route_to: str | None = None
    pickup_point: str | None = None
    drop_point: str | None = None
    vehicle_number: str | None = None
    supports: list[int] | None = None
    brands: str | None = Field(None, description='Comma-separated brand names; unknown brands are added.')
    active: bool | None = None
    photo_id: int | None = None
    #: After a probable-duplicate warning, the user chose "Create anyway".
    allow_duplicate: bool = False


class QuickCreateIn(BaseModel):
    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    mobile: str = Field(min_length=1, max_length=40)
    specialization: str | None = None
    brands: str | None = None
    city: str | None = None
    route_from: str | None = None
    route_to: str | None = None
    vehicle_number: str | None = None
    job_id: int | None = Field(None, description='The repair this contact was created from, recorded in its history.')
    allow_duplicate: bool = False


class SetupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: str = ''
    details: str = ''
    active: bool = True
    category_id: int | None = None
    category_ids: list[int] | None = None
    user_id: int | None = None


def duplicate_error(found: DuplicateContact):
    matches = [dict(id=m['id'], name=m['name'], secondary=m.get('secondary', ''), reasons=m['reasons'],
                    exact=m['exact'], active=bool(m['active'])) for m in found.matches]
    return ApiError(409, 'DUPLICATE_CONTACT', str(found), matches=matches)


def detail(s, ident):
    contacts = Contacts(s)
    row = contacts.get(ident)
    if not row or row['kind'] not in CONTACT_KINDS:
        raise ApiError(404, 'NOT_FOUND', 'Contact not found.')
    from repairshop.contacts import summary
    brands = row['snapshot'].get('brand_supported', [])
    return ContactDetail(**{**row, 'mobile': row['contact'], 'kind_label': label(row['kind']), 'brands': brands,
                            'summary': summary(row['snapshot']), 'activity': contacts.activity(ident)})


def values_of(body: BaseModel, kind):
    allowed = set(PROFILE_FIELDS[kind]) | {'name', 'mobile', 'supports', 'brands', 'active', 'photo_id',
                                            'address_line1', 'address_line2', 'district', 'state', 'pincode'}
    if kind == 'transporter':
        allowed -= {'address_line1', 'address_line2', 'district', 'state', 'pincode', 'brands', 'supports'}
    if kind not in ('vendor', 'centre'):
        allowed -= {'brands', 'supports'}
    data = body.model_dump(exclude_none=True, exclude={'kind', 'allow_duplicate', 'job_id'})
    unknown = set(data) - allowed
    if unknown:
        raise ApiError(400, 'NOT_APPLICABLE', 'These details do not apply to a ' + label(kind).lower() + ': '
                       + ', '.join(sorted(unknown)))
    return data


@router.get('/contacts/kinds')
def kinds():
    return dict(contacts=[dict(kind=k, label=v, fields=list(PROFILE_FIELDS[k])) for k, v in CONTACT_KINDS.items()],
                setup=[dict(kind=k, label=v) for k, v in SETUP_KINDS.items()])


@router.get('/contacts', response_model=list[ContactSummary])
def contacts(kind: Kind, search: str = Query('', max_length=80), include_inactive: bool = False, s=Depends(service)):
    return Contacts(s).directory(kind, search, include_inactive)


@router.get('/contacts/options', response_model=Options)
def options(kind: Kind, job_id: int | None = None, search: str = Query('', max_length=80), s=Depends(service)):
    """Active contacts for a selector, the ones relevant to this repair first. Nothing is hidden."""
    if job_id:
        s.require_job_access(job_id)
    rows = Contacts(s).options(kind, job_id, search)
    return Options(recommended=[r for r in rows if r['recommended']], others=[r for r in rows if not r['recommended']])


@router.get('/contacts/duplicates')
def duplicates(kind: Kind, name: str, mobile: str = '', city: str = '', s=Depends(service)):
    return [dict(id=m['id'], name=m['name'], secondary=m.get('secondary', ''), reasons=m['reasons'],
                 exact=m['exact'], active=bool(m['active'])) for m in Contacts(s).duplicates(kind, name, mobile, city)]


@router.get('/contacts/{ident}', response_model=ContactDetail)
def contact(ident: int, s=Depends(service)):
    return detail(s, ident)


@router.post('/contacts', response_model=ContactDetail)
def create(body: ContactIn, s=Depends(service)):
    if not body.kind:
        raise ApiError(422, 'VALIDATION_ERROR', 'Choose the kind of contact.', 'kind')
    contacts = Contacts(s)
    data = values_of(body, body.kind)
    if not body.allow_duplicate:
        found = contacts.duplicates(body.kind, data.get('name', ''), data.get('mobile', ''), data.get('city', ''))
        if found:
            raise duplicate_error(DuplicateContact(found))
    return detail(s, contacts.save(body.kind, data))


@router.patch('/contacts/{ident}', response_model=ContactDetail)
def update(ident: int, body: ContactIn, s=Depends(service)):
    current = detail(s, ident)
    data = values_of(body, current.kind)
    merged = {k: getattr(current, k) for k in ('name', 'mobile')}
    merged.update(data)
    Contacts(s).save(current.kind, merged, ident=ident)
    return detail(s, ident)


@router.post('/contacts/{ident}/activate', response_model=ContactDetail)
def activate(ident: int, s=Depends(service)):
    detail(s, ident)
    Contacts(s).set_active(ident, True)
    return detail(s, ident)


@router.post('/contacts/{ident}/deactivate', response_model=ContactDetail)
def deactivate(ident: int, s=Depends(service)):
    """History keeps the record and every snapshot; it only leaves the selectors."""
    detail(s, ident)
    Contacts(s).set_active(ident, False)
    return detail(s, ident)


@router.post('/contacts/quick-create', response_model=ContactOption)
def quick_create(body: QuickCreateIn, s=Depends(service)):
    """Create from inside a repair and return it ready to select (Save & Select)."""
    extra = body.model_dump(exclude_none=True, exclude={'kind', 'name', 'mobile', 'job_id', 'allow_duplicate'})
    allowed = set(PROFILE_FIELDS[body.kind]) | ({'brands'} if body.kind in ('vendor', 'centre') else set())
    extra = {k: v for k, v in extra.items() if k in allowed and v}
    if body.job_id:
        s.require_job_access(body.job_id)
    try:
        ident = Contacts(s).quick_create(body.kind, body.name, body.mobile, allow_duplicate=body.allow_duplicate,
                                         job_id=body.job_id, **extra)
    except DuplicateContact as found:
        raise duplicate_error(found)
    option = next(r for r in Contacts(s).options(body.kind, body.job_id) if r['id'] == ident)
    return option


# ---- Shop setup lists ---------------------------------------------------------

@router.get('/setup/{kind}')
def setup_list(kind: SetupKind, include_inactive: bool = True, s=Depends(service)):
    return ReadModels(s).setup_list(kind, include_inactive)


@router.post('/setup/{kind}', response_model=Ok)
def setup_create(kind: SetupKind, body: SetupIn, s=Depends(service)):
    return Ok(id=s.save_master(kind, **body.model_dump(exclude_none=True)))


@router.patch('/setup/{kind}/{ident}', response_model=Ok)
def setup_update(kind: SetupKind, ident: int, body: SetupIn, s=Depends(service)):
    return Ok(id=s.save_master(kind, **body.model_dump(exclude_none=True), ident=ident))
