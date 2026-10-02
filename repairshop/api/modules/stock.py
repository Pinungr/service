"""Shop inventory, repair parts and device warranties. Money is whole paise."""
import uuid
from typing import Any, Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from repairshop.inventory import Inventory
from repairshop.parts import Parts
from repairshop.warranties import Warranties
from ..deps import service
from ..schemas import Ok

router = APIRouter(tags=['inventory'])


class StockIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = ''
    brand: str = ''
    model: str = ''
    part_number: str = ''
    compatibility: str = ''
    serialized: bool = False
    serial: str = ''
    batch: str = ''
    category_id: int | None = None
    supplier_id: int | None = None
    invoice: str = ''
    purchase_date: str | None = None
    storage: str = 'Stock shelf'
    minimum_stock: int = Field(0, ge=0)
    purchase_cost: int = Field(0, ge=0)
    customer_price: int | None = Field(None, ge=0)
    markup_basis_points: int | None = Field(None, ge=0)
    warranty_duration: int = Field(0, ge=0)
    warranty_unit: str = 'months'
    warranty_provider: str = ''
    warranty_terms: str = ''
    notes: str = ''
    active: bool = True


class AdjustIn(BaseModel):
    quantity: int
    reference: str = Field(min_length=1)
    notes: str = ''
    kind: Literal['STOCK_RECEIVED', 'STOCK_ADJUSTMENT', 'DAMAGED', 'SCRAPPED', 'WARRANTY_REPLACEMENT', 'CUSTOMER_RETURN'] = 'STOCK_RECEIVED'
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80)


class PartIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    part_type: str = ''
    brand: str = ''
    model: str = ''
    part_number: str = ''
    serial: str = ''
    quantity: int = Field(1, ge=1)
    source: Literal['stock', 'supplier', 'technician', 'other']
    inventory_id: int | None = None
    supplier_id: int | None = None
    invoice: str = ''
    purchase_date: str | None = None
    purchase_cost: int = Field(0, ge=0)
    customer_price: int = Field(0, ge=0)
    warranty_duration: int = Field(0, ge=0)
    warranty_unit: str = 'months'
    warranty_provider: str = ''
    warranty_terms: str = ''
    requested_by: str = ''
    request_notes: str = ''
    notes: str = ''


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1)


class InstallIn(BaseModel):
    installed_by: str = Field(min_length=1)
    installed_date: str | None = None


class TransferIn(BaseModel):
    action: Literal['reserve', 'issue', 'return', 'release', 'damaged', 'scrapped']
    reference: str = ''
    notes: str = ''


class ProcureIn(BaseModel):
    action: Literal['order', 'receive']
    reference: str = ''


class RepairWarrantyIn(BaseModel):
    name: str = 'Repair workmanship'
    start_date: str
    duration: int = Field(ge=0)
    unit: Literal['days', 'months', 'years'] = 'months'
    provider: str
    terms: str = ''


class WarrantyEditIn(BaseModel):
    reason: str = Field(min_length=1)
    privileged_override: bool = False
    duration: int | None = Field(None, ge=0)
    unit: Literal['days', 'months', 'years'] | None = None
    start_date: str | None = None
    status: Literal['ACTIVE', 'VOID', 'REPLACED'] | None = None
    provider: str | None = None
    terms: str | None = None
    notes: str | None = None


class ClaimIn(BaseModel):
    warranty_id: int
    complaint: str = Field(min_length=1)
    override_reason: str = ''


class ClaimUpdateIn(BaseModel):
    status: Literal['OPEN', 'ACCEPTED', 'REJECTED', 'IN_REPAIR', 'REPLACED', 'COMPLETED', 'CLOSED']
    resolution: str = ''
    replacement_part_id: int | None = None


class ManualCheckIn(BaseModel):
    result: Literal['VALID', 'INVALID', 'UNVERIFIED'] = 'UNVERIFIED'
    evidence_type: str
    reference: str = ''
    provider: str = ''
    coverage: Literal['manufacturer', 'shop_part', 'shop_repair', 'supplier', 'vendor'] = 'shop_part'
    notes: str = ''
    attachment_id: int | None = None


# ---- inventory ---------------------------------------------------------------

@router.get('/inventory')
def inventory(search: str = Query('', max_length=80), view: Literal['all', 'low', 'out'] = 'all', s=Depends(service)):
    return Inventory(s).rows(search, view)


@router.post('/inventory', response_model=Ok)
def create_stock(values: StockIn, s=Depends(service)):
    return Ok(id=Inventory(s).save(values.model_dump(exclude_none=True)))


@router.put('/inventory/{ident}', response_model=Ok)
def update_stock(ident: int, values: StockIn, s=Depends(service)):
    return Ok(id=Inventory(s).save(values.model_dump(exclude_none=True), ident))


@router.post('/inventory/{ident}/adjust', response_model=Ok)
def adjust(ident: int, values: AdjustIn, s=Depends(service)):
    qty = -abs(values.quantity) if values.kind in ('DAMAGED', 'SCRAPPED') else values.quantity
    return Ok(id=Inventory(s).adjust(ident, qty, values.reference, values.notes, kind=values.kind, operation_id=values.operation_id))


@router.get('/inventory/movements')
def movements(stock_id: int | None = None, job_id: int | None = None, s=Depends(service)):
    return Inventory(s).movements(stock_id=stock_id, job_id=job_id)


# ---- repair parts -------------------------------------------------------------

@router.get('/repairs/{ident}/parts')
def parts(ident: int, s=Depends(service)):
    return Parts(s).rows(ident)


@router.post('/repairs/{ident}/parts', response_model=Ok)
def plan_part(ident: int, values: PartIn, s=Depends(service)):
    data = values.model_dump()
    if data['source'] == 'stock':
        data.pop('supplier_id', None)
    return Ok(id=Parts(s).save(ident, data))


@router.put('/repairs/{ident}/parts/{part_id}', response_model=Ok)
def revise_part(ident: int, part_id: int, values: PartIn, s=Depends(service)):
    data = values.model_dump()
    if data['source'] == 'stock':
        data.pop('supplier_id', None)
    return Ok(id=Parts(s).save(ident, data, part_id))


@router.post('/parts/{ident}/remove', response_model=Ok)
def remove_part(ident: int, values: ReasonIn, s=Depends(service)):
    Parts(s).remove(ident, values.reason)
    return Ok(id=ident)


@router.post('/parts/{ident}/install', response_model=Ok)
def install_part(ident: int, values: InstallIn, s=Depends(service)):
    Parts(s).install(ident, values.installed_by, values.installed_date)
    return Ok(id=ident)


@router.post('/parts/{ident}/transfer', response_model=Ok)
def transfer_part(ident: int, values: TransferIn, s=Depends(service)):
    """Reserve / issue / return / release shop stock for a part, or write it off (owner)."""
    Inventory(s).transfer(ident, values.action, values.reference, values.notes)
    return Ok(id=ident)


@router.post('/parts/{ident}/procure', response_model=Ok)
def procure_part(ident: int, values: ProcureIn, s=Depends(service)):
    Parts(s).procure(ident, values.action, values.reference)
    return Ok(id=ident)


# ---- warranties ---------------------------------------------------------------

@router.get('/repairs/{ident}/warranty')
def warranty(ident: int, s=Depends(service)) -> dict[str, Any]:
    """Intake warranty report, this device's part / repair warranties, claims and manual checks."""
    import json
    job = s.job(ident)
    w = Warranties(s)
    return dict(intake=json.loads(job['lifecycle_data']).get('intake_warranty'),
                warranties=w.rows(job['device_id']) if job['device_id'] else [],
                claims=w.claims(job['device_id']) if job['device_id'] else [],
                manual_checks=w.manual_checks(ident))


@router.post('/repairs/{ident}/warranty/repair', response_model=Ok)
def repair_warranty(ident: int, values: RepairWarrantyIn, s=Depends(service)):
    return Ok(id=Warranties(s).repair_warranty(ident, **values.model_dump()))


@router.patch('/warranties/{ident}', response_model=Ok)
def edit_warranty(ident: int, values: WarrantyEditIn, s=Depends(service)):
    data = values.model_dump(exclude_none=True)
    Warranties(s).edit(ident, data.pop('reason'), data.pop('privileged_override'), **data)
    return Ok(id=ident)


@router.post('/repairs/{ident}/warranty/claims', response_model=Ok)
def claim(ident: int, values: ClaimIn, s=Depends(service)):
    return Ok(id=Warranties(s).claim(ident, values.warranty_id, values.complaint, values.override_reason))


@router.patch('/warranty-claims/{ident}', response_model=Ok)
def update_claim(ident: int, values: ClaimUpdateIn, s=Depends(service)):
    Warranties(s).update_claim(ident, values.status, values.resolution, values.replacement_part_id)
    return Ok(id=ident)


@router.post('/repairs/{ident}/warranty/manual-checks', response_model=Ok)
def manual_check(ident: int, values: ManualCheckIn, s=Depends(service)):
    return Ok(id=Warranties(s).manual_check(ident, **values.model_dump()))
