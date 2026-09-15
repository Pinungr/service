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

## Schema version 13 — corrected visit totals, technician identity

`migration13.py` is additive and idempotent. No customer, job, deposit, payment,
quotation or invoice record is deleted or rewritten.

* `visits.estimated_total` is recomputed from `sum(jobs.initial_estimate)` for every
  visit. Version 11 and 12 populated it from the customer's **deposit**, which is a
  different figure. Deposits themselves are untouched and still live on `jobs.deposit`;
  `visits.advance_total` still comes from money actually received. The migration records
  how many visits it corrected in the audit log, and re-running it is a no-op.
* New column `masters.user_id` links a directory technician (`kind='technician'`) to a
  login account, with a partial unique index so one login maps to at most one directory
  technician. Job ownership for a technician is checked through this link, so a repair
  assigned via `assignments.technician_master_id` is reachable only by the technician it
  belongs to. Existing rows keep `user_id` NULL and are simply reachable by no technician
  until an owner links them.

Migration transactions: `migration11` and `migration12` previously ran
`executescript()` inside an open transaction. `executescript()` implicitly commits, so a
later failure could leave the schema half-applied with `user_version` unchanged. Both now
use `persistence.migration()`, which wraps the whole migration — including the
`user_version` bump — in one transaction, and `persistence.run_script()`, which executes a
script statement by statement without ending that transaction. Migrations 5 to 10 were
reviewed and were already atomic.

File layout: shop-only copies that carry purchase cost, third-party cost or margin are
written under `Internal/` instead of the customer's folder, and are recorded with
attachment kind `internal_document` so no customer send path can select them. `Internal/`
is included in backup, restore and restore-recovery alongside `managed` and `Customers`.

## Custody identity — no front office, no office-storage default custodian

No schema change and no data migration. Custody has always been a location string on
`holdings`/`movements`, so this is a change to what new records contain, never a rewrite
of what old ones say.

A custody location now answers *who is responsible for this item*:

| Value | Meaning |
|---|---|
| `staff:<user id>` | an authorized staff/admin user is holding it |
| `technician:<user id>` / `technician:master-<id>` | a technician is holding it |
| `vendor:` / `centre:` / `transit:` | an external repairer or a carrier has it |
| `customer` | back with its owner |
| `exception:<reason>` | lost, written off or otherwise resolved |
| `shop:<place>` | **historical / optional** — a storage place rather than a person |

`domain.in_shop()` and `domain.sql_in_shop()` are the single definition of "in the shop's
own possession" and accept all of `shop:`, `staff:` and `technician:`. Every possession
check in Python and SQL uses them, so historical `shop:` rows keep behaving exactly as
before and remain readable, reportable and restorable.

Intake no longer asks who received the product or which shelf it goes on. The signed-in
user becomes both the receiver (`jobs.actor`) and the first custodian, and the intake
movement runs `customer → staff:<that user>`. `Service.receiving_custody()` derives the
identity from the session and refuses a staff identity belonging to anyone else, so one
employee cannot record a colleague as having taken delivery. A `shop:` place is still
accepted where a caller passes one explicitly.

Assignment and custody stay independent: assigning a repair never moves the product, and
`hand_over` records a real handover between two authorized people without touching the
assignment. The identities behind the audit trail already existed and are unchanged —
`jobs.actor` (received by), `assignments.actor` / `technician_id` (assigned by / to),
`movements.actor` (who recorded a handover), `quotes.actor`, `entries.actor`.

## Schema version 14 — return events own their evidence

`migration14.py` is additive apart from removing columns that describe a choice the
application no longer offers.

* `return_verifications` gains `received_by_user_id`, backfilled from `actor`, and loses
  `receiver_kind`, `receiver_name`, `receiver_mobile` and `storage`. A return is received
  by the signed-in user; there is no storage custodian and no receiver to choose, so
  `Returns.verify(job_id, received, operation_id, notes, discrepancies)` takes no receiver
  argument and cannot be told to record somebody else.
* New `return_evidence(verification_id, discrepancy_id, attachment_id)` replaces
  `return_discrepancies.photo_id`; existing photos were migrated into it. It is
  append-only and `attachment_id` is unique, so one photo documents one return event.
  A photo only qualifies as return evidence when it was captured as one
  (`attachments.kind='return_photo'`), belongs to that repair, and has not already been
  used for an earlier return. An intake photo of the same product is therefore never
  silently reusable as proof of transit damage.

## Authorization

`permissions.py` is the authority for what each role may do. Services call
`require_permission('intake')` rather than naming roles, and `Service.require_job_access`
is the single job-level guard used by every job-specific read and write. A user without
`view_all_jobs` reaches a repair only when it is assigned to them — by login account or
through the directory technician linked to it — or when they are physically holding it.
A shared visit never widens that: visit listings, child jobs and product counts are all
filtered per job.

Custody values are `staff:<user id>`, `technician:<user id>`, `vendor:`, `centre:`,
`transit:`, `customer` and `exception:`. `shop:<place>` is only ever read, never written:
storage places are no longer seeded, are not a directory, and cannot be made a custodian.

## Application settings

`app_settings.py` declares every operational default the owner configures once: paper
sizes, which events go out on WhatsApp and email, whether the PDF is attached, what the
intake receipt shows, and what happens after intake. Values live in the existing
`settings` table; a key that has never been set falls back to its declared default, so
adding a setting never breaks an existing installation and a stored value that no longer
validates falls back rather than crashing.

A global setting states only what the shop *wants* to do. Whether a customer can be
reached, and whether they consented, is still decided per customer in
`queue_customer_document`, so a setting can never message someone who has not agreed.
Only `settings` permission holders may change them; everyone else reads them through
normal work.

## Records on disk

Two separate trees, both included in backup and restore:

* `Customers/…/Repairs/<job>/customer-job-summary.txt` — only what the customer may see:
  their details, the product, the reported issue and condition, accessories received, the
  initial estimate, the approved quotation, the account position, warranty, status and
  handover. Safe to print, email or hand over.
* `Internal/CUST-nnnnnn/<job>/internal-job-details.txt` — the shop's own record:
  purchase and vendor costs, margins, third-party quotations, assignments, work logs,
  expenses, dispatches, return checks, custody history and the audit trail.

Nothing is routed by filename: `Documents.generate()` takes an explicit
`visibility='customer'|'internal'`, and internal copies are recorded with attachment kind
`internal_document`, which no customer send path will accept.
