# Repair lifecycle update · v1.2.0

For the complete schema-7 parts, cards and warranty update, see `LIFECYCLE_IMPLEMENTATION_REPORT.md`. This document describes the foundational lifecycle changes.

This update integrates the supplied repair flow into the existing Windows application. The primary workspace now shows the customer and device, repair route, physical location, responsible party, warranty, pending time and one next action. It uses the existing records rather than a second repair database.

## Architecture discovered and reused

The application uses native PyQt6 widgets, service-owned business transactions and SQLAlchemy-managed SQLite connections. It uses parameterized SQLite queries rather than SQLAlchemy ORM entity classes. `persistence.py` defines the schema and sequential migrations; `services.py` owns customer, repair, warranty, quotation, immutable financial and custody operations. `queries.py` provides existing reports. `customer_records.py` manages stable devices, photo evidence, intake drafts, folder projections and customer overview data. `ui.py`, `customer_ui.py`, and `ui_widgets.py` implement the screens. `documents.py`, `messaging.py` and `backup.py` provide receipts, the durable consent-aware outbox and verified backup/restore.

Existing stages represented work progress, while `items` + `holdings` + append-only `movements` represented actual custody. Assignments identify a technician, vendor or service center. A completed external repair was already distinct from physical return. Customer approvals refer to immutable quotation versions; customer and vendor ledgers remain separate from device collection. These concepts are retained.

## Staff flow

1. Use **New Repair Intake** to search or register the customer, save the required owner/submitter photo, and record the device, condition and only the accessories actually received. Intake creates the stable device/job references and receiving receipt. An interrupted intake remains a resumable draft.
2. Open the job's **Repair workspace**. Follow the prominent **Next action** button. Complete the initial inspection, verify warranty, then confirm a route and responsible repairer. Selecting a route never falsely moves the device.
3. In-house work proceeds through diagnosis, parts availability, estimate, explicit customer approval, required advance, repair and technician testing. Parts orders pause the job and resume its previous estimate/approved stage when received.
4. External work requires a selected directory entry and a dispatch record with items, condition and consent. Record direct handover or a carrier; carrier dispatch shows **In Transit** until arrival is confirmed. Capture external reference numbers, diagnosis, cost breakdowns and repair results. Record customer approval for paid work. Vendor bills and payments use the existing ledger.
5. All successful routes reach **Final shop QC** while the device is physically at the shop. Functional, power and original-complaint checks must pass; charging, display and connectivity must be passed or explicitly not applicable. QC failure returns in-house work to diagnosis and external work to a new dispatch/rework cycle.
6. Unrepairable, declined, cancelled and unsuccessful jobs use an explicit **Unrepaired return condition check**. They never acquire a false successful-repair test result. Only the previously agreed return/assessment charges can be billed.
7. Review billing and advances, then mark **Ready for Delivery**. The balance remains visible. Queue a customer notification using the existing consent/provider settings, record actual payment/refund, and open handover.
8. Handover shows photos, original accessories, all currently held items, the repair summary and warranty. Confirm demonstration, acceptance, accessories and payment review, and record the receiver and acknowledgment. Every returned item moves atomically to **With Customer**; the job becomes **Delivered**. Close it with **Close job**. Its full history and any explicitly approved credit remain available.

## Lifecycle and compatibility model

There is one current stage: the existing `jobs.stage`. Existing route, assignment, dates, custody, warranty, quotation, payment and photo fields are reused. `Lifecycle` determines valid actions, display status, next action, custody-derived location, attention messages and tracker steps. Form widgets do not implement independent transition rules.

New desktop intakes enter the guided workflow. The existing direct `Service.intake` API remains backward compatible (`guided=False`); the desktop passes `guided=True`. Existing integrations and old records therefore are not silently subjected to invented historical prerequisites. Direct old stage/assignment/custody/warranty/replacement shortcuts are blocked for guided jobs; quotation actions validate the current lifecycle, and paid work still uses the existing approval/deposit checks.

Additional precise stages are `inspection`, `warranty_check`, `route_selection`, `external_diagnosis`, `technician_testing`, `final_qc`, and `billing`. Existing stages retain their original database values.

| Stored stage | Staff label / meaning |
| --- | --- |
| received | Received; next is initial inspection |
| inspection | Initial inspection |
| warranty_check | Verify manufacturer warranty; unknown stays pending |
| route_selection | Confirm repair route and responsible party |
| diagnosis | In-house diagnosis / re-diagnosis |
| ready_dispatch | Dispatch record or physical dispatch pending |
| external_diagnosis | At service center / with third-party technician, diagnosis pending |
| awaiting_estimate | Prepare customer estimate or record center warranty decision |
| awaiting_approval | Waiting for customer decision on current quote |
| approved | Ready to authorize repair, subject to diagnosis, custody, parts and deposit |
| waiting_parts | Parts ordered / awaited |
| under_repair | Repair in progress; physical holder remains independently visible |
| technician_testing | In-house technician testing |
| awaiting_return | External result received; device must return to shop |
| testing / final_qc | Final shop QC |
| billing | Review and issue applicable final charges |
| ready_repaired | Ready for delivery after successful QC and billing review |
| return_unrepaired | Return without repair; receipt/condition check still required |
| ready_unrepaired | Ready for delivery, explicitly unrepaired |
| collected | Delivered / with customer |
| closed | Closed; preserved history |

### Legacy mapping

Migration does not rewrite old statuses or guess that an old completed repair was delivered. Existing status labels are displayed with **LEGACY**, while actual location comes from holdings. Unknown values remain **LEGACY STATUS: original value** and require review; they are not silently mapped.

The **Review legacy job** action requires an explicit operator review and explanation. It preserves the old stage in audit/evidence. Most known stages remain unchanged. Previously ready jobs return to Final QC to verify readiness and billing rather than assuming the new checklist existed. A previously delivered job can close only after verified handover/custody evidence. Tracker checkmarks are based on recorded transitions, never invented for missing legacy steps.

## Migration and data integrity

Schema **5 → 6** adds only `jobs.lifecycle_version`, `jobs.lifecycle_data` and an index. All existing rows start with lifecycle version 0 and empty evidence. No production database is deleted, recreated, or seeded. The existing migration engine makes and validates a complete pre-upgrade archive before upgrading an existing database.

`lifecycle_data` contains the new inspection/warranty-verification evidence, parts order/resume information, dispatch snapshot, route-specific notes/cost components, QC checklist, repair warranty, billing review and handover confirmations. It is current supporting evidence; every important change is also recorded in the existing append-only audit/work tables. No duplicate location, customer, device or financial ledger is introduced.

Compound lifecycle commands reuse existing services within one transaction. Nested operations use savepoints and the same connection. A failed multi-item handover rolls back every movement and status change. Composite read views use one consistent read-only database snapshot. Optimistic version checks prevent a stale open form from overwriting newer work.

Physical movement records, financial entries, quote decisions and audit rows remain immutable. Partial external returns leave remaining accessories visible and block final handover. Replacement handling records the new serial as a linked replacement item, preserves the original device ID/history and explicitly resolves the original item. Owner-authorized exceptions require a reason and remain in custody history.

## Screens changed and added

- **Dashboard:** ten clickable lifecycle/custody cards, attention list, account/backup/messaging summaries and intake/draft actions. Counts of progress and physical location may overlap.
- **Active Repairs / Ready for Delivery / Repair History:** searchable paginated views showing route, status, physical location, responsibility, pending time, expected date, balance and next action. The ready and history views reuse the same table.
- **Job detail:** prominent repair status header, route-specific tracker, relevant action buttons, route details, device photos, custody and chronological timeline. **Full records** preserves the prior detailed tabs.
- **Inspection, warranty verification and route decision:** dedicated guided dialogs, with large route selection buttons and mandatory route confirmation.
- **Dispatch / external receipt:** actual selected items, condition, carrier, acknowledgment and partial returned quantities.
- **Diagnosis / parts / repair / technician test:** guided dialogs using existing work records.
- **Final QC:** original complaint, diagnosis, work, parts, route, repairer and available job photos with an explicit checklist. Unrepaired returns use a separate condition check.
- **Billing / handover:** existing ledgers integrated with the ready stage; customer/device photos, accessory reconciliation, delivery confirmation and automatic collection receipt.
- **Customer overview:** route, readable lifecycle state, current location, next action and last update added alongside stable devices, previous repairs, payments and photos.
- **Directories:** existing reusable vendor/center records gain structured company/OEM, address, contact person, email, specialization and notes within the existing details field. Legacy free-text details remain readable.

## Attention and operating assumptions

- Return/repair/collection dates produce relevant overdue warnings. Approval and parts waits are flagged after three calendar days by default. Final QC, outstanding payments/refunds, holds and accessories left externally after device return are visible.
- INR, integer paise and Asia/Kolkata display times are retained. Manufacturer eligibility verification and the center's actual coverage decision are separate.
- A customer photo remains mandatory for intake. Device before/after photos are supported and optional; no automatic face recognition or disconnected-camera detection is claimed.
- The owner retains authority for invoices, refunds, vendor accounts and financial corrections. Counter staff can record customer receipts. Positive-balance handover needs an explicit owner credit reason; negative-balance handover requires refund/credit resolution. Collection does not erase debt.
- Notifications are queued through existing consent-aware channels. A queued notification is not proof of delivery. The synthetic preview has no external customer messaging consent.
- QC failure means rework. A post-delivery repair uses the existing linked follow-up job rather than rewriting the delivered job.

## Files changed

New: `repairshop/lifecycle.py`, `repairshop/lifecycle_ui.py`, `repairshop/migration6.py`, `tests/test_lifecycle.py`, `scripts/lifecycle_demo.py`, this guide and the preserved lifecycle requirements.

Updated: `repairshop/persistence.py`, `repairshop/domain.py`, `repairshop/services.py`, `repairshop/ui.py`, `repairshop/ui_widgets.py`, `repairshop/customer_records.py`, `repairshop/customer_ui.py`, version metadata, release/progress documentation and verification output.

## Intentionally preserved

Customer registration and consents; mandatory customer photos, device photos, recovery and attachments; stable device/job IDs; intake drafts and folders; sales; versioned quotations and approvals; customer and vendor ledgers, allocations and corrections; original warranty/work/custody records; reports, documents, notification providers, staff roles, backups and restore. The original detailed job tabs remain available. No external messages or real financial transactions are performed by this update.

## Verification

`tests/test_lifecycle.py` covers the three route happy paths; warranty rejection and route switching; waiting for parts; unsuccessful repair; declined quotes and unrepaired collection; QC pass/failure and external re-dispatch; payment/refund/owner-credit handling; delivered/closed custody; partial accessory returns; replacement serial history; invalid/stale actions; old API guardrails; legacy adoption; verified schema-5 migration preserving financial/photo/history records; transaction rollback; and the actual Qt workspace/tracker.

The complete suite result is recorded in `test-results.xml`. Synthetic screen images are in `screenshots/lifecycle-*-v12.png`. `package-verification.json` records the actual portable ZIP membership and extracted executable launch/restart check. The portable ZIP contains only **RepairShopManager.exe**, with no standalone source, guides, test data or loose runtime files. All release verification uses isolated synthetic databases. A separate clean Windows installation and new real-camera hardware are outside this workstation's verification evidence.
