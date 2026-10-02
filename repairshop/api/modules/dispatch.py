"""Dispatch records and physical custody.

A dispatch is administrative information about sending a repair's items out; it never
moves custody by itself. Custody changes only through recorded handovers (the guided
dispatch / arrive / receive steps, or the general handover below), each idempotent by
operation id. Choosing a repair partner is an assignment and moves nothing.
"""
import uuid
from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from repairshop.dispatch import (Dispatches, TRANSPORT_METHODS, TRANSPORT_MODES, TRANSPORT_REQUIRED, TRANSPORT_LABELS,
                                 TRANSPORT_PAYERS, TRANSPORT_DATES, TRANSPORT_TIMES)
from repairshop.queries import Queries
from repairshop.readmodels import ReadModels
from ..deps import service
from ..schemas import Model, Ok

router = APIRouter(tags=['dispatch'])


class DispatchDetail(Model):
    id: int
    job_id: int
    cycle: int
    version: int
    current: bool
    status: str
    route: str
    contact_id: int | None = None
    party: str | None = None
    contact_snapshot: dict[str, Any] = {}
    transporter_id: int | None = None
    transporter: str = ''
    transporter_snapshot: dict[str, Any] = {}
    reference: str = ''
    transport_mode: str
    transport: dict[str, Any] = {}
    transport_summary: str = ''
    carrier: str = ''
    amount: int
    paid_by: str
    expected_return: str | None = None
    condition: str = ''
    notes: str = ''
    manifest: list[int] = []
    actual_dispatch_at: str | None = None
    amendment_reason: str = ''
    supersedes_id: int | None = None
    editable: bool
    created: str


class Attempt(Model):
    attempt: int
    assignment_id: int
    contact_id: int | None = None
    partner: str | None = None
    snapshot: dict[str, Any] = {}
    route: str
    reference: str = ''
    expected_return: str | None = None
    instructions: str = ''
    assigned: str
    sent: str | None = None
    returned: str | None = None
    result: str
    current: bool


class DispatchOverview(BaseModel):
    current: DispatchDetail | None
    history: list[DispatchDetail]
    attempts: list[Attempt]


class DispatchIn(BaseModel):
    """Transport fields depend on the method; see GET /api/dispatch/methods. Money is paise."""
    transport_mode: str | None = None
    transport: dict[str, str] | None = None
    transporter_id: int | None = None
    amount: int | None = Field(None, ge=0)
    paid_by: str | None = None
    reference: str | None = None
    expected_return: str | None = None
    condition: str | None = None
    notes: str | None = None
    manifest: list[int] | None = None


class AmendIn(BaseModel):
    values: DispatchIn
    reason: str = Field(min_length=1)
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1)


class MoveIn(BaseModel):
    item_id: int
    quantity: int = Field(ge=1)
    source: str
    destination: str
    counterparty: str = Field(min_length=1)
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80)
    reference: str = ''
    condition: str = ''
    notes: str = ''
    acknowledgment: str = ''


@router.get('/dispatch/methods')
def methods():
    """The single transport model: each method, its fields, which are required and how they are typed."""
    def kind(key):
        return 'date' if key in TRANSPORT_DATES else 'time' if key in TRANSPORT_TIMES else 'text'
    return dict(methods=[dict(key=key, label=TRANSPORT_METHODS[key], uses_bus_service=key == 'BUS',
                              free_text_company=key == 'COURIER',
                              fields=[dict(key=f, label=TRANSPORT_LABELS[f], type=kind(f), required=f in TRANSPORT_REQUIRED[key])
                                      for f in TRANSPORT_MODES[key]])
                         for key in TRANSPORT_METHODS],
                payers=[dict(value=k, label=v) for k, v in TRANSPORT_PAYERS.items()])


@router.get('/dispatch/courier-suggestions', response_model=list[str])
def courier_suggestions(s=Depends(service)):
    """Courier companies used before. Suggestions only: any company may be typed."""
    return Dispatches(s).courier_suggestions()


@router.get('/repairs/{ident}/dispatch', response_model=DispatchOverview)
def overview(ident: int, s=Depends(service)):
    d = Dispatches(s)
    return DispatchOverview(current=d.current(ident), history=d.history(ident), attempts=d.attempts(ident))


@router.patch('/repairs/{ident}/dispatch', response_model=DispatchOverview)
def edit(ident: int, values: DispatchIn, s=Depends(service)):
    """Correct a dispatch that has not physically left yet."""
    Dispatches(s).edit(ident, values.model_dump(exclude_none=True))
    return overview(ident, s)


@router.post('/repairs/{ident}/dispatch/amend', response_model=DispatchOverview)
def amend(ident: int, body: AmendIn, s=Depends(service)):
    """Correct a sent dispatch with a new version; the original and the custody ledger stay."""
    Dispatches(s).amend(ident, body.values.model_dump(exclude_none=True), body.reason, operation_id=body.operation_id)
    return overview(ident, s)


@router.post('/repairs/{ident}/dispatch/cancel', response_model=DispatchOverview)
def cancel(ident: int, body: ReasonIn, s=Depends(service)):
    Dispatches(s).cancel(ident, body.reason)
    return overview(ident, s)


@router.get('/custody/holdings')
def holdings(job_id: int | None = None, s=Depends(service)):
    """Items currently held, by whom, limited to repairs this user may see."""
    rows = Queries(s).holdings(job_id=job_id, movable=True)
    for row in rows:
        row['holder'] = s.custodian(row['location'])
    return rows


@router.get('/custody/destinations')
def destinations(s=Depends(service)):
    return ReadModels(s).custody_destinations()


@router.post('/custody/movements', response_model=Ok)
def move(body: MoveIn, s=Depends(service)):
    """Record one actual handover. Retrying with the same operation_id records it once."""
    return Ok(id=s.move(body.item_id, body.quantity, body.source, body.destination, body.counterparty,
                        body.operation_id, reference=body.reference, condition=body.condition,
                        notes=body.notes, acknowledgment=body.acknowledgment))
