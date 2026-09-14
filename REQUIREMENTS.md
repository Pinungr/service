# Codex implementation prompt: RepairShop Manager

Act as a senior Python desktop application engineer and business software architect. Build a complete, usable Windows desktop application for my computer/electronics sales and repair shop. Implement the application in the working repository, including its database, native interface, business workflows, integrations, backups, tests, and Windows packaging. A requirements document, wireframe, scaffold, or demonstration alone is not the requested result.

Read this entire prompt before designing the database. It is self-contained and includes the agreed requirements. Use the working name **RepairShop Manager**, with configurable shop branding.

## 1. Delivery approach and boundaries

- First inspect the workspace and applicable repository instructions. If it is empty, create the project. If an application already exists, inspect it, reuse appropriate working code, and preserve existing data and unrelated functionality. Never silently delete, reset, or overwrite an existing database or repository.
- Produce a short implementation plan and then implement it. Work in runnable increments, maintain a requirements checklist, and continue through the full scope without asking for approval after each routine stage.
- Make sensible implementation choices when this prompt leaves ordinary details open. Record assumptions. Ask only when an unresolved decision materially affects business behaviour, existing data, or an external account.
- Complete all local work even if messaging credentials or a Windows build machine are unavailable. Provide working provider adapters and isolated test doubles, while honestly reporting any unverified live integration or platform-specific build step.
- Follow the environment's permissions. Do not publish a website, deploy infrastructure, send messages to real customers, transfer money, or enable production scheduled tasks during development. Provide the settings and setup actions that let the shop owner deliberately enable these features.
- Keep credentials, customer data, real backups, and local runtime files out of Git. Use synthetic demonstration data in a separate database.

## 2. Required architecture and technology

Use a **modular monolith**: one installable desktop application, one repository, one local SQLite database, and directly called internal modules. Monolith does not mean placing everything in one file.

Baseline stack:

- Python 3.12 or a newer supported version compatible with the dependencies; choose and document one tested baseline.
- PyQt6 for a native Windows desktop interface. Do not mix PyQt6 and PySide6. If an existing repository already uses a compatible Qt binding, retain it and explain the choice.
- SQLite with SQLAlchemy 2.x and Alembic migrations, or retain an equally sound existing SQLite persistence layer with explicit versioned migrations.
- ReportLab for PDF job cards, quotations, receipts, statements, and handover documents.
- openpyxl for Excel exports; also support CSV export.
- A maintained HTTP client for official WhatsApp messaging, and SMTP with TLS for email. Select supported authentication for the configured email provider; do not assume every provider accepts a username/password.
- Windows Credential Manager through a suitable keyring integration for messaging secrets.
- pytest and pytest-qt for meaningful domain, integration, and desktop interaction tests.
- PyInstaller for a self-contained Windows distribution. Supply a reproducible Windows build script and installer configuration or documented installation package.

Use clear modules such as bootstrap/config, domain, application services, persistence/migrations, desktop UI, messaging, documents, reporting, backup/restore, and audit. Keep SQL and business rules out of UI event handlers. Business operations must be testable without launching the desktop interface. Avoid generic framework abstractions that add complexity without serving a requirement.

No browser-hosted application, React frontend, FastAPI/Django web server, microservices, Docker, Redis, Celery, mandatory cloud database, or AI/LLM dependency is needed. Background threads or a background mode of the same executable are allowed; they are internal parts of the monolith.

Assume one shop computer initially, with separate staff logins inside the application. The volume requirement means customers and service jobs, not 1,000 simultaneous staff sessions. Do not put a shared SQLite file on a network drive. Document a future LAN deployment path without implementing a distributed system now.

## 3. Local operation, identity, and storage

- All core work must function without internet: intake, customer search, repairs, warranty tracking, quotations and recorded approvals, item handovers, finance, dashboards, documents, history, backups, and restoration.
- Internet is used for configured WhatsApp and email services. A provider outage must not block saving a repair or payment.
- Store the database and managed attachments in a stable writable Windows application-data directory outside the executable/install directory. Use relocatable attachment references and handle spaces and Unicode in paths.
- Provide first-run shop configuration, owner account creation, currency INR, and timezone Asia/Kolkata by default. Store event timestamps consistently and render local dates/times; distinguish calendar due dates from instants.
- Local roles: Owner/Admin, Counter Staff, and Technician. Owner controls settings, staff access, finance corrections, waivers, restores, and credentials. Counter staff manages intake, customer communication, handovers, and permitted receipts. Technicians update assigned work and findings. Enforce permissions in application services as well as the UI.
- Hash login passwords with a maintained password-hashing implementation. Never ship a universal production admin password. Keep technical logs separate from the business audit history and redact secrets.
- Enforce one interactive application instance for the selected live database. Coordinate any worker/background mode so two workers cannot process the same operation.

## 4. Reusable lists: add once, use again

The user calls this “incremental”: newly entered master options must be saved and reusable across later jobs and application restarts.

Implement searchable editable selectors with **+ Add new** for product categories, brands/models where useful, repair/service types, accessory types, technicians, third-party repairers, service centres, transport providers/methods, and shop storage locations.

- Example: create “Laptop repair” on the first visit; select it on subsequent visits.
- Map suggested accessory types to product categories: laptop can suggest adapter, mouse, Wi-Fi dongle, loose RAM, and bag.
- Suggestions are reusable choices. Every new job starts with all accessory-received checkboxes unchecked.
- Adding an accessory type from intake saves the type and its category association, then lets staff explicitly mark whether it was received on this job.
- Normalize names for duplicate detection while preserving readable display names. Phone numbers are normalized, but shared phone numbers must not force two people to become one customer.
- Allow editing and deactivation. Referenced records cannot be hard-deleted; historical documents and issued quotations must retain the names/values they had when issued.
- Third parties are saved business contacts, not automatically software login accounts. Search prior vendors and add a new one when choosing someone different.

## 5. Customers, products sold, and job intake

Maintain customers with name, normalized phone/WhatsApp number, optional email/address, communication preferences, and channel consent. Support optional alternate contacts.

Distinguish the device owner/customer from the person who submitted it and the person collecting it. If these are different people, preserve their relationship and the contacts selected for updates. A customer may own multiple products and return for multiple services.

Maintain a lightweight sales/product register: product category, brand/model, serial number when available, customer, invoice reference/date, sale date, sale amount/cost if entered, warranty provider/start/end/terms, purchase proof, and handover status. Support sold products awaiting collection and connect later warranty/service jobs to the sold product. Do not expand this into a full purchasing, inventory, or tax-filing ERP.

Create a unique, immutable job number, for example REP-2026-000001. A job normally represents one primary device; a single customer visit may group several device jobs under one intake reference. This allows a laptop and printer to be repaired by different vendors and collected separately.

Intake fields include customer and submitter, product/serial, whether sold by this shop or elsewhere, complaint, visible damage, condition/photos, accessories actually received, intake date, receiving staff, storage location, route, tentative dates, consent to assessment/transport and relevant charges, and any customer advance. Allow an unknown serial number. Print a receipt listing the actual device and accessories received.

Customer history must show their sales, devices, warranty claims, repair visits, quotations, payments/refunds, and communications without duplicate customer creation on each visit.

## 6. Individual item custody and handovers

Track the main device and each received loose accessory independently. Store item type, description, quantity, condition, identifying/serial details when applicable, photos if useful, current holder/location, and associated job.

Distinguish loose RAM received separately from RAM already installed inside the device. Installed parts/replacements belong in repair work records and must not create a second received accessory accidentally.

Required custody locations include shop storage location, internal technician where relevant, third-party repairer, authorised service centre, transporter/in transit, customer, and a documented exception location.

- A repair assignment is responsibility; custody is where an item physically is. Model them independently.
- Selecting a repairer or marking “Ready to dispatch” does not move any item.
- Staff explicitly chooses the items and quantities for each dispatch, receipt, internal handover, or customer collection.
- A laptop sent out can leave its adapter, mouse, and dongle at the shop.
- Partial handovers and partial returns must conserve quantities. Serialized units need individual identity. Reject dispatching unavailable items, returning more than sent, or assigning one unit to two locations simultaneously.
- Every movement records from/to, actual handover time, actor, counterparty, transport/reference, quantity, condition, notes, and an optional acknowledgment.
- Transport departure changes custody to in transit; destination acknowledgment changes it to the centre/vendor/shop. Expected arrival alone is not proof of receipt.
- Reconcile returned items against the outbound list, preserve outstanding items, and allow additional returned/replacement items with explicit provenance and linkage.
- Store immutable movement history with correcting/reversing events when necessary. Do not let an editable “current location” field bypass the movement record.

On customer collection, show every originally received item and any agreed replacements. Record the collector and acknowledgment. Require all items to be returned or explicitly resolved by an authorized person with a documented reason before operational closure; partial collections remain visible.

## 7. Repair workflow and state rules

Use related state fields/entities for operational progress, route, custody, warranty decision, quotation approval, payment status, and messaging. Do not encode every combination into one giant status dropdown.

Provide these operational stages or clear equivalents: received, diagnosis/assessment, awaiting estimate, awaiting customer approval, approved/scheduled, under repair, waiting for parts, external repair complete/awaiting return, testing, ready for customer collection, return without repair, collected, and operationally closed. Record on-hold, cancellation, unrepairable outcomes, and reasons without losing custody or finance obligations.

Routes: in-house repair, third-party paid repair, service-centre warranty assessment/repair. Support switching routes and multiple repair assignments/attempts with complete history.

- In-house work records technician, diagnosis, repair actions, replacement parts and costs, start/completion times, test result, and service warranty if provided.
- External work records vendor/contact, reference, estimate, findings, work done, completion, and return expectations.
- Vendor reports are recorded by shop staff initially; the application must not pretend to know an external completion event without receiving an update.
- Store estimated repair completion and estimated customer collection separately. Support estimated duration in days, its reference date, actual dates, and revision history. Use explicitly labelled calendar days by default, not an unexplained working-day calculation.
- Start paid repair only with approval for the current applicable scope/quotation and any required deposit. Permit previously authorized assessment/transport before the full repair quotation exists.
- Additional paid work or a price increase beyond the approved quotation requires a revised quotation and new approval before that extra work starts.
- Mark repaired items ready for collection only when physically at the shop and testing has passed. An external completion report alone means awaiting return.
- For rejected/unrepairable work, allow “Ready for collection — unrepaired” after the item is returned and checked in; it must not need a false “repair passed” result or send a “successfully repaired” message.
- Rework after collection opens a linked follow-up job/attempt, preserving the original invoice, warranty decision, movements, and payments.
- Operational closure, customer debt, vendor debt, and message delivery are independent. Closed/collected jobs with unpaid balances must still appear in ledgers and dues reports.

## 8. Warranty and service-centre handling

Track initial warranty-date eligibility independently from the centre's actual claim decision. An in-date warranty does not automatically mean the claim is accepted.

- Link the sale/invoice, serial, purchase proof, warranty dates/terms/provider, complaint, damage evidence, and assessment request.
- Record centre name/contact, dispatch/arrival, claim/RMA number, inspection findings, accepted/rejected/partially-covered/pending decision, covered work, excluded work, reason, and evidence.
- The centre may confirm eligibility only after inspecting the item. Support shipping for assessment after the customer has agreed to the assessment/transport arrangement.
- Capture tentative days, completion date, return ETA, and changes with reasons; notify the selected customer contacts.
- Record no-charge warranty repair and separately agreed customer-paid transport/handling. Warranty coverage must not silently make every expense free.
- A rejected or partially covered claim can lead to a paid quotation, another repair route, or return without repair, based on the customer's recorded choice.
- Track replacement products from the centre: original and replacement serial numbers, evidence, item custody, and the warranty terms actually supplied. Do not invent a fresh warranty automatically.

## 9. Transport and expense tracking

For outbound and return legs, support bus, train, courier, hand delivery, and reusable user-added methods. Record destination, transport company/person/contact, ticket/receipt/tracking reference, departure, expected arrival, actual acknowledgment, item list, payer, actual cost, and agreed customer charge.

Allocate a shared shipment's actual expense explicitly across linked jobs; allocation totals must equal the expense and never charge the full shared cost once per job. Preserve transport expenses even when repair is declined or a warranty claim is rejected.

Every additional vendor-requested charge needs an amount, reason, supporting record, acceptance status, and job/allocation linkage. Additional customer charges require the quotation rules below; additional vendor payments are separate money movements.

## 10. Quotations, customer decisions, and cancellation charges

Distinguish the vendor's estimate, vendor's confirmed charge, the customer's quotation, customer invoice, and actual payments/refunds.

Build itemized customer quotations with repair labour/service, parts, transport, approved inspection/handling if used, discounts, explicitly configured tax fields if required, and total in INR. Do not hardcode tax law or claim statutory invoice compliance without an agreed configuration. Keep vendor cost/margin in staff views; customer documents show the customer-facing amounts.

Quotation states: draft, issued/awaiting response, approved, declined, expired if a validity date is set, and superseded. Issued versions are immutable snapshots with amount, scope, and applicable terms. A change creates a new version. Approval must reference exactly one version and a recorded customer/authorized representative, amount, timestamp, channel, recorded-by staff member, and optional evidence.

Support approval recorded by staff from a call, in-person conversation, WhatsApp, or email. Sending/reading a message is not approval. Do not infer approval from an unrelated “OK” or use an LLM to authorize repairs. Online customer self-service or reply ingestion is not a prerequisite for the local application.

Keep quote approval and payment separate. A configurable deposit requirement determines whether approved work may start; deposits may be paid before a final invoice and must remain allocated and auditable.

At intake/dispatch, capture the agreed decline/return policy as a per-job snapshot. Required options are NO_CUSTOMER_CHARGE and AGREED_TRANSPORT_ONLY. Optional previously agreed assessment/handling charges must be explicit, never silently added. Shop defaults can populate new jobs but cannot retroactively change old agreements.

If repair is declined, compute agreed charges minus customer money retained, show balance due or refund due, and arrange return without repair. Support owner-authorized waivers with reasons. Existing vendor expenses remain owed unless the vendor separately issues a credit/waiver.

Use “quotation” or “estimate” for the requested repair amount. Reserve “refund” for actual money returned. A refund due is not automatically money paid: record its subsequent payment and reference separately.

## 11. Money, customer accounts, and third-party monthly ledgers

Use integer paise for persisted money, with Decimal-based input/calculations and an explicit rounding policy. Never use binary floating-point money. Validate currency, signs, allocations, and totals centrally.

Implement immutable posted financial entries with reversals/corrections rather than edits that erase history. Drafts can be edited. Use explicit transaction boundaries, unique operation IDs, and duplicate-submit protection so double-clicking or restarting cannot post a payment or invoice twice.

Maintain independent customer accounts and vendor/service-centre accounts, linked to jobs through invoices, line items, payments, credits, and allocations. A job can involve multiple vendors/repair attempts. Actual shop costs, customer selling prices, receivables, and payables must never be one shared amount.

Record these separately:

- Vendor quotation, accepted estimate, confirmed bill/charges, additional approved costs, credit notes/waivers, money sent to the vendor, and money refunded by the vendor.
- Customer quotation, final issued bill, discounts/credits/waivers, advances, partial/final receipts, refund due, and actual refund payment.
- Expenses paid directly by the shop, their job allocations, and which expense is already included in a vendor bill. Prevent counting an included part or transport charge again.

Payment fields: counterparty, direction/type, date, amount, cash/UPI/bank/other reusable method, reference, notes, receipt evidence, entered-by user, and invoice/job allocations. Recording a payment does not initiate a bank or UPI transfer.

One payment may settle several invoices/jobs. Partial payments leave balances outstanding; overpayments become unapplied advances/credits. Prevent over-allocation and track unapplied funds explicitly. Allow opening balances with dated, auditable provenance for first-time setup.

Monthly vendor ledger requirements:

- Filter by vendor and month/date range; also show all vendors and their balances.
- Show opening balance, each job/reference/device, work performed, confirmed charges, credits, payments, vendor refunds, explicit settlement adjustments, and closing balance.
- Use financial posting dates for the statement period and show job/dispatch dates separately. Jobs dispatched earlier and billed later must not disappear or be charged twice.
- Display unconfirmed estimates and unfinished/unbilled work separately from confirmed payable totals.
- Compute vendor closing balance consistently: opening payable + confirmed charges - credits - payments to vendor + refunds received from vendor, with signed documented adjustments.
- Compute customer closing balance consistently: opening receivable + issued charges - credits - receipts from customer + refunds paid to customer, with signed documented adjustments.
- Negative balances represent credit/advance or money due back; never clamp them to zero.
- Carry balances forward across months. “Settled” requires zero outstanding account balance after valid entries; a partial settlement cannot mark all jobs paid. Financial settlement must not mark devices returned or repairs complete.
- Optional round-off is an explicit agreed settlement adjustment, with actor/reason/amount, preserving original charges. Do not silently round each repair or discard a balance.
- Retain dated statement snapshots so an old statement can be viewed even after later corrections; distinguish the issued snapshot from a recalculated ledger.
- Export/print the ledger to PDF/Excel and allow deliberately sending a selected statement through configured messaging, with appropriate recipient preview.

Example that must reconcile: opening vendor payable Rs 500 + two confirmed bills Rs 1,250 and Rs 1,803 = Rs 3,553. An agreed Rs 3 reduction leaves Rs 3,550; a recorded payment of Rs 3,550 leaves zero. A later refund/credit must be represented by its actual entries, not a changed “paid” checkbox.

Report job margin as customer net billed revenue minus recorded direct costs on a consistent tax basis, with estimates labelled provisional. Call this job margin before overheads, not guaranteed net business profit. Payments affect cash flow, not whether revenue/cost is counted twice.

## 12. Automatic WhatsApp and email notifications

Provide a channel-neutral notification service and real adapters for official WhatsApp Business messaging and configured email. The application stays a native desktop monolith; messaging does not turn it into a hosted website.

Business events create durable notification-outbox records in the same database transaction as the event. Send after commit using a background worker, outside database write transactions and outside the Qt UI thread.

Notification events include job receipt, quotation issued, customer decision recorded, tentative collection date, revised/delayed date, dispatch, warranty acceptance/rejection/partial coverage, external repair completion, return arrival, repaired ready for collection, unrepaired ready for collection, and actual collection. Reminders are configurable and limited; stop them when no longer relevant.

Recipients: selected customer/device owner, submitter if different and authorized for updates, and configured shop owner/responsible staff. Each event/audience can use WhatsApp, email, or both. Deduplicate the same normalized destination receiving the same event/content through multiple contact roles. Customer-facing templates must use the approved customer amounts and suitable descriptions; internal vendor costs/margins belong only in authorized internal communications.

Examples of required meaning:

- External repair completed: repair is complete, the item is awaiting return, and collection is tentatively expected on the recorded date. Do not say “collect now.”
- Repaired and tested at shop: job/device is ready for collection, with shop address/hours and current customer balance if appropriate.
- Warranty rejected: convey the recorded customer-facing reason and request a decision on the paid quotation or return.
- Unrepaired item returned: item is ready for collection without repair, with only the agreed charges.

Implement reusable templates and previews with validated variables, approved WhatsApp template identifiers/language where required, and separate email subject/body. Official WhatsApp account setup, recipient opt-in, template approval, internet access, and possible provider charges are deployment prerequisites, not reasons to block the local application.

Store each notification's business event/version, recipient, channel, payload/template snapshot, state, attempts, timestamps, provider message ID, and last error. Useful states include pending, blocked by configuration/consent, sending, accepted by provider, delivered/read where genuinely known, retryable/permanent failure, uncertain outcome, and cancelled as obsolete.

- API success or SMTP acceptance must not be labelled delivered/read. Show delivery unknown when confirmation is unavailable.
- Verify the chosen provider's current official capabilities before implementing status checks. Do not invent a WhatsApp status-polling endpoint or assume a desktop machine can receive public webhooks.
- Default deployment requires outbound connectivity only. Do not deploy a website, public webhook listener, tunnel, or customer portal. Staff records customer approvals and vendor updates through the desktop interface.
- If automatic inbound replies/delivery tracking requires an external callback receiver or a provider's retrieval API, document that dependency and the actual supported capability. Keep an adapter boundary for a later integration; do not fake the feature or add infrastructure silently.
- Use bounded retries with backoff for safe retryable failures and respect rate limits. Persist work across restarts. Revalidate current consent, quotation/version, status, dates, and collection before sending; cancel or replace stale messages.
- Use unique outbox/event keys and worker claims to prevent local duplicate processing. When a timeout/crash leaves it uncertain whether the provider accepted a message, reconcile using supported provider features or flag it for review rather than blindly resending. Do not claim exactly-once delivery across an external provider.
- Do not automatically replay historical messages after restoring a backup. Restored outbox entries require reconciliation and revalidation before sending is re-enabled.
- Provide a notification centre with preview, errors, safe retry, cancellation, and channel configuration. Test mode captures messages locally and never contacts real recipients.

Keep API tokens and email credentials in the OS credential store, not source code, logs, PDFs, or plain exported settings. Document reconfiguration on another computer. Provide explicit settings/test actions for an owner-selected test recipient; never send a real test message without that action.

Sending runs while the application is open or in an explicitly enabled tray/background mode of the same package. Catch up after restart. Do not imply the application sends while the computer is switched off. Avoid WhatsApp Web scraping, browser automation, and personal-account automation libraries.

## 13. Dashboard and staff interface

Build a polished, practical native desktop interface with readable fonts, keyboard navigation, clear validation messages, date pickers, searchable selectors, paginated/filterable tables, and visible saving/error states. Avoid oversized decorative cards that obscure working records. Bundle assets locally.

Required screens: Dashboard; Customers and customer history; Products sold/warranty register; Jobs and intake; Job detail; Dispatch/receive/collection; Technicians/third parties/service centres; Quotations and approvals; Customer payments/refunds; Vendor accounts and monthly settlement; Reports; Notifications; Backups; Settings/staff.

The job detail screen should keep overview, received items/custody, work history, warranty, quotations/decisions, expenses/payments, transport, documents, messages, and audit history accessible through clearly named sections or tabs. Every main action must call the actual application service and persist data.

Dashboard location counts:

- Active repair devices physically at the shop.
- Devices with third-party repairers.
- Devices at service centres.
- Devices in outbound/return transit.
- Loose accessories by location, separately from primary devices.

Dashboard operational counts, with colours plus readable labels/icons:

- Awaiting diagnosis/estimate/approval: amber or a clear neutral label.
- Under in-house repair: blue.
- Ready at shop to dispatch to third party: orange.
- Ready at shop to dispatch to service centre: teal.
- External repair complete/awaiting return: purple.
- Repaired and ready for customer collection: green.
- Unrepaired and ready for collection: distinct labelled status.
- Sold products ready for customer handover: separate from repaired devices.
- Overdue jobs, overdue returns, and delayed collection: red warning indicators.

Selecting a count opens exactly the matching records with job number, customer, device, current holder, responsible repairer, stage, expected dates, balance, and notification status. Filters include dates, customer, phone, serial, job number, category, location, route, technician/vendor/centre, approval, and payment status.

Location totals are exclusive for a primary device at an instant. Operational status cards are another view of those items and must not be added to location totals. Sold products and loose accessories have explicit separate totals. Count physical units rather than handover rows or duplicated join results. Exclude collected/closed items from active custody totals while retaining searchable history and unpaid balances.

Refresh affected dashboard data after successful saves and background events, using real queries. Show last successful backup, outstanding customer/vendor balances, failed/pending messages, and overdue work without conflating these with repair counts. Do not label sample data as live shop data.

## 14. Documents, history, and reports

Generate branded, printable PDF job cards, intake receipts, item dispatch/return manifests, customer quotations, bills/payment receipts, refund acknowledgments, customer collection receipts, vendor statements, and warranty/repair summaries. Preserve issued document snapshots and version references.

Provide PDF, Excel, and CSV reporting for date ranges, repair route, technician, vendor, centre, category, and customer. Include jobs received/completed/collected, open items by custodian, overdue work, approved/rejected warranty claims, customer dues, vendor dues, payments/refunds, transport costs, and job margins. Protect spreadsheet exports against formula injection from user-entered text.

All business changes that matter to responsibility or money must retain actor, timestamp, affected record, event/action, reason when required, and before/after details or immutable event payload. Audit history is append-only through the app; do not claim it is tamper-proof against an operating-system administrator editing local files.

## 15. Backups, long-term archives, and historical viewing

Implement automatic backups inside this application's lifecycle/background mode. These are software features, not ChatGPT reminders or cloud backup services.

Defaults:

- One verified daily recovery backup when due; retain a configurable recent set, initially 30 daily backups.
- A complete dated long-term archive every 90 days, with a simple 60/90-day setting for the requested two-to-three-month interval.
- Backup Now, selectable backup destination, optional external-drive copy, backup history, last successful date, next due date, and clear success/failure/missing-drive indicators.
- If the application/computer was off, catch up on the next launch. Do not silently call an absent external-drive copy successful; keep it pending and preserve any verified local backup.
- Long-term archives remain until the owner explicitly manages retention. Creating an archive must not delete or clear live jobs or old history.

Each complete archive must contain a consistent database snapshot, all referenced managed photos/attachments/issued documents, non-secret settings, application/schema version, backup time, and a manifest with file sizes and checksums. Document credentials that must be re-entered on another computer.

Use SQLite's supported backup API or an equally proven consistent snapshot method. Do not simply copy a live main .db file while ignoring WAL state. Coordinate database and attachment writes so the manifest and snapshot reference a consistent set. Use safe temporary files, validation, and atomic finalization; interrupted archives must not be listed as successful. Exclude backup folders themselves from recursive inclusion. Old verified backups must survive a new backup failure.

Validate archive checksums, attachment completeness, database integrity, and schema compatibility. Test restoration rather than trusting that a ZIP file exists.

Provide two distinct operations:

1. **Open backup for viewing:** open an isolated read-only copy for searching history and viewing/exporting reports. Disable business writes, sending, live outbox processing, and live-data migrations. Never overwrite the current database for viewing.
2. **Restore backup:** owner-only, with a concrete preview and explicit confirmation. Stop workers, take a pre-restore safety backup, validate the chosen archive, restore database plus attachments together, and preserve a recovery path if any step fails. Keep outgoing notifications paused until reconciliation. Fail safely on an unsupported newer schema; migrate only a restored working copy when supported.

Handle disk-full, missing/readonly destinations, corrupted/incomplete archives, invalid paths, archive path traversal, and interrupted restoration. Logs and UI must tell the operator what succeeded and what remains unresolved.

## 16. Persistence, concurrency, and performance

Target at least **1,000 customers with their service jobs per month**, with multiple jobs per customer and multi-year retention. Do not impose a 1,000-record database cap.

- Use foreign keys, relevant unique/check constraints, appropriate indexes, and short transactions. Enable SQLite foreign-key checks on every connection; configure WAL/busy timeout appropriately and document the chosen durability settings.
- Use separate thread-owned connections/sessions. Never share one ORM session across Qt/background threads. Handle lock contention without freezing the UI.
- Persist operation, financial posting, item movements, audit, and notification-outbox entries atomically when they form one business action. Roll back failed actions cleanly.
- Run HTTP, SMTP, report/PDF generation, large exports, and backups outside the UI thread and outside long database write transactions. Recover gracefully from failed attachment/document generation.
- Use pagination and indexed filters; do not load every job, image, or ledger entry into memory at startup. Use real database aggregation for dashboard totals and validate queries against join duplication.
- Protect stale form submissions with version/conflict checks where they could overwrite finance, custody, or quote state.
- Keep schema changes versioned, backed up, and upgrade-tested. Do not recreate the production database on startup or during upgrades.
- Generate reproducible synthetic data with at least 60,000 customers and 100,000 service jobs, repeat visits, multiple items/movements, quotes, and ledger entries. Keep bulk attachments bounded/configurable so tests do not consume uncontrolled disk space.
- Measure startup, first-page search, dashboard, and a vendor monthly ledger on stated hardware. Aim for common first-page searches around one second and dashboard/normal monthly ledger queries around two seconds on a modern SSD machine. These are engineering targets to verify, not claims of achieved performance. Record p50/p95 timings and dataset details; investigate slow queries.

## 17. Meaningful tests and acceptance scenarios

Use isolated temporary databases and synthetic contacts. Live WhatsApp/email is disabled in automated tests. Test real SQLite transactions and application services, plus the essential desktop paths; do not rely solely on mocked persistence or superficial button-exists tests.

Required acceptance coverage:

1. Create “Laptop repair,” an accessory, and a vendor; restart and find all in selectors without duplicates.
2. A new laptop job displays mapped accessories unchecked; selecting adapter and mouse saves only those actually received.
3. Send only the laptop to a vendor; accessories stay at the shop. Reject a duplicate or unavailable dispatch.
4. Partial dispatch/return of quantities preserves totals; missing items stay outstanding and are visible at collection.
5. Switch from in-house to vendor repair, then another vendor; preserve work, custody, and each vendor's charges.
6. Customer owner and submitter differ; send to configured contacts without duplicate same-address messages or leaking internal costs.
7. An in-date warranty is pending until assessed; physical-damage rejection produces a recorded decision, customer update, and paid quote or return path.
8. An accepted warranty has zero covered repair charge but retains agreed outbound/return charges.
9. A service-centre replacement tracks original/replacement serials and actual supplied warranty terms.
10. An issued quote is approved at one version; a higher revised quote cannot use the previous approval. Delivered messages cannot authorize work.
11. Approval without a required deposit cannot start paid work; approval with no deposit policy can. Paid assessment permissions are checked independently.
12. Customer declines under free-return versus transport-only policies; charges and any refund due differ correctly. Later default-policy changes do not alter the old agreement.
13. Vendor completion while the device is away sends an awaiting-return message, not pickup. Receipt plus passed shop testing enables repaired pickup.
14. Unrepairable/rejected item return enables an explicitly unrepaired collection without a fake successful test.
15. Customer advance/partial/final receipt/refund reconciles without duplicate postings, incorrect signs, or float rounding errors.
16. Vendor opening balance, charges, credits, partial/bulk payments, refunds, round-off, and carry-forward reconcile. Include the Rs 3,553 to Rs 3,550 settlement example.
17. Customer refusal does not erase a valid vendor payable; collecting an item does not settle either ledger automatically.
18. One shared transport expense allocated over two jobs is not counted twice; a part included in a vendor bill is not an extra cost.
19. New internet outage does not block intake/payments. Queued notifications survive restart, respect consent, and suppress obsolete quotes/pickup reminders.
20. Two attempted worker runs/double-clicks do not duplicate local financial/outbox entries. Ambiguous provider outcomes are flagged safely. SMTP acceptance is not claimed as delivery.
21. Dashboard counts agree with item-level custody; accessories, sold items, transit, and overlapping operational views are not double-counted.
22. Backup during normal operations restores database, attachments, balances, and custody consistently. A missing external drive is reported truthfully.
23. Read-only backup viewing changes neither live data nor external messages. Restore requires owner confirmation and prevents automatic historical notification replay.
24. Corrupted/incomplete archives, disk-full, interrupted backup/restore, invalid archive paths, and incompatible schemas preserve the live/last good data.
25. Application upgrade migrates a populated database with existing customer history intact. Limited-role users cannot bypass restrictions by calling services directly.
26. Bulk-data searches and ledgers meet measured practical targets, and long-running work leaves the UI responsive.
27. A fresh Windows installation launches without a separately installed Python; core workflows work with network disconnected and persist across restart.

Use a traceability matrix linking requirements to implementation and tests. Add focused invariant/property tests where useful for money allocations and custody conservation. Do not spend effort on tests that only mirror labels or trivial getters.

## 18. Implementation sequence

Implement all stages as one coherent application, keeping each stage runnable:

1. Repository inspection, concise architecture/schema design, requirement mapping, application shell, first-run setup, migrations, and role foundations.
2. Reusable directories, customers, sales/warranty register, intake, received items, and printed intake receipts.
3. Custody/dispatch/receipt, repair assignments and work, warranty decisions, quotations/approvals, and collection guards.
4. Financial posting, customer accounts, vendor monthly settlement, transport allocation, refunds, and documents/reports.
5. Actual dashboard queries, filters, notifications/outbox, provider adapters/settings, and safe offline behaviour.
6. Backups, historical viewing, safe restore, representative performance work, Windows packaging, and full acceptance verification.

Integrate tests with the relevant stages rather than postponing all verification. Maintain a durable progress checklist and resume from completed work if the session is interrupted. Complete the full required scope; do not stop after the first stage or leave essential screens as TODOs.

## 19. Deliverables and definition of done

Deliver:

- Complete source with a clear modular monolith structure, dependency specification/lock, migrations, and local assets.
- A runnable native app and actual persisted workflows, not UI-only demonstrations or in-memory production data.
- Automated tests, synthetic demo/benchmark generators, and a requirements/acceptance traceability matrix.
- Readable architecture/data-model notes, business-state rules, ledger conventions, and backup format/restore procedure.
- README with exact environment setup, development launch, tests, demo-data generation, packaging, and installation commands. Provide tested PowerShell scripts for Windows where possible.
- Windows distribution/installer when built on a suitable Windows environment. If unavailable, supply the build inputs and exact commands, clearly label the Windows artifact as not built, and do not mislabel a Linux binary as a Windows executable.
- Owner/staff user guide explaining intake, accessory checklists, warranty, dispatch/receipt, customer quote approval, monthly vendor settlement, messaging setup, archives, and recovery.
- Document actual WhatsApp/email setup and capabilities, credential handling, current limitations of inbound/delivery confirmation, and costs/account prerequisites without pretending these are configured.
- Release notes and concise final report: implemented features, test/benchmark results, artifact locations, setup tasks still requiring the owner's external accounts, and any concrete unresolved defects.

The product is complete only when the specified business rules are implemented end to end, persisted across restarts, and meaningfully verified. External accounts and an unavailable Windows host may remain explicitly listed setup/validation dependencies; they must not be hidden behind a claim that live messaging or a Windows installer was tested.

Start by inspecting the repository, briefly state the architecture and assumptions, and then build the application through the stages above.
# Customer registration and intake UX — September 2026

Implement the attached four-step Customer → Product → Repair → Confirm workflow. Registration requires name, phone and address with optional alternate/email and camera/upload photo preview. Detect matching phones and require an explicit existing/new customer choice. Intake supports sales-history autofill, dated warranty badges, external warranty details, category-specific reusable accessories, service recommendations, optional due dates and currency inputs. Preserve mandatory intake photos, multi-product visits, draft recovery, consent and all existing financial/workflow rules. Limit redesign to these forms; retain schema 9.
# Repair journey presentation — September 2026

Redesign only JobWorkspace presentation. Derive a connected journey from the existing lifecycle snapshot, tracker and audit; show completed/current/upcoming/blocked/outcome states with text and icons, route-specific future paths only when known, and the existing primary handler within the current node. Historical nodes are read-only details. Keep tabs, authorization, transitions, payments and all existing data unchanged. Compact the operational summary and group workspace details. Verify guided and legacy jobs, rework, all routes, held/unrepaired outcomes, resizing and action dispatch.

# Repair journey presentation, second pass — September 2026

Close the presentation gaps in the first pass without touching business logic.
The journey must adapt to the window: connected stage cards when it has height,
a wrapping horizontal rail when it has width instead. At the route decision point
show the routes the application actually defines as still open, and no route's
stages until one is chosen. Lifecycle stages are clickable for history only and
carry stage, status, time, staff, location, route and blocking reason on hover.
Status colour, icon and wording must have a single definition in the shared
design system. Separate the current-stage primary action, stage-relevant actions,
general tools and administrative utilities so they are not equally weighted.
Group workspace detail so responsibility includes current custodian and physical
location, and show stored codes in the words staff already read elsewhere.
Verify every lifecycle stage, both branch routes, held and unrepaired outcomes,
legacy records, resizing, tabs and action dispatch. Retain schema 9.
