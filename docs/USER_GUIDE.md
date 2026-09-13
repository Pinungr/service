# RepairShop Manager: owner and staff guide

## Start your shop

Extract the Windows distribution and run RepairShopManager.exe. Enter the shop name, owner name, username and a password of at least 10 characters. This creates a live database in your Windows local application-data folder. Configure the address, opening hours, default return policy, backup location and external-drive destination under **Settings & staff**. The defaults are INR, Asia/Kolkata, 30 daily recovery copies, a permanent archive every 90 days, and test-mode messaging.

Create separate logins for counter staff and technicians. Owners manage financial corrections, vendor accounts, settings and restoration. Counter staff handle intake, customers, communications, handovers and receipts. Technicians record findings and repair progress for their assigned jobs. Disabling a staff login takes effect in service checks, including already open sessions.

## Customer, sale and intake

Search **Customers** by name or phone before creating a record. Shared phone numbers are allowed; people are not automatically merged. Record channel consent separately for email and WhatsApp. Customer history groups jobs, products, quotations, payments and messages.

Use **Products sold** for a lightweight sold-device and warranty register. Record the serial if known, sale and invoice dates, sale price, optional cost, warranty provider/dates/terms and purchase proof. Record product collection separately. Select a sale and choose **Warranty/service job** to link the repair to it.

Choose **New intake** or press Ctrl+N. Select the device owner; preserve the submitter and their relationship if another person brings it in. A separately saved, authorized contact can also receive updates. Select the product category and service; **+ Add new** saves reusable choices. Every intake starts with accessory checkboxes unchecked. Check only what was actually received. Loose RAM belongs in this checklist; RAM already installed inside the computer belongs in repair work.

Enter the fault, visible damage, serial (optional), shop storage location, repair route, estimated dates, deposit requirement, agreed transport/assessment charges and consent. The return policy is copied into the job and is unaffected by later default changes. An advance records money already received, without initiating a bank transfer. A printable intake receipt is generated in the background. Add photographs or evidence from the job detail.

Each primary device gets its own immutable REP job number. Reuse the visit reference to group devices from one customer visit. A follow-up after collection is a linked new job.

## Physical custody and collection

Selecting a vendor assigns responsibility; it does not move the device. Open **Dispatch & receive** or the job's **Move / collect items** action. Select the exact item and its current holder, quantity, actual destination, counterparty and tracking/reference. Moving a laptop does not move its adapter or mouse. Partial quantities remain at the previous holder.

For transport, record departure to an **In transit** holder. Only record receipt at the centre/vendor/shop when the actual receiving person acknowledges it. Expected dates are not receipt evidence. View all outstanding items in the job's Items & custody tab.

For repaired collection, receive the main device at the shop and record a passed test before marking **Ready repaired**. A vendor completion report uses **Awaiting return** and does not invite immediate collection. For an unrepaired return, choose **Ready unrepaired** and document the outcome and return check; a false passed-repair test is not needed.

Customer collection requires the collector and acknowledgment for each selected handover. Return all items or have an owner explicitly resolve an exception with a reason. Partial collections remain visible. Only then mark **Collected** or **Closed**. Neither action settles customer or vendor debt.

## Repair work and warranty

Open the job to view clearly named tabs for custody, work, assignments, warranty, quotes, accounts, expenses, movements, documents, messages and audit history. Record diagnosis, actions, installed parts, start/completion details and service warranty. Switch assignments to another vendor when needed; previous records remain.

Warranty date eligibility is separate from the centre's decision. Record pending, accepted, rejected or partial coverage with RMA, findings, covered/excluded work, and evidence. Approved warranty work can be no-charge, while transport or handling remains separately agreed. Rejection can lead to a paid quote or return without repair. A replacement records both serial identities, evidence and the warranty terms actually supplied; no fresh warranty is invented.

Revise estimated repair, collection and return dates with a reason. Dates use calendar days. Set or release an on-hold/cancellation reason without losing custody or money obligations.

## Quotations and customer decisions

Issue an itemized quotation using one `Description | rupee amount` per line. Discounts are negative. Include only customer-facing prices. Taxes, when applicable, must be explicitly configured and described; the app does not determine tax law or certify statutory invoice compliance.

An issued quote is immutable. A revision creates a new version and supersedes old approval. Record explicit approval or decline against the exact version, including who authorized it, the channel and evidence. Sending, reading or an unrelated message does not authorize repair. Paid repair requires current approval and the job's required deposit. Repair work records enforce the same guard as the stage action.

An owner issues the customer bill from an approved quote. If a prior bill remains posted, reverse it with a reason before billing a full revised quote. For declined work, the **Agreed decline charges** action shows allowed charges, money retained and balance/refund due. No-charge and agreed-transport policies remain distinct. A refund due is not a paid refund; record the actual refund separately.

## Accounts and monthly vendor settlement

All amounts are stored as integer paise. Enter decimal rupee amounts; rounding is half-up to the nearest paise. Entries are append-only. Corrections use a reversing entry, preserving actor, date and reason.

Customer account: opening receivable + issued charges − credits − receipts + refunds paid + signed adjustments. Vendor account: opening payable + confirmed charges − credits − payments + refunds received + signed adjustments. Negative balances remain visible as credit/advance. Opening balances require provenance. Customer receipts are allowed for counter staff; vendor entries, refunds, bills and corrections require the owner.

One payment may allocate across charge entry IDs. Enter `charge ID | rupee allocation` per line. Allocations cannot exceed the payment or the selected charge; the remainder is unapplied. Use cash, UPI, bank or reusable methods and preserve references/evidence. No actual transfer is initiated.

In **Monthly ledger**, choose the account and posting-date range. Opening and closing balances carry across periods. Estimates and unfinished vendor work are displayed separately from confirmed payables. For the example in the brief: post INR 500 opening, INR 1,250 and INR 1,803 charges, an agreed adjustment of −INR 3 with a reason, then INR 3,550 payment. Closing payable is zero. Payment does not return a device or finish a repair.

For a shared transport expense, record the actual cost once and allocate it across jobs so portions exactly equal the total. A part or transport already included in a vendor bill is marked with that bill entry ID to avoid counting it again in margins. Customer charges remain governed by quotations. Margin means billed revenue less recorded costs before overheads; receipts and payments affect cash flow separately.

## Documents and reports

Generate job cards, intake receipts, handover manifests, quotations, bills/receipts/refund acknowledgments, collection receipts and warranty summaries from the job. Generated PDFs are saved in managed storage and listed under Documents. Double-click to open/print. Issued documents remain snapshots even after current records change. Monthly statements can also be saved as dated PDF snapshots.

Reports support jobs, custody, overdue work, warranty, customer/vendor dues, payments/refunds, transport and margins, with relevant date/route/customer/category/repairer filters. Export PDF, Excel or CSV in the background. Text beginning with spreadsheet formula characters is neutralized.

## Messages

Test mode captures messages locally and contacts nobody. Review destination, exact saved body, state and error in **Notifications**. Owners configure official WhatsApp and TLS email settings. See MESSAGING.md before enabling live mode. The worker runs only while the application is open and catches up after restart.

Accepted means the provider accepted the request; delivery/read status is unknown without genuine external confirmation. Uncertain submissions are not blindly retried. Current consent, destination, quote version and pickup relevance are checked again before sending. Cancel obsolete records. After restoration, outgoing notifications remain paused and historical entries require reconciliation.

## Backups, historical viewing and restoration

Every active staff session checks for due backups at launch and hourly; backup configuration and restore controls remain owner-only. **Backup now** makes a verified recovery archive. Long-term archives are kept until the owner explicitly manages them outside the app. Missing external drives remain pending; the verified local backup survives. Connect the configured drive and choose retry pending copies.

Archives contain the database, every referenced managed file, settings, schema/application versions and a checksum manifest. Secrets are excluded. Use **Validate archive** to check checksums, database integrity and completeness.

**Open backup for viewing** creates a separate read-only view. It does not overwrite live data, migrate the archived database or send messages. Close that viewing window when finished.

**Restore backup** previews the timestamp, record counts and schema. Wait for background work to finish. Type RESTORE only after reviewing the exact archive. The app takes a safety backup, installs database plus attachments together, preserves the previous files in a recovery directory and pauses outgoing messages. Restart and sign in using the restored credentials. If replacement is interrupted, startup uses the recovery journal to restore the previous state. A newer unsupported schema is rejected.

Use a verified local drive for live data. An external backup copy can be stored elsewhere; a shared SQLite file is not a multi-computer deployment. A future LAN version would move the persistence boundary to a managed server and service API while keeping these domain rules.


## Customer webcam photos, drafts and permanent product folders

See [Photos and customer overview](PHOTOS_AND_CUSTOMER_OVERVIEW.md) for the version 1.1 intake photo requirement, owner/submitter labels, saved drafts, repeat physical devices, product photographs, consolidated readiness counts, local folders and photo recovery. Existing jobs remain accessible without photos or a camera.
# Inventory and custody in version 1.4.0

1. Open **Inventory → Add inventory item** as owner. Record the part, SKU, supplier, unit purchase/selling prices, shelf/bin and default warranty. Use serialized stock only when each item has its own serial. Save, then **Receive / adjust stock** with the invoice/reference. Low stock and Out of stock use currently available units.
2. Open the repair job's **Parts → Add required part**. Search inventory and choose **Use shop stock**. If sourcing externally, choose the assigned repairing third party or an external supplier. A repairing-third-party supplier is locked to the repair vendor. Record selling price separately from the owner's internal purchase cost.
3. For shop stock, select the part and **Reserve stock**, then **Issue to repairer** when physically handed over. Record the acknowledgment. A transfer card and timeline event are created. Use **Return unused** for a physical return, or **Release reservation** before issue. Owners can write off damaged/scrapped reserved or issued parts with evidence.
4. For supplier parts, record the order and receipt. Record vendor labour, transport and other internal budgets under **Internal costing**. Post actual vendor invoices/payments separately in Vendor Accounts.
5. Issue the customer quotation. Parts use their selling prices; add customer labour/other charges. Record explicit approval. Added parts require a revision and another decision; the review shows the previous amount, new parts and price difference. Start the repair and **Mark installed** only when the work actually happens. Installation starts the saved warranty and consumes issued stock.
6. For courier dispatch, name the courier at the physical handover. The device shows IN TRANSIT with its actual custodian and final destination. Confirm arrival when the repairer receives it. For return by courier, record return dispatch, then shop receipt. Leave the courier blank for a direct outbound handover. Return cards save the result, repair work, parts, invoices, condition and receiver.
7. In-house assignment asks whether the device has physically been handed to the technician. If it has not, it remains at the counter. Use **Hand device to technician** with a bench and acknowledgment before repair; return it to QC/storage after technician testing.
8. In **Warranty**, use **Manual warranty check** if the original evidence exists outside this database. Record the result and evidence. An active claim locks ordinary warranty edits; an exceptional owner correction uses **Privileged override** with a reason. Claim resolution remains a separate action.

Internal costs and margins are visible to the owner. Ordinary printed cards and customer documents omit them; **Print internal copy (owner)** includes a clearly marked saved cost breakdown.
