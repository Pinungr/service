"""Read-only money projection for the Review Billing / Ready-for-Pickup screen.

Four separate numbers are kept distinct at all times:

    INITIAL ESTIMATE  →  APPROVED QUOTATION  →  FINAL BILL  →  BALANCE DUE

The initial estimate is the figure given at the counter and is never rewritten by a
later quotation. The approved quotation is the exact customer-approved version. The
final bill is what was actually posted to the customer ledger.
"""
from .domain import RuleError, rupees

CATEGORIES = ('service', 'parts', 'transport', 'other')


def categorize(line):
    """Group one quotation line into the customer-facing breakdown."""
    kind = (line.get('kind') or '').lower()
    if kind in CATEGORIES:
        return kind
    if kind in ('part', 'stock_part', 'third_party_part'):
        return 'parts'
    if kind in ('labour', 'service'):
        return 'service'
    text = (line.get('description') or '').lower()
    if 'transport' in text or 'courier' in text or 'freight' in text:
        return 'transport'
    if line.get('part_id') or 'part' in text:
        return 'parts'
    return 'other'


class Billing:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def breakdown(self, lines):
        totals = {key: 0 for key in CATEGORIES}
        grouped = {key: [] for key in CATEGORIES}
        for line in lines:
            key = categorize(line)
            totals[key] += line.get('amount', 0)
            grouped[key].append(line)
        return dict(totals=totals, lines=grouped, total=sum(totals.values()))

    def quote_lines(self, quote):
        import json
        if not quote:
            return []
        try:
            return json.loads(quote['lines'])
        except (ValueError, TypeError):
            return []

    def summary(self, job_id):
        """One consistent snapshot of every money figure for this job."""
        self.s.require_permission('billing')
        self.s.require_job_access(job_id)
        with self.db.read_snapshot():
            return self._summary(job_id)

    def _summary(self, job_id):
        job = self.s.job(job_id)
        latest = self.db.one('SELECT * FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1', (job_id,))
        approved = self.db.one('''SELECT q.* FROM quotes q JOIN decisions d ON d.quote_id=q.id
            WHERE q.job_id=? AND d.decision='approved' ORDER BY q.version DESC LIMIT 1''', (job_id,))
        money = self.db.one("""SELECT
            COALESCE(sum(CASE WHEN e.kind='invoice' THEN e.amount ELSE 0 END),0) AS invoiced,
            COALESCE(sum(e.amount),0) AS balance,
            -COALESCE(sum(CASE WHEN e.kind IN ('receipt','refund')
                OR (e.kind='reversal' AND o.kind IN ('receipt','refund')) THEN e.amount ELSE 0 END),0) AS received
            FROM entries e LEFT JOIN entries o ON o.id=e.reverses_id
            WHERE e.account_type='customer' AND e.job_id=?""", (job_id,))
        advance = self.db.one("""SELECT -COALESCE(sum(e.amount),0) AS n FROM entries e
            WHERE e.account_type='customer' AND e.job_id=? AND e.kind='receipt'
            AND e.notes='Intake advance'""", (job_id,))['n']
        installed = self.db.rows("""SELECT name,quantity,customer_price,source,serial FROM repair_parts
            WHERE job_id=? AND status='installed' ORDER BY id""", (job_id,))
        from .party_quotes import PartyQuotes
        party = PartyQuotes(self.s)
        approved_lines = self.breakdown(self.quote_lines(approved))
        return dict(
            job=job_id, number=job['number'], device=job['device'], customer=job['customer'],
            initial_estimate=job['initial_estimate'],
            latest_quote=latest, latest_total=(latest or {}).get('total'), latest_state=(latest or {}).get('state', 'Not issued'),
            approved_quote=approved, approved_version=(approved or {}).get('version'),
            approved_total=(approved or {}).get('total'),
            approved_breakdown=approved_lines,
            final_bill=money['invoiced'],
            advance=advance, received=money['received'], other_payments=money['received'] - advance,
            balance_due=money['balance'],
            installed_parts=[dict(r, amount=r['customer_price'] * r['quantity']) for r in installed],
            third_party_customer_lines=party.customer_lines(job_id),
            ready=job['stage'] in ('ready_repaired', 'ready_unrepaired'),
        )

    def readable(self, job_id):
        """Label/value pairs for the Review Billing panel and the final bill document."""
        s = self.summary(job_id)
        rows = [('Initial estimate at intake', rupees(s['initial_estimate'])),
                ('Approved quotation' + (f" · version {s['approved_version']}" if s['approved_version'] else ''),
                 rupees(s['approved_total']) if s['approved_total'] is not None else 'Not approved yet'),
                ('Final bill', rupees(s['final_bill']) if s['final_bill'] else 'Not billed yet'),
                ('Advance paid at intake', rupees(s['advance'])),
                ('Other payments received', rupees(s['other_payments'])),
                ('Balance due', rupees(s['balance_due']))]
        totals = s['approved_breakdown']['totals']
        rows += [(key.title() + ' (approved)', rupees(totals[key])) for key in CATEGORIES]
        return rows

    def guard_final_bill(self, c, job_id, amount):
        """A bill may never silently exceed the customer-approved quotation."""
        approved = c.execute('''SELECT q.total,q.version FROM quotes q JOIN decisions d ON d.quote_id=q.id
            WHERE q.job_id=? AND d.decision='approved' ORDER BY q.version DESC LIMIT 1''', (job_id,)).fetchone()
        if approved is None:
            return
        if amount > approved['total']:
            raise RuleError(
                f"This bill of {rupees(amount)} exceeds approved quotation version {approved['version']} "
                f"({rupees(approved['total'])}). Issue a revised quotation and record the customer's "
                "approval before billing the higher amount.")
