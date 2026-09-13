# Inventory, costing and custody update — 1.4.0

The existing PyQt6 application, Master Job IDs, repair parts, immutable Job Cards, quotations, accounts and device history remain the foundation. This release extends those services; it does not create a second inventory or custody database. The detailed request is retained in `INVENTORY_CUSTODY_REQUIREMENTS.md`.

## Database and migration

Schema 9 extends `stock_items` with SKU, category, compatibility, serial/batch identity, supplier and purchase evidence, storage/minimum stock, default warranty and markup metadata. `repair_parts` gains reservation/issue location, procurement state and requester notes. `stock_movements` retains previous IDs and quantity deltas while adding reservation/issue deltas, movement type, quantity, sender/receiver, job/part/repairer references, metadata snapshots and operation IDs. Immutable triggers protect movements and installed history.

`manual_warranty_checks` is an append-only evidence register linked to the existing job/device/attachment architecture. Claims gain original-status/outcome fields. Effective warranty state is derived from active claims, with an audited owner override for exceptional corrections.

The existing verified pre-upgrade backup runs before migration. Schema 8 balances, installed parts, warranties and issued card snapshots are preserved in migration tests. Historical stock adjustments are explicitly labelled legacy; no missing dispatches, purchases or warranty records are invented. Development and verification use isolated synthetic databases; the live shop database has not been migrated or reset during this work.

## Inventory and stock architecture

`Inventory` operates on the existing stock ledger. Owned stock is the sum of stock deltas. Available stock equals owned stock minus reservations and physical issues. Reserving or issuing therefore prevents another job using the same unit without prematurely consuming owned stock. Actual installation records the consumption and binds the part to device history.

Supported events include receipt, adjustment, reservation, release, issue to technician/vendor, unused return, installation, damage, scrap, warranty replacement receipt and customer return receipt. Each event records staff, timestamp, evidence, locations and related job/part where applicable. Issue/unused-return events create printable part-transfer Job Cards in the same job timeline. Part cost and warranty metadata are snapshotted from the planned part.

Commands use database transactions. Insufficient stock, duplicate serialized units and invalid transitions fail without partial updates. A failed transfer-card creation rolls back its stock event. Two independent database connections competing for the last available unit produce one successful reservation. Receipt operation IDs make retries idempotent.

## Sourcing, costing and customer approval

Adding a required part opens an inventory search first. The operator can use shop stock, the assigned repairing third party, an external supplier or another documented source. For repairing-third-party supply, the assigned vendor is filled and locked in the form and enforced by the service. Another company must be recorded as an external supplier. Supplier parts have explicit order/receipt steps.

The owner-only Internal costing tab separates shop/supplier/vendor parts, vendor labour, transport, other expenses, service-centre charges and in-house costs. Structured vendor parts replace the old aggregate vendor-parts budget in calculations, avoiding double counting. It shows total internal cost, latest customer quotation, previous approved amount and expected margin.

Customer quotations use the part selling price and independently entered customer labour/other charges. Revision preview shows prior approval, newly quoted parts, revised total and the price difference. The existing versioned approval guard requires a fresh decision when the part specification changes. Customer PDFs and counter projections omit purchase costs, vendor costs and margin; owner internal return-card copies are explicitly marked on the title and footer.

## Device custody and Job Cards

The existing item holdings/movements ledger is authoritative for physical possession. Route, stage, assigned worker, current custodian and destination are separate projections.

Courier dispatch creates Shop → Courier custody, with the vendor/service centre as the destination. Confirmed arrival creates Courier → Repairer. Reverse transit records Repairer → Courier → Shop. Direct handover remains available. Transit statuses no longer claim that a courier-held device is at the repairer. Accessories in transit do not incorrectly make a device already at the shop appear in transit.

In-house assignment records work responsibility. The assignment dialog can also record an actual handover with condition, acknowledgment and work area. Otherwise the device stays at the counter and the next action requests handover. Paid work requires physical handover on the new workflow; final QC requires return from the technician to the shop QC/storage location. Returning the device earlier for reassignment preserves its repair stage and allows a route change without prematurely advancing to QC.

Return cards preserve repairer identity even when the actual sender is a courier. They snapshot result, receipt status, diagnosis, work, installed/reported parts and their warranties, invoice/reference, manufacturer warranty/RMA, replacement information, condition, accessories, receiver and acknowledgment. Internal copies additionally show the saved cost breakdown. Later cost/catalog edits cannot rewrite issued cards. Partial returns retain outstanding custody rather than falsely completing device receipt.

## Warranties

Inventory defaults populate planned parts. Installation creates an independent installed-part warranty with its own start/expiry/provider/terms. Later catalog changes do not change issued warranties. Zero duration is displayed as warranty not recorded.

Manual checks record VALID, INVALID or UNVERIFIED, evidence type/reference, provider, coverage, staff, timestamp, notes and optional attachment. Accepted checks allow a documented warranty-service route without creating fictional historic inventory or installed-part records.

An active claim displays CLAIM IN PROGRESS and disables ordinary warranty editing. Owner override requires an explicit exceptional action and reason and creates an audit event; it does not hide the active claim. Rejected claims release the claim-derived state so normal coverage/expiry applies again.

## Screens and operation

Use **Inventory** for catalog, availability, low/out-of-stock filtering, receipt/adjustment, suppliers, movement history, installations and claims. Use a job's **Parts** tab to plan, reserve, issue, return, release, order, receive, install or write off a part. Use **Internal costing** for owner budgets, **Job Cards** for issued evidence and **Warranty** for coverage/claims/manual verification. Stock and custody actions appear in the Repair timeline and drive the next-action prompt. Parts and warranty tabs scroll at smaller window heights.

## Files

Added application files: `repairshop/inventory.py`, `inventory_ui.py`, `migration9.py`, `part_editor.py`, `costing.py`, `costing_ui.py`, `custody.py`.

Modified application files: `repairshop/__init__.py`, `persistence.py`, `parts.py`, `parts_ui.py`, `lifecycle.py`, `lifecycle_ui.py`, `job_cards.py`, `warranties.py`, `queries.py`, `ui.py`, `ui_widgets.py`; package version in `pyproject.toml`.

Added verification files: `tests/test_inventory_custody.py`, `tests/test_inventory_ui.py`, `tests/schema_fixtures.py`, `scripts/inventory_demo.py`. Updated `tests/test_lifecycle.py`, `tests/test_parts_cards_warranty.py`, `tests/test_visit_intake.py`, `scripts/lifecycle_demo.py` and `scripts/build.ps1`. Added this report and the requirements document; updated README, release notes and user guide.

## Validation

Full suite: **166 passed in 60.94 seconds**, with no warnings, using `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --junitxml=docs/test-results.xml`.

New tests cover catalog creation/search/markup, low/out-of-stock, receipt retry, reservations, concurrent last-unit contention, issue to both repair routes, unused returns, write-offs, installation, serialized/generic stock, rollback on card failure, source/vendor enforcement, separate internal costs/selling prices, public-document redaction, warranty snapshots, manual evidence outcomes, active-claim locks/override/rejection, forward/reverse/direct custody and schema-8 migration preservation. Six real Qt dialog tests cover catalog input, inventory-first selection, vendor lock/cost visibility, quote revision review and warranty controls.

Nine synthetic UI views were inspected, including inventory, parts, costing, forward/reverse courier custody, assignment/handover, return cards and manual warranty. Four representative PDFs were rendered and inspected: courier handover, part transfer, public return and internal return. Existing lifecycle, quotations, intake, customer photos, accounts, backups and legacy migration tests are included in the full suite. The earlier end-to-end demo generator also ran against a fresh isolated database, producing all 11 scenarios including a closed repair and a returning warranty job.

Build output is staged under `dist/releases/1.4.0` to preserve an executable that may already be running. The distribution ZIP must contain exactly `RepairShopManager.exe`. `scripts/verify_package.py` checks archive integrity and launches/restarts the extracted executable with development environment paths removed; its results and SHA-256 are saved in `docs/package-verification.json`.

Final package verification passed: exactly one EXE, ZIP integrity passed, 71,953,163 bytes, extracted launch/restart exit codes 0/0 in 3.813/3.484 seconds. No shop data or standalone source files are included in the archive.

## Assumptions and remaining limits

- Owner is the authorized internal-cost/admin role; counter staff operate sourcing/custody with selling prices. No new permission hierarchy was introduced.
- Costing is an internal repair budget. Actual vendor bills and payments remain separate entries in the existing vendor accounts ledger; recording a budget does not post or pay a bill.
- Inventory uses a catalog/serial/batch unit cost snapshotted at part planning. Automatic FIFO or weighted-average valuation across receipts is not implemented; separate batch/SKU records can represent different lots.
- Stock issues/returns apply to the quantity of one planned part row. Split rows before reservation for separate physical issues or partial unused returns. Device/accessory custody retains its existing partial-quantity support.
- Warranty replacement/customer-return stock receipts require owner evidence; they do not automatically resolve a warranty claim or reverse an installed-part history entry.
- Physical handovers and external confirmations are recorded by staff; courier tracking is not integrated. Manual warranty acceptance is evidence recorded by the shop, not an external warranty-provider verification service.
- Older issued cards remain exactly as issued. New structured fields appear on newly recorded cards; missing old costs/custody/warranty evidence is not inferred.
- Package verification uses this Windows host with development paths removed, not an independent clean Windows VM. The EXE embeds bytecode/runtime dependencies; a single-file distribution prevents shipping loose source files but is not a guarantee against reverse engineering.

Close the old application, extract the new ZIP into a fresh folder and launch its EXE. Existing production data remains in `%LOCALAPPDATA%\RepairShopManager`; startup performs the backed-up schema upgrade when needed.
