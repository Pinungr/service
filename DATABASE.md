# Database impact — intake UX 1.5.0

Schema remains version 9. Customer fields, photos, category/accessory relations, brand/model masters, sales links, per-device jobs and intake drafts reuse existing tables and service transactions.

The optional `intake_warranty` object is added to existing `jobs.lifecycle_data` JSON and recorded as `intake_warranty_recorded` audit evidence in the same intake transaction. Shop snapshots derive from the selected, ownership-checked sale. External snapshots are validated customer reports; hidden valid-only fields are cleared for other statuses. Existing verified manual warranty checks and coverage decisions are not replaced. Older jobs without the optional object retain their behavior. No migration, reset or destructive data conversion is required.

## Schema version 11 — customer visits and versioned third-party dispatch

`migration11.py` is additive. No earlier migration file was changed and no historical
row is rewritten.

New tables:

- `visits` — one customer intake session. Columns: `number` (`VIS-YYYYMMDD-NNNN`, unique),
  `customer_id`, `intake_ref`, `created`, `actor`, `notes`, `estimated_total`,
  `advance_total`, `origin`, `cancelled_reason`. Indexed on `customer_id`, `created`
  and `intake_ref`. The visit number is immutable and visits cannot be deleted; an
  abandoned intake is recorded with `cancelled_reason` and an audited `visit_cancelled`
  event, which never removes its child jobs.
- `dispatches` — one administrative dispatch record per repair job, per send cycle,
  per version. `(job_id, cycle, version)` is unique and a partial unique index keeps
  exactly one `current=1` row per `(job_id, cycle)`. Statuses are `DRAFT`, `READY`,
  `DISPATCHED`, `SUPERSEDED`, `RETURNED`, `CANCELLED`.

New column: `jobs.visit_id` (nullable FK, indexed together with `jobs.intake_ref`).

Backfill: every existing job was grouped by its own recorded `(customer_id, intake_ref)`
pair, and one visit was created per group in job order, dated from the earliest job's
receipt time. Jobs already received together through the multi-product intake therefore
stay together, and no unrelated jobs are merged. Job ids, numbers, custody movements,
financial entries and issued cards are untouched. A dispatch record is reconstructed for
external jobs that carry saved guided-workflow dispatch evidence, marked `DISPATCHED`
when the custody ledger shows an outbound movement and `READY` otherwise.

Immutability: `dispatch_history_update` rejects any change to the repairer, reference,
transport details, amount, manifest, condition or recorded dispatch time of a row that
has already been sent, superseded, returned or cancelled. Corrections therefore create a
new version with a mandatory `amendment_reason` and a `supersedes_id` link. The custody
ledger (`movements`, `holdings`) is never written by an amendment, so the original
physical handover time, sender, receiver and item history are preserved exactly.

## Schema version 12 — intake detail, third-party quotations, return checks

`migration12.py` is additive. No earlier migration file was changed.

New columns:

- `customers`: `address_line1`, `address_line2`, `pincode`, `district`, `state`. The legacy
  free-text `address` column is kept and is still rewritten from the structured fields, so
  older documents, folder projections and reports keep working. Existing free-text
  addresses were copied into `address_line1` (with any remaining lines into
  `address_line2`); PIN code, district and state start blank and are completed on the next
  edit. State and district are plain text with offline suggestions — no dataset is bundled
  and no network lookup is performed.
- `jobs`: `initial_estimate` (paise) and `customer_requirement`. The initial estimate is
  the counter figure and is never overwritten by a quotation or a bill.
- `items`: `notes` and `photo_id`, so a received accessory carries its own condition
  (`Working` / `Not Working` / `Not Tested` / `Damaged`, in the existing `condition`
  column), a note and a photo.
- `masters`: `address_line1`, `address_line2`, `pincode`, `district`, `state`,
  `specialization`, `photo_id` for third parties, service centres and suppliers. Any
  address already stored in the JSON `details` profile was lifted into these columns.
- `dispatches`: `paid_by` (shop / customer / third party).

New tables:

- `party_quotes` and `party_quote_lines` — the third party's own quotation, versioned.
  `(job_id, version)` is unique and a partial unique index keeps one `state='current'` row
  per job. Both tables reject UPDATE and DELETE, so a revision is always a new version
  linked by `supersedes_id` with a `revision_reason`. Parts quoted here are supplied by
  the third party and are deliberately never written to `stock_items`, `repair_parts` or
  `stock_movements`.
- `return_verifications` and `return_discrepancies` — the physical check of items coming
  back from an external repairer, built from the outbound dispatch manifest. Both are
  append-only. Recording a verification never moves custody; `holdings`/`movements` are
  written only by the existing confirmed receive operation.

Settings (`settings` table, no migration needed): `paper_size` (A4 or A5) and
`include_photos` for customer WhatsApp/email.
