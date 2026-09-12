# RepairShop Manager 1.2.0 implementation report

The existing desktop application now follows the supplied repair diagrams through intake, three repair routes, parts and approval, shop quality checks, payment, delivery and closure. One Master Job contains its receiving, assignment, dispatch, return and delivery cards. Installed parts, stock movements and warranties are structured records; a future warranty claim uses a new job linked to the original repair.

## 1. Existing architecture discovered

The application uses native PyQt6 widgets and service-owned transactions over SQLAlchemy-managed SQLite connections. Persistence uses parameterized SQL, rather than SQLAlchemy ORM classes. Existing customers, stable physical devices, jobs, assignments, work, manufacturer warranty decisions, quotations and approvals, customer/vendor ledgers, item holdings and movements, photos, attachments, outbox, customer folders and verified backups were reused. There was no existing spare-parts inventory to reuse.

## 2. Files modified

- `repairshop/persistence.py`: schema dispatch, nested savepoints, shared transaction connections and consistent read snapshots.
- `repairshop/services.py`: intake/card integration, device brand/model, assignment cards, current-part quotation and approval integration, managed lifecycle guards.
- `repairshop/domain.py`: additional lifecycle stages and reusable supplier directory kind.
- `repairshop/ui.py`: dashboard, guided navigation, active/history lists, intake, quotations, directories, reports and safe background-task window cleanup.
- `repairshop/ui_widgets.py`: internal-price display and worker lifetime handling.
- `repairshop/customer_records.py`: customer overview indicators and complete folder projections for cards, parts, warranties and claims.
- `repairshop/customer_ui.py`: returning-device warranty lookup and customer overview columns.
- `repairshop/documents.py`: saved card printing, private external manifests, final invoices and structured warranties, local display time.
- `repairshop/queries.py`: job-card, parts, part-warranty and claim reports.
- `repairshop/__init__.py`, `pyproject.toml`: version 1.2.0.
- `scripts/verify_package.py`: verify the extracted EXE against the separate v1.2 synthetic database.
- Developer README, release notes, progress log and verification artifacts.

## 3. Files added

- `repairshop/migration6.py`, `repairshop/migration7.py`.
- `repairshop/lifecycle.py`, `repairshop/lifecycle_ui.py`.
- `repairshop/job_cards.py`, `repairshop/parts.py`, `repairshop/warranties.py`, `repairshop/parts_ui.py`.
- `tests/test_lifecycle.py`, `tests/test_parts_cards_warranty.py`.
- `scripts/lifecycle_demo.py` and lifecycle requirements/design/report documents.
- Synthetic screen captures under `docs/screenshots/lifecycle-*-v12.png`.

## 4. Database changes

Schema 6 adds `jobs.lifecycle_version`, `jobs.lifecycle_data` and a lifecycle index. Schema 7 adds `job_cards`, `stock_items`, `stock_movements`, `repair_parts`, `part_warranties` and `warranty_claims`, with foreign keys, indexes and history-preservation triggers.

There is no duplicate customer, device, master-job, custody, estimate or financial ledger. Stock on hand is the sum of stock movements. Current physical custody remains the existing holdings ledger. Customer amounts remain integer paise in the existing financial tables.

## 5. Migration details

The existing migration engine creates and validates a complete pre-upgrade archive before migrating a saved database. Migrations proceed through the existing versions to schema 7; they do not delete or recreate a shop database. Old job stages, stable device IDs, payments, quotes, photos and customer folders remain intact.

Old jobs are marked legacy through the new default fields. No historical job cards or installed-part records are invented. An operator can review a legacy job and enable guided actions going forward. Previously ready legacy jobs require a real readiness/QC review. Unknown legacy states stay visible and require review.

Tests cover upgrades from schemas 5 and 6, verified backups, preserved financial/photo/device/custody data, and empty new card history for legacy records. Development and release checks used isolated synthetic data folders; the production data directory was not modified.

## 6. Master Job and Job Cards

The existing immutable `REP-YYYY-NNNNNN` number is retained as the Master Job ID. Cards use `REP-YYYY-NNNNNN / CARD-01`, `CARD-02`, and so on. Selecting a different route does not create another Master Job.

New intake creates a receiving card. In-house assignment creates an assignment card. Guided external dispatch, carrier arrival, return and customer delivery create event cards within the same transaction as the actual assignment/handovers. Partial returns contain the quantities actually received; outstanding accessories remain with their recorded holder.

Cards preserve party details, device/type/brand/model/serial, complaint, condition, included items, photo references known at issue time, effective/recorded times, staff, expected return, external reference and acknowledgment. Cards cannot be edited or deleted. Printing is separately audited. Existing holdings and movements remain the source of custody truth.

## 7. Lifecycle statuses

Received → Initial inspection → Warranty check → Route selection. In-house repair continues through diagnosis, estimate, approval, optional parts waiting, repair and technician testing. External routes use dispatch, optional carrier transit/arrival, external diagnosis, warranty or paid approval, repair result and return to the shop.

All routes return through Final shop QC → Billing → Ready for Delivery → Delivered → Closed. Declined, cancelled, unsuccessful and not-repairable outcomes use an explicit unrepaired return check. They do not acquire a false successful-repair result. QC failure returns the job to diagnosis or a fresh external dispatch. Route changes and rework remain in the timeline.

The stored stages and detailed compatibility mapping are documented in `REPAIR_LIFECYCLE.md`.

## 8. Physical location

The existing locations remain `shop:*`, `technician:*`, `vendor:*`, `centre:*`, `transit:*`, `customer` and owner-documented `exception:*`. The main screen derives location and responsibility from actual holdings and assignment records. A selected route is not treated as proof of dispatch. External repair completion is not treated as proof of return.

Customer delivery requires all unresolved items to be at the shop, completed QC and billing review, customer acceptance, accessory confirmation, payment/refund review and a named receiver/acknowledgment. Multi-item delivery is atomic. Owner-authorized credit or custody exceptions require recorded reasons. Closure requires delivery and closed warranty claims.

## 9. Parts model

Each part records job/device, name/type/brand/model/part number/serial, quantity, source, stock reference, supplier snapshot, invoice and purchase date, purchase cost, selling price, installation details, warranty duration/unit/provider/terms, current status, revision, and linked estimate/card. Serialized parts require one unit per row.

Planned parts may be edited or removed with audit. Installed parts cannot be overwritten or deleted. Installation requires an approved current estimate that includes the exact part revision and selling price. Stock usage and part warranty creation are in the same transaction as installation.

Adding, removing or changing quoted parts supersedes the old quote's approval state while preserving its issued content and recorded decision. The job returns to Prepare Estimate. The Parts tab contributes its lines automatically; the quote form accepts labour, vendor service, transport, other charges and discounts. Prices are per unit; quote totals include quantity.

## 10. Supplier and stock source model

Sources are shop inventory, external supplier, supplying third-party technician, and other with an explanation. The existing master directory supports a supplier kind and reuses vendor records where appropriate. A supplier can be created directly from the part form. The supplier name/contact/details are snapshotted for history.

The owner can create stock items and receive/correct quantities through Parts → Shop stock. Selecting stock pre-fills its part details and prices. Installation consumes stock; shortages are blocked. Immutable stock movements preserve purchase/correction references and usage linked to the repair. This is a minimal spare-parts inventory, not a separate purchasing/accounting application. Supplier invoices can be attached using the existing document tools.

## 11. Warranty model

Installed parts with a positive duration automatically receive a structured warranty linked to job, stable device and installed part. Days use calendar-day addition; months and years use calendar arithmetic, clamping month-end dates appropriately. The expiry date is inclusive. Warranty starts at the recorded installation date. Stock purchases do not start the customer's installed-part warranty.

The Warranty tab also allows a separate repair/workmanship warranty. Statuses include ACTIVE, derived EXPIRED, CLAIMED, VOID and REPLACED. Original start, duration, expiry, provider, coverage and installation details remain queryable. Owner corrections require a reason and record previous values and changes in audit. Manufacturer/OEM warranty decisions remain in their original separate model.

## 12. Warranty claims

Selecting an existing device at intake shows active repair/part warranties. A claim must belong to a new active Master Job for that same stable device; the original repair and installed-part record stay intact. The claim links new job, original job, device, part and warranty, with complaint and resolution history.

Transitions are OPEN → ACCEPTED → IN_REPAIR → REPLACED/COMPLETED → CLOSED, or OPEN/ACCEPTED → REJECTED → CLOSED. Replacement requires a part actually installed on the claim job. Expired claims require an explicit owner override reason. A delivered claim must be resolved and closed before the Master Job closes.

Warranty repairs with structured parts use an approved zero-charge estimate when the customer owes nothing. This keeps agreement on the work and replacement parts explicit. Paid extras still require a current approved estimate. Completing a nonreplacement repair does not silently extend the original warranty period.

## 13. UI changes

The main workspace shows Master Job, device, customer, current card, manufacturer warranty and part/claim indicators; status, location, responsibility, pending time, expected dates, estimate, payments and the next action are readily visible. A tracker shows actual completed steps, not assumed legacy history.

Tabs contain Repair workspace, Device photos, Repair timeline, Items and location, Job Cards, Parts and Warranty. Existing detailed diagnosis/quotes/finance/documents remain available through Full records and action dialogs. Parts has a selected-row summary so price, installation and warranty remain readable without scrolling every column.

The dashboard has 13 clickable summaries and an attention list. Counts use SQL aggregates for the full database, while detailed attention rows are bounded to the latest 50 matches. Active repair tables support searching, filtering and paging. Customer overview/history includes current card, physical location, next action and warranty indicators. New reports cover cards, parts, warranties and claims.

## 14. Printing

Receiving receipts, all issued job cards, delivery receipts and final invoices use the existing ReportLab/PDF/attachment pipeline. Printing an external manifest selects the saved external card; a legacy record without an actual card requires a reviewed future handover instead of fabricating a manifest.

External card snapshots and PDFs use the shop as sender/customer, with the repairer's details. Original customer contact records, address, email and customer photo are excluded. Device photo references are identifiers rather than customer-folder paths. Operators remain responsible for the content of their own free-text notes.

Customer invoices show selling prices and approved charges, installed parts and warranty details, invoiced amount and remaining balance. Purchase cost and internal margin are omitted. PDFs display event time in IST. Four synthetic A4 documents were rendered and visually inspected; each sample fits one page. Text extraction also verified vendor privacy, final selling prices and warranty expiry.

## 15. Existing functionality preserved

Required customer photos, resumable drafts, stable devices, product photos, customer folders, original jobs and immutable numbers, manufacturer warranty history, versioned quotes and decisions, customer/vendor ledgers, advances/refunds, bill reversals, movements, attachments, outbox, backups and archive behavior remain in the existing architecture. Customer folder projections now also include the new structured records.

The direct legacy service API remains compatible; new desktop intake explicitly enables the guided workflow. Guided records cannot bypass their lifecycle using old arbitrary stage/movement shortcuts. No external messages were sent during verification.

## 16. Tests added

`test_lifecycle.py` covers the three routes, warranty rejection and route change, external replacement, parts waiting, quote decline, unsuccessful returns, final QC failure and redispatch, partial accessory return, refunds, owner credit, stale forms, role checks, atomic handover rollback, migration, legacy review, read consistency and real Qt workspace rendering.

`test_parts_cards_warranty.py` covers receiving/assignment/dispatch/return/delivery cards, sequential IDs, party snapshots and privacy, printable documents, each part source, cost/price/margin, automatic quote lines, revised approval, installation and stock rollback, installed history, month-end/leap-year expiry, warranty permissions/expiry override, new-job lookup and claim references, full warranty replacement through delivery/closure, dashboard filtering, migration 6, the new tabs, reports and customer folder history.

## 17. Verification results

**121 automated tests passed** on Windows (35.80 seconds). The JUnit result is `test-results.xml`; command output is in `runtime/final-release-tests.log`. This includes all existing tests and the new lifecycle, card, parts, warranty, migration, report and window-cleanup coverage. The final service-center case checks explicit approval of tracked zero-charge warranty parts.

Nine synthetic screenshots are stored in `docs/screenshots/lifecycle-*-v12.png`. The separate demonstration folder is `runtime/lifecycle-v12-demo`, containing eleven scenarios, including a future warranty claim. Demo login is `demo` / `DemoShop2026!`; these credentials are never created in production.

The actual portable ZIP was extracted and verified: **exactly one member, `RepairShopManager.exe`**. ZIP integrity passed. Both extracted launches exited successfully (0 / 0) with only Windows System32 on PATH and developer Python environment variables removed. ZIP size: 71,827,823 bytes. `package-verification.json` records the hash, launch timings and full evidence.

## 18. Assumptions

- Existing REP numbers are the Master Job IDs; renumbering saved cases would break traceability.
- Cards record completed events. Preparing dispatch alone does not falsely indicate physical handover.
- Installation consumes stock and begins part warranty. The owner records stock receipts/corrections.
- Repaired devices use positive QC; unrepaired returns use condition verification.
- Customer approval covers structured parts even for a zero-charge warranty replacement.
- A4 is the current printing format; PDFs can be printed using the installed Windows PDF viewer.
- Existing GST/tax configuration and ledger rules are retained; no new tax engine is introduced.

## 19. Remaining limitations and risks

- Verification ran on this Windows workstation, including synthetic Qt renders and extracted-package launches. It is not a separate clean Windows VM or new real-camera/printer hardware certification.
- Existing historical parts or warranty details kept only in free-text notes are preserved, but not automatically converted into asserted installed-part/warranty records.
- Full parts/history tables may require horizontal scrolling. The selected-part summary and job header keep essential actions and values visible.
- Minimal stock tracking does not create purchase orders, supplier payment entries or bank transfers automatically. Existing accounts and attachments remain the tools for actual payable records.
- Old issued PDF files stay intact. Generating another final invoice reflects current warranty status and ledger balance; retain the original issued document when an exact historical copy is needed.
- The portable ZIP contains only the application EXE, with embedded Python bytecode and runtime dependencies. This avoids distributing loose source files; it is not protection against determined reverse engineering.
- The EXE writes shop data outside its own file, to the existing configured data directory. A running older application should be closed before opening the update against that same shop data.
