"""Quotations, customer decisions, bills, third-party quotations, costing, accounts and sales.

All money is whole paise. Totals, balances and invoice amounts are computed by the
existing billing, quotation and ledger code; nothing here does financial arithmetic.
"""
import uuid
from typing import Any, Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from repairshop.billing import Billing, CATEGORIES
from repairshop.costing import JobCosts
from repairshop.domain import today
from repairshop.party_quotes import PartyQuotes
from repairshop.queries import Queries
from repairshop.readmodels import ReadModels
from ..deps import service
from ..schemas import Ok

router = APIRouter(tags=['finance'])
AccountType = Literal['customer', 'vendor']


def op():
    return Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80)


class Charge(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    amount: int
    kind: str | None = None


class QuoteIn(BaseModel):
    scope: str = Field(min_length=1)
    lines: list[Charge] = []
    terms: str = 'Paid work starts after this version is approved and the required deposit is received.'
    valid_until: str | None = None


class PreviewIn(BaseModel):
    lines: list[Charge] = []


class DecisionIn(BaseModel):
    decision: Literal['approved', 'declined']
    person: str = Field(min_length=1)
    channel: Literal['call', 'in_person', 'whatsapp', 'email']
    evidence: str = ''


class InvoiceIn(BaseModel):
    operation_id: str = op()


class PartyLine(BaseModel):
    kind: Literal['part', 'labour', 'transport', 'other'] = 'part'
    name: str = Field(min_length=1)
    quantity: int = Field(1, ge=1)
    unit_cost: int = Field(0, ge=0)
    customer_charge: int = Field(0, ge=0)
    warranty: str = ''
    notes: str = ''


class PartyQuoteIn(BaseModel):
    lines: list[PartyLine] = []
    labour: int = Field(0, ge=0)
    transport: int = Field(0, ge=0)
    other: int = Field(0, ge=0)
    reference: str = ''
    notes: str = ''
    reason: str = ''


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1)


class CostsIn(BaseModel):
    values: dict[str, int | str]
    reason: str = Field(min_length=1)


class EntryIn(BaseModel):
    account_id: int
    kind: str
    amount: int
    job_id: int | None = None
    posted: str | None = None
    method: str = ''
    reference: str = ''
    notes: str = ''
    allocations: list[tuple[int, int]] = []
    operation_id: str = op()


class ReverseIn(BaseModel):
    reason: str = Field(min_length=1)
    operation_id: str = op()


class ExpenseIn(BaseModel):
    kind: Literal['outbound_transport', 'return_transport', 'part', 'handling', 'additional_vendor_charge']
    amount: int = Field(ge=0)
    payer: str = ''
    reference: str = ''
    allocations: dict[int, int]
    included_entry_id: int | None = None
    details: dict[str, str] = {}
    operation_id: str = op()


class SaleIn(BaseModel):
    customer_id: int
    device: str = Field(min_length=1)
    category_id: int | None = None
    serial: str = ''
    invoice_ref: str = ''
    invoice_date: str | None = None
    sale_date: str | None = None
    amount: int = Field(0, ge=0)
    cost: int | None = Field(None, ge=0)
    provider: str | None = None
    warranty_start: str | None = None
    warranty_end: str | None = None
    warranty_terms: str = ''


class CollectIn(BaseModel):
    collector: str = Field(min_length=1)
    acknowledgment: str = Field(min_length=1)


# ---- customer quotations --------------------------------------------------------

@router.get('/quotes')
def quotes(s=Depends(service)):
    return ReadModels(s).quotes()


@router.get('/repairs/{ident}/quotes')
def job_quotes(ident: int, s=Depends(service)):
    return ReadModels(s).job_quotes(ident)


@router.post('/repairs/{ident}/quotes/preview')
def preview(ident: int, values: PreviewIn, s=Depends(service)):
    return Billing(s).quote_preview(ident, [c.model_dump() for c in values.lines])


@router.post('/repairs/{ident}/quotes', response_model=Ok)
def issue_quote(ident: int, values: QuoteIn, s=Depends(service)):
    return Ok(id=s.issue_quote(ident, values.scope, [c.model_dump(exclude_none=True) for c in values.lines],
                               values.terms, values.valid_until or None))


@router.get('/quotes/{ident}')
def quote(ident: int, s=Depends(service)) -> dict[str, Any]:
    """The exact version the customer is asked to approve, grouped as quoted, with the money position."""
    q = s.quote_decision_details(ident)
    billing = Billing(s)
    grouped = billing.breakdown(billing.quote_lines(q))
    summary = billing.summary(q['job_id'])
    return dict(id=q['id'], job_id=q['job_id'], version=q['version'], state=q['state'], scope=q['scope'],
                total=q['total'], terms=q['terms'], valid_until=q['valid_until'], expired=q['expired'],
                categories=list(CATEGORIES), lines=grouped['lines'], totals=grouped['totals'],
                advance=summary['advance'], other_payments=summary['other_payments'],
                expected_balance=q['total'] - summary['received'], initial_estimate=summary['initial_estimate'],
                decisions=['declined'] if q['expired'] else ['approved', 'declined'])


@router.post('/quotes/{ident}/decision', response_model=Ok)
def decide(ident: int, values: DecisionIn, s=Depends(service)):
    """Record the authorised person's explicit decision. Reading a message is not approval."""
    return Ok(id=s.decide_quote(ident, values.decision, values.person, values.channel, values.evidence))


@router.post('/quotes/{ident}/invoice', response_model=Ok)
def invoice(ident: int, values: InvoiceIn, s=Depends(service)):
    return Ok(id=s.invoice(ident, values.operation_id))


@router.get('/repairs/{ident}/billing')
def billing(ident: int, s=Depends(service)):
    return Billing(s).summary(ident)


@router.get('/repairs/{ident}/decline-balance')
def decline_balance(ident: int, s=Depends(service)):
    return s.decline_balance(ident)


@router.post('/repairs/{ident}/decline-bill', response_model=Ok)
def bill_decline(ident: int, values: InvoiceIn, s=Depends(service)):
    return Ok(id=s.bill_decline(ident, values.operation_id))


# ---- third-party quotations and internal costing --------------------------------

@router.get('/repairs/{ident}/party-quotes')
def party_quotes(ident: int, s=Depends(service)):
    q = PartyQuotes(s)
    return dict(current=q.current(ident), history=q.history(ident))


@router.post('/repairs/{ident}/party-quotes', response_model=Ok)
def issue_party_quote(ident: int, values: PartyQuoteIn, s=Depends(service)):
    data = values.model_dump()
    return Ok(id=PartyQuotes(s).issue(ident, data.pop('lines'), **data))


@router.post('/repairs/{ident}/party-quotes/cancel', response_model=Ok)
def cancel_party_quote(ident: int, values: ReasonIn, s=Depends(service)):
    PartyQuotes(s).cancel(ident, values.reason)
    return Ok()


@router.get('/repairs/{ident}/costs')
def costs(ident: int, s=Depends(service)):
    return JobCosts(s).summary(ident)


@router.put('/repairs/{ident}/costs', response_model=Ok)
def save_costs(ident: int, values: CostsIn, s=Depends(service)):
    JobCosts(s).save(ident, values.values, values.reason)
    return Ok()


# ---- accounts -----------------------------------------------------------------------

@router.get('/accounts/{account_type}/entries')
def entries(account_type: AccountType, account_id: int | None = None, job_id: int | None = None, s=Depends(service)):
    return ReadModels(s).entries(account_type, account_id=account_id, job_id=job_id)


@router.get('/accounts/{account_type}/balances')
def balances(account_type: AccountType, s=Depends(service)):
    return Queries(s).account_balances(account_type)


@router.get('/accounts/vendor/parties')
def vendor_parties(s=Depends(service)):
    return ReadModels(s).account_parties('vendor')


@router.get('/accounts/{account_type}/{account_id}/ledger')
def ledger(account_type: AccountType, account_id: int, start: str = Query(None), end: str = Query(None), s=Depends(service)):
    start, end = start or today()[:8] + '01', end or today()
    data = Queries(s).ledger(account_type, account_id, start, end)
    if account_type == 'vendor':
        data['unconfirmed_estimates'] = ReadModels(s).vendor_estimates(account_id)
    return dict(data, start=start, end=end)


@router.post('/accounts/{account_type}/entries', response_model=Ok)
def post_entry(account_type: AccountType, values: EntryIn, s=Depends(service)):
    data = values.model_dump()
    return Ok(id=s.post(account_type, data.pop('account_id'), data.pop('kind'), data.pop('amount'), data.pop('operation_id'),
                        allocations=[tuple(a) for a in data.pop('allocations')],
                        **{k: v for k, v in data.items() if v not in (None, '') or k in ('method', 'reference', 'notes')}))


@router.post('/entries/{ident}/reverse', response_model=Ok)
def reverse(ident: int, values: ReverseIn, s=Depends(service)):
    return Ok(id=s.reverse(ident, values.reason, values.operation_id))


@router.post('/expenses', response_model=Ok)
def expense(values: ExpenseIn, s=Depends(service)):
    return Ok(id=s.expense(values.amount, values.allocations, values.kind, values.payer, values.reference,
                           values.details, values.operation_id, values.included_entry_id))


# ---- products sold ---------------------------------------------------------------------

@router.get('/sales')
def sales(s=Depends(service)):
    return Queries(s).sales()


@router.post('/sales', response_model=Ok)
def register_sale(values: SaleIn, s=Depends(service)):
    data = values.model_dump(exclude_none=True)
    return Ok(id=s.save_sale(data.pop('customer_id'), data.pop('device'), **data))


@router.post('/sales/{ident}/collect', response_model=Ok)
def collect_sale(ident: int, values: CollectIn, s=Depends(service)):
    s.collect_sale(ident, values.collector, values.acknowledgment)
    return Ok(id=ident)
