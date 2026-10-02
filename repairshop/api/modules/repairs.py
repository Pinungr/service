"""Repair jobs: lists, the workspace snapshot, the journey and guided actions.

Every decision comes from `Lifecycle`: the allowed actions, the primary action, the
journey states and every transition rule. Actions are commands, never field updates:
there is no endpoint that sets a stage, route, custody location or payment state.
"""
from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from repairshop.action_forms import ActionForms
from repairshop.journey_model import build_journey
from repairshop.lifecycle import Lifecycle, ACTIONS, LABELS
from repairshop.queries import Queries
from repairshop.readmodels import ReadModels
from repairshop.visits import Visits
from ..deps import service
from ..errors import ApiError
from ..schemas import Command, Model, Page, page

router = APIRouter(prefix='/repairs', tags=['repairs'])

#: How the workspace groups secondary actions. Presentation only; availability is the lifecycle's.
GROUPS = {'adopt': 'exception', 'change_route': 'exception', 'decline': 'exception', 'repair_failed': 'exception',
          'rework': 'exception', 'resolve_item': 'exception', 'details': 'exception',
          'parts': 'tool', 'manual_warranty': 'tool', 'costing': 'tool', 'hand_over': 'tool'}
FILTERS = [('', 'All active repairs'), ('ready', 'Ready for delivery'), ('attention', 'Attention required'),
           ('external_centre', 'At service centre'), ('external_vendor', 'With third party'), ('in_house', 'In-house'),
           ('warranty_claims', 'Warranty claims'), ('overdue', 'Overdue'), ('history', 'All repair history')]


class RepairSummary(Model):
    id: int
    number: str
    visit: str | None = None
    customer: str
    phone: str
    device: str
    device_id: int | None = None
    route: str
    status: str
    location: str
    responsible: str
    current_custodian: str
    stage_age: str
    expected_date: str | None = None
    balance: int = 0
    estimate: int = 0
    next_action: str
    attention: str


class ActionRef(Model):
    key: str
    label: str
    group: str = 'step'
    primary: bool = False


class Assignment(Model):
    id: int | None = None
    route: str | None = None
    contact_id: int | None = None
    party: str | None = None
    contact: str | None = None
    summary: str | None = None
    partner: dict[str, Any] = {}
    reference: str | None = None
    expected_return: str | None = None
    instructions: str | None = None
    technician: str | None = None


class Custodian(Model):
    name: str
    kind: str
    role: str
    location: str


class RepairDetail(Model):
    id: int
    number: str
    version: int
    stage: str
    stage_label: str
    route: str
    route_label: str
    current_status: str
    customer_id: int
    customer: str
    phone: str
    device: str
    device_id: int | None = None
    serial: str
    complaint: str
    damage: str
    customer_requirement: str = ''
    received: str
    received_by: str
    visit_number: str | None = None
    warranty_status: str
    responsible: str
    assigned_technician: str
    current_custodian: str
    custodian_role: str
    custodian_since: str | None = None
    custodians: list[Custodian]
    current_location: str
    final_destination: str
    at_shop: bool
    away: bool
    next_action: str
    primary: str
    actions: list[ActionRef]
    attention: list[str]
    assignment: Assignment
    quote: dict[str, Any] = {}
    balance: int
    paid: int
    initial_estimate: int = 0
    deposit: int = 0
    repair_due: str | None = None
    collection_due: str | None = None
    return_due: str | None = None
    hold_reason: str = ''
    legacy: bool
    current_card: str
    warranty_indicator: str
    open_claims: int = 0
    record: dict[str, Any] = Field(default_factory=dict, description='Diagnosis, repair, QC and intake-warranty facts.')
    vendor_payments: bool = False


class JourneyNode(Model):
    key: str
    label: str
    status: str
    detail: str = ''
    current: bool = False
    options: list[str] = []
    events: list[dict[str, Any]] = []
    action: ActionRef | None = None


class Journey(Model):
    repair_id: int
    job_number: str
    version: int
    current_stage: str
    route: str
    route_label: str
    next_action: str
    nodes: list[JourneyNode]


class TimelineEvent(Model):
    id: int
    created: str
    actor: str | None = None
    action: str
    event: str
    details: str


class ActionResult(BaseModel):
    replayed: bool
    repair: RepairDetail


class DatesIn(BaseModel):
    expected_version: int
    repair_due: str | None = None
    collection_due: str | None = None
    return_due: str | None = None
    duration_days: int | None = None
    reference_date: str | None = None
    reason: str = Field(min_length=1)


class HoldIn(BaseModel):
    reason: str = ''


RECORD_KEYS = ('diagnosis', 'parts_required', 'parts_available', 'parts_used', 'repair_summary', 'unrepaired',
               'repair_warranty', 'warranty_until', 'intake_warranty', 'inspection', 'replacement', 'return_result',
               'route_details', 'technician_bench', 'dispatched', 'returned', 'repair_started', 'repair_completed',
               'notified', 'handover', 'legacy_review')


def detail(s, ident):
    v = Lifecycle(s).snapshot(ident)
    data = v['data']
    record = {k: data[k] for k in RECORD_KEYS if k in data}
    if 'qc' in data:
        record['qc'] = {k: data['qc'].get(k) for k in ('result', 'checks', 'notes', 'created', 'actor')}
    a = v['assignment'] or {}
    return RepairDetail(**{**v, 'stage_label': LABELS.get(v['stage'], v['stage']),
                           'received_by': (v.get('received_by') or {}).get('name') or 'Not recorded',
                           'actions': [ActionRef(key=k, label=ACTIONS.get(k, k), group=GROUPS.get(k, 'step'), primary=k == v['primary'])
                                       for k in v['actions']],
                           'assignment': Assignment(**{**a, 'technician': a.get('technician')}),
                           'quote': {k: v['quote'].get(k) for k in ('id', 'version', 'state', 'total', 'valid_until', 'scope')} if v['quote'] else {},
                           'legacy': not v['lifecycle_version'], 'record': record,
                           'vendor_payments': s.may('vendor_accounts') and v['route'] != 'in_house'})


@router.get('', response_model=Page)
def repairs(search: str = Query('', max_length=80), filter: str = Query('', alias='filter', max_length=40),
            offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), s=Depends(service)):
    rows = Lifecycle(s).rows(search, filter, offset, limit + 1)
    return page(rows, offset, limit, RepairSummary)


@router.get('/filters')
def filters(s=Depends(service)):
    """The list filters, including one per lifecycle stage."""
    return [dict(value=k, label=l) for k, l in FILTERS] + [dict(value=k, label=l.title()) for k, l in LABELS.items()]


@router.get('/{ident}', response_model=RepairDetail)
def repair(ident: int, s=Depends(service)):
    return detail(s, ident)


@router.get('/{ident}/journey', response_model=Journey)
def journey(ident: int, s=Depends(service)):
    """The current path as connected nodes, projected from the lifecycle snapshot."""
    v = Lifecycle(s).snapshot(ident)
    primary = ActionRef(key=v['primary'], label=ACTIONS.get(v['primary'], v['primary']), primary=True) if v['primary'] else None
    nodes = []
    for node in build_journey(v):
        status = {'upcoming': 'future'}.get(node['status'], node['status'])
        events = [dict(created=e.get('created'), actor=e.get('actor'), details=e.get('details') or e.get('event'))
                  for e in (node.get('events') or [])[-3:]]
        nodes.append(JourneyNode(key=node['key'], label=node['title'], status=status, detail=node.get('detail') or '',
                                 current=bool(node.get('is_current')), options=node.get('options') or [], events=events,
                                 action=primary if node.get('is_current') and status in ('current', 'waiting') else None))
    return Journey(repair_id=v['id'], job_number=v['number'], version=v['version'], current_stage=v['stage'],
                   route=v['route'], route_label=v['route_label'], next_action=v['next_action'], nodes=nodes)


@router.get('/{ident}/timeline', response_model=list[TimelineEvent])
def timeline(ident: int, s=Depends(service)):
    return Lifecycle(s).timeline(ident)


@router.get('/{ident}/items')
def items(ident: int, s=Depends(service)):
    """Physical items, who holds each one now, and every recorded handover."""
    life = Lifecycle(s)
    holdings = life.holdings(ident)
    for h in holdings:
        h['holder'] = s.custodian(h['location'])
    movements = Queries(s).history(ident)['movements']
    names = ReadModels(s).item_names(ident)
    return dict(holdings=holdings, movements=[dict(
        id=m['id'], item=names.get(m['item_id'], ''), quantity=m['quantity'], happened=m['happened'],
        from_location=m['from_location'], to_location=m['to_location'],
        from_holder=s.custodian(m['from_location'])['name'], to_holder=s.custodian(m['to_location'])['name'],
        counterparty=m['counterparty'], reference=m['reference'], condition=m['condition'], notes=m['notes'],
        acknowledgment=m['acknowledgment']) for m in movements])


@router.get('/{ident}/records')
def records(ident: int, s=Depends(service)):
    """The complete stored record, as the desktop "Full records" window shows it."""
    return Queries(s).history(ident)


@router.get('/{ident}/visit')
def visit(ident: int, s=Depends(service)):
    return Visits(s).for_job(ident)


@router.get('/{ident}/actions/{action}/form')
def action_form(ident: int, action: str, s=Depends(service)):
    """What to ask for one action the lifecycle allows now, prefilled from the record."""
    return ActionForms(s).describe(ident, action.replace('-', '_'))


@router.post('/{ident}/actions/{action}', response_model=ActionResult)
def act(ident: int, action: str, command: Command, s=Depends(service)):
    """Run one guided step. 409 when the repair changed or the step is no longer available."""
    action = action.replace('-', '_')
    if action not in ACTIONS:
        raise ApiError(404, 'UNKNOWN_ACTION', 'There is no such repair action.')
    if command.expected_version is None:
        raise ApiError(422, 'VALIDATION_ERROR', 'expected_version is required for repair actions.', 'expected_version')
    done = ActionForms(s).submit(ident, action, command.payload, command.expected_version, command.operation_id)
    return ActionResult(replayed=done is False, repair=detail(s, ident))


@router.post('/{ident}/dates', response_model=RepairDetail)
def dates(ident: int, values: DatesIn, s=Depends(service)):
    s.dates(ident, values.repair_due, values.collection_due, values.return_due, values.reason,
            version=values.expected_version, duration_days=values.duration_days, reference_date=values.reference_date)
    return detail(s, ident)


@router.post('/{ident}/hold', response_model=RepairDetail)
def hold(ident: int, values: HoldIn, s=Depends(service)):
    """Record a hold / outcome reason, or release the hold with an empty reason."""
    s.hold(ident, values.reason)
    return detail(s, ident)


@router.get('/{ident}/route-options')
def route_options(ident: int, s=Depends(service)):
    from repairshop.lifecycle import route_choices
    return route_choices(Lifecycle(s).snapshot(ident))
