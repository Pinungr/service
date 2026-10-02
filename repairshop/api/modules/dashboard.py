"""Prepared operational summaries and the global job search."""
from fastapi import APIRouter, Depends, Query
from repairshop.lifecycle import Lifecycle, LABELS
from repairshop.queries import Queries
from ..deps import service
from ..schemas import Model

router = APIRouter(tags=['dashboard'])

QUEUE = [('received', 'Received', 'info'), ('inspection', 'Waiting inspection', 'warning'),
         ('awaiting_estimate', 'Estimate pending', 'warning'), ('awaiting_approval', 'Waiting approval', 'warning'),
         ('under_repair', 'Repair in progress', 'info'), ('waiting_parts', 'Waiting for parts', 'warning'),
         ('ready', 'Ready for delivery', 'success'), ('collected', 'Completed', 'success')]
PLACES = [('in_house', 'In-house'), ('external_centre', 'At service centre'), ('external_vendor', 'With third party'),
          ('warranty_claims', 'Warranty claims'), ('attention', 'Attention required'), ('overdue', 'Overdue')]


class Card(Model):
    key: str
    label: str
    tone: str = 'info'
    count: int


class AttentionRow(Model):
    id: int
    number: str
    customer: str
    device: str
    location: str
    attention: str
    next_action: str


class Dashboard(Model):
    mine_only: bool
    queue: list[Card]
    places: list[Card]
    attention: list[AttentionRow]
    balances: list[dict]
    sales_awaiting_collection: int | None
    loose_accessories: int
    last_backup: str | None
    messaging_mode: str


class SearchHit(Model):
    id: int
    number: str
    customer: str
    phone: str
    device: str
    device_id: int | None
    stage: str
    status: str
    visit_number: str | None
    received: str


@router.get('/dashboard', response_model=Dashboard)
def dashboard(s=Depends(service)):
    life = Lifecycle(s)
    totals = life.dashboard_counts()
    data = Queries(s).dashboard()
    attention = [r for r in life.rows(filter_key='attention', limit=50) if r['attention']]
    return Dashboard(
        mine_only=not s.may('view_all_jobs'),
        queue=[Card(key=k, label=label, tone=tone, count=totals.get(k, 0)) for k, label, tone in QUEUE],
        places=[Card(key=k, label=label, count=totals.get(k, len(attention) if k == 'attention' else 0)) for k, label in PLACES],
        attention=attention,
        balances=data['balances'],
        sales_awaiting_collection=data['sales'],
        loose_accessories=sum(r['units'] for r in data['locations'] if r['type'] == 'accessory'),
        last_backup=(data['backup'] or {}).get('created'),
        messaging_mode=s.db.setting('messaging_mode', 'test'))


@router.get('/search', response_model=list[SearchHit])
def search(q: str = Query('', max_length=80), s=Depends(service)):
    """Mobile number, REP-/visit number, DEV- device id or job id; bounded to 30 results."""
    rows = Lifecycle(s).search_jobs(q.strip())
    for row in rows:
        row['status'] = LABELS.get(row['stage'], row['stage'])
    return rows
