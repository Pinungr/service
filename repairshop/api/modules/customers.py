"""Customers, their devices and their photos."""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from repairshop.customer_records import CustomerRecords
from repairshop.queries import Queries
from repairshop.readmodels import ReadModels
from ..deps import service
from ..errors import ApiError
from ..schemas import Model, Ok, Page, page

router = APIRouter(tags=['customers'])
MAX_UPLOAD = 50 * 1024 ** 2


class CustomerSummary(Model):
    id: int
    name: str
    phone: str
    email: str = ''
    address: str = ''


class Customer(Model):
    id: int
    name: str
    phone: str
    alternate: str = ''
    email: str = ''
    address: str = ''
    address_line1: str = ''
    address_line2: str = ''
    pincode: str = ''
    district: str = ''
    state: str = ''
    whatsapp_consent: bool = False
    email_consent: bool = False
    current_photo_id: int | None = None
    created: str


class CustomerIn(BaseModel):
    name: str | None = Field(None, max_length=200)
    phone_number: str | None = Field(None, max_length=40)
    alternate: str | None = Field(None, max_length=40)
    email: str | None = Field(None, max_length=200)
    whatsapp_consent: bool | None = None
    email_consent: bool | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    pincode: str | None = None
    district: str | None = None
    state: str | None = None
    #: Quick counter registration records a name and number now, the address later.
    complete: bool = True
    #: Set after staff confirm this is a different person who shares a phone number.
    confirm_shared_phone: bool = False


class Device(Model):
    id: int
    customer_id: int
    name: str
    category_id: int | None = None
    brand: str = ''
    model: str = ''
    serial: str = ''


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str = ''
    model: str = ''
    serial: str = ''


class Photo(Model):
    id: int
    kind: str
    title: str
    person_role: str | None = None
    captured: str | None = None
    created: str
    job_id: int | None = None
    device_id: int | None = None


class Overview(BaseModel):
    customer: Customer
    counts: dict[str, int]
    all_ready: bool
    outstanding: list[dict]
    history: list[dict]
    visits: list[dict]
    devices: list[Device]
    photos: list[Photo]


JOB_FIELDS = ('id', 'number', 'product', 'device_id', 'stage', 'route_label', 'current_status', 'current_location',
              'next_action', 'responsible', 'collection_status', 'tentative_collection', 'balance', 'ready',
              'received', 'last_update', 'visit_id')


async def read_upload(upload: UploadFile):
    data = await upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, 'FILE_TOO_LARGE', 'Choose a file smaller than 50 MB.')
    return data


def _address(values):
    return {k: getattr(values, k) for k in ('address_line1', 'address_line2', 'pincode', 'district', 'state')
            if getattr(values, k) is not None}


@router.get('/customers', response_model=Page)
def customers(search: str = Query('', max_length=80), offset: int = Query(0, ge=0), s=Depends(service)):
    rows = Queries(s).customers(search.strip(), offset)
    return page(rows, offset, 50, CustomerSummary).model_copy(update={'has_more': len(rows) == 50})


@router.get('/customers/phone-matches', response_model=list[CustomerSummary])
def phone_matches(phone: str = Query(..., max_length=40), exclude_id: int | None = None, s=Depends(service)):
    return ReadModels(s).customers_with_phone(phone, exclude_id)


@router.post('/customers', response_model=Customer)
def create_customer(values: CustomerIn, s=Depends(service)):
    matches = ReadModels(s).customers_with_phone(values.phone_number or '') if values.phone_number else []
    if matches and not values.confirm_shared_phone:
        raise ApiError(409, 'DUPLICATE_PHONE', 'An existing customer uses this phone number. Use their record, '
                       'or confirm that this is a different person sharing the number.')
    ident = s.save_customer(values.name, values.phone_number, values.email, None, values.whatsapp_consent,
                            values.email_consent, values.alternate, complete=values.complete, **_address(values))
    return ReadModels(s).customer(ident)


@router.patch('/customers/{ident}', response_model=Customer)
def update_customer(ident: int, values: CustomerIn, s=Depends(service)):
    if values.phone_number:
        matches = ReadModels(s).customers_with_phone(values.phone_number, ident)
        if matches and not values.confirm_shared_phone:
            raise ApiError(409, 'DUPLICATE_PHONE', 'Another customer uses this phone number. Confirm that this is intended.')
    s.save_customer(values.name, values.phone_number, values.email, None, values.whatsapp_consent,
                    values.email_consent, values.alternate, ident=ident, complete=values.complete, **_address(values))
    return ReadModels(s).customer(ident)


@router.get('/customers/{ident}', response_model=Overview)
def overview(ident: int, s=Depends(service)):
    data = CustomerRecords(s).overview(ident)
    trim = lambda rows: [{k: r.get(k) for k in JOB_FIELDS} for r in rows]
    return Overview(customer=data['customer'], counts=data['counts'], all_ready=data['all_ready'],
                    outstanding=trim(data['outstanding']), history=trim(data['history']), visits=data['visits'],
                    devices=data['devices'], photos=data['photos'])


@router.get('/customers/{ident}/sales')
def customer_sales(ident: int, s=Depends(service)):
    return Queries(s).customer_sales(ident)


@router.get('/customers/{ident}/quotes')
def customer_quotes(ident: int, s=Depends(service)):
    return Queries(s).customer_quotes(ident)


@router.get('/customers/{ident}/payments')
def customer_payments(ident: int, s=Depends(service)):
    return Queries(s).customer_payments(ident)


@router.get('/customers/{ident}/messages')
def customer_messages(ident: int, s=Depends(service)):
    return Queries(s).customer_messages(ident)


@router.post('/customers/{ident}/photos', response_model=Ok)
async def customer_photo(ident: int, file: UploadFile = File(...), role: str = Form('owner'),
                         person_name: str = Form(''), captured: str | None = Form(None), s=Depends(service)):
    """Owner / submitter / product / accessory photos captured or uploaded at the counter."""
    data = await read_upload(file)
    return Ok(id=CustomerRecords(s).save_photo(data, ident, role, person_name, captured=captured))


@router.patch('/devices/{ident}', response_model=Device)
def update_device(ident: int, values: DeviceIn, s=Depends(service)):
    CustomerRecords(s).update_device(ident, values.name, values.brand, values.model, values.serial)
    return ReadModels(s).device(ident)


@router.get('/devices/{ident}/photos', response_model=list[Photo])
def device_photos(ident: int, s=Depends(service)):
    return ReadModels(s).device_photos(ident)


@router.post('/devices/{ident}/photos', response_model=Ok)
async def device_photo(ident: int, file: UploadFile = File(...), job_id: int | None = Form(None), s=Depends(service)):
    data = await read_upload(file)
    device = ReadModels(s).device(ident)
    return Ok(id=CustomerRecords(s).save_photo(data, device['customer_id'], 'product', device_id=ident, job_id=job_id))


@router.post('/repairs/{ident}/return-photos', response_model=Ok)
async def return_photo(ident: int, file: UploadFile = File(...), description: str = Form(...), s=Depends(service)):
    """Evidence of what came back from a repairer, filed with this repair."""
    data = await read_upload(file)
    job = s.job(ident)
    return Ok(id=CustomerRecords(s).save_photo(data, job['customer_id'], 'return', description, job_id=ident))
