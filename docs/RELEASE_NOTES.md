# RepairShop Manager 1.3.1

Fixed the quotation decision failure caused by an accidental expiry date in 1900. New quotations now have an explicit optional expiry checkbox, a date picker starting next week and no selectable past dates. The service also rejects past expiry dates before issuing or superseding a quotation.

The decision form reloads the saved quotation and shows its validity before requesting a decision. Expired current quotations can be declined; approval requires a revised quotation. The revision button carries forward the scope, non-part charges and terms while the existing Parts tab supplies current structured parts. Already decided, replaced and inactive-job quotations show specific guidance; saved decisions and original quotation dates are never overwritten. The repair workspace flags expired quotations.

No database migration or production record edit is needed. Reopen the quotation in the updated application to record a decline, or use **Issue revised quotation** if the customer wishes to approve.

Validation: 138 automated tests passed in 44.78 seconds. New tests cover past-date rejection without superseding a valid quote, expired decline versus approval, today/no-expiry approval, obsolete or cancelled-job decisions and the real Qt decision/expiry/revision forms. Both updated dialogs were visually checked with synthetic data. Package verification is recorded in package-verification.json.

# RepairShop Manager 1.3.0

Repair/service choices now follow the selected product category. Desktop, Laptop, Printer and Phone have their own repair options; general services such as Diagnosis remain available across categories. Owners can set applicable categories in Directories when editing a service, and services added from intake belong to its selected category. Invalid category/service combinations are rejected when saving.

New Repair Intake accepts multiple devices for one customer visit. Fill a device, click **Add this product to visit**, repeat, then **Save visit**. The customer and saved photo carry forward; each device has its own category, service, fault, accessories, advance, stable device identity and repair job. Edit/remove queued devices before saving. Cancel preserves the complete draft. Saving receives all products in one transaction, so an invalid product leaves the whole visit as a draft without partial jobs or payments.

The result shows all jobs in the visit and offers a combined receiving receipt. Open **Same visit** from a repair workspace or search the visit reference in Active Repairs. Each device keeps its own receiving card and subsequent repair, billing and delivery history.

Schema 8 adds category/service relationships after a verified pre-upgrade backup. Existing customer records, jobs and historical service selections are preserved. Previously unclassified custom services remain general until the owner assigns categories in Directories. Production data was not used for development or testing.

Validation: 131 automated tests passed (47.04 seconds), including service filtering, mixed-customer rejection, transaction rollback, separate device advances/accessories, draft resume/edit/remove, duplicate-save protection and schema migration. Synthetic intake screens and the combined two-device PDF were visually checked. The portable ZIP contains only RepairShopManager.exe; release launch/restart verification is recorded in package-verification.json.

# RepairShop Manager 1.2.1

New Repair Intake now includes a New customer button beside customer search. The existing registration form opens inside intake, pre-fills the search name or phone, and selects the saved customer automatically. Entered device details stay in the intake form. Photo capture remains disabled with a clear explanation until a customer is selected. Cancelling registration preserves the prior selection. No database migration or data reset is required. All 123 automated tests passed (41.20 seconds), including nested intake registration and cancellation; the updated intake screen was visually checked with synthetic data.

# RepairShop Manager 1.2.0

Guided repair lifecycle, immutable sequential Job Cards, structured parts and stock, versioned part approval, installed-part/repair warranties and linked future claims are integrated into the existing desktop application. Schema 7 preserves existing records with a verified pre-upgrade backup. Full implementation and validation: `LIFECYCLE_IMPLEMENTATION_REPORT.md`. 121 automated tests passed on the release source. Final test and package evidence: `test-results.xml` and `package-verification.json`.

## Previous release

# RepairShop Manager 1.1.0 — local Windows release

This release implements a runnable native application with persisted customer/sales/intake workflows; reusable directories; item custody; repair assignments/work; warranty decisions/replacements; versioned quotes/recorded approvals; customer/vendor accounts; shared expenses; PDFs and reports; a durable outbound queue; verified backups, historical viewing and restoration.

Customer webcam capture, local product photos, persistent intake drafts, stable device identities, permanent customer folders and a consolidated overview are added without replacing the existing architecture. Schema 5 creates a verified full archive before upgrading existing data. See `PHOTOS_AND_CUSTOMER_OVERVIEW.md`.

## Validation

- Python 3.14.6, Windows 11 x64. Exact dependency versions are pinned in `requirements-lock.txt`.
- 73 automated tests passed, including real SQLite services and PyQt desktop interactions. The detailed acceptance coverage is listed in TRACEABILITY.md; the JUnit result is `test-results.xml`.
- Synthetic performance dataset: 60,000 customers, 100,000 jobs, 200,000 items/movements, 100,000 quotations and 200,000 account entries. Results and timing definitions are in `benchmark-results.json`.
- Native dashboard and intake were visually inspected on Windows. Version 1.1 customer overview, photo intake and missing-camera screens were rendered with the Windows Qt platform and visually checked; images are in `screenshots/*v11.png`. A generated intake receipt was rendered with Poppler and checked for readable text, table alignment and clipping.
- The end-user package is now a single PyInstaller executable. The portable ZIP contains only `RepairShopManager.exe`; standalone source, guides, build inputs and separate runtime folders are excluded. The runtime unpacks temporarily on launch. This packaging does not make the embedded program immune to reverse engineering.
- The packaged executable launched the synthetic demo and exited its smoke test with code 0 on this Windows host. The build excludes a conflicting development-tool ICU library so Qt resolves the Windows ICU ABI correctly.
- Measured hardware: AMD Ryzen 5 9600X, approximately 32 GB RAM, Windows 11. Current query p95 results: dashboard 528 ms, first job page 3.72 ms, customer search 9.81 ms, vendor monthly ledger 14.06 ms. These are repeated local measurements; the database-startup measurement excludes password hashing and Qt construction.

## Owner setup

Create production credentials on first launch. Configure shop details, backup destinations, staff roles and channel consent. Connect official messaging accounts only when ready; test mode is the default. Messaging tokens remain in Windows Credential Manager and must be re-entered after changing computers. OAuth access tokens require owner/provider renewal; a provider-specific refresh flow is not bundled.

## Practical limits

- Webcam behavior has automated fake-camera coverage. Real preview, permission prompts, driver compatibility and unplugging during capture require manual shop-hardware verification.
- Existing explicit sale/follow-up links are grouped into devices during migration. Older unrelated jobs with the same description remain separate, avoiding unproven merges.
- The performance measurements below are from the earlier release; they are not new measurements of photo rendering or folder migration.

- Outbound-only WhatsApp/SMTP: accepted is not delivered. There is no fabricated status polling, inbound auto-approval or public callback listener. PDF statement attachment sending currently uses email.
- Common jobs/customer screens are paginated and searchable. Supporting history tables show recent records; date-range reports provide broader historical exports. Large historical PDF tables can span many pages.
- The app records payments and tax line descriptions; it does not initiate transfers, file taxes, or certify statutory invoice compliance.
- Physical transport receipt, centre decisions, customer authority and replacement evidence are recorded by staff; the app cannot observe outside events automatically.
- Schema upgrades and interrupted restoration are locally tested. A clean Windows VM deployment, live providers and physical power-loss/full-disk conditions need independent environment validation.
- Archive viewing supports the current schema without changing it. For an older schema, restore into a separate working data directory to migrate a copy; the original archive remains unchanged.
- No guaranteed concurrent LAN access is provided. Keep the live SQLite database on a local disk; a future multi-computer version needs a service/database boundary.


## Final 1.1 package check

The 71,722,120-byte ZIP contains exactly `RepairShopManager.exe`. Its extracted executable launched and restarted successfully (exit 0/0; 3.961/3.469 seconds) with only Windows System32 on PATH and Python/Qt development-path variables removed. Qt multimedia DLLs and Windows/FFmpeg media plugins are included. The existing schema-4 demo was upgraded through the packaged app after creation of a separately validated full pre-upgrade archive; all 24 jobs retained device links. See `package-verification.json`.
