# RepairShop Manager 1.5.0

Customer registration now groups required name, phone and address with optional alternate/email and camera/upload photo preview. Phone matches require an explicit existing/new customer choice. New intake uses four steps, inline registration, shop sales autofill, recorded-date warranty status, optional external warranty details, searchable category/brand/model/service masters, category-specific accessories, quick due dates, optional charges and a final summary. Multiple devices and durable drafts remain supported.

External warranty is a customer report, not verified coverage or permission to start repair. The existing Warranty tab shows the recorded intake snapshot separately. No schema migration or reset; existing service, financial, photo and repair approval checks remain in force. Install over the current application to preserve records. See `INTAKE_UX.md` for scope and validation.

# RepairShop Manager 1.4.4

Fixed invisible dropdown arrows throughout the shared theme. Ordinary, editable and disabled selectors now show a separate arrow button; date pickers and quantity controls also have explicit chevrons. Icons ship inside the offline executable and resolve beside the package, including when the installation path contains spaces.

No database or business-rule changes. Validation: 177 tests passed, including rendered-glyph and click/keyboard regression tests; all five control checks also passed at 150% scaling. Independent code/security review found no issues in this fix. The existing explicit `--smoke-test` mode now also renders a synthetic control sheet to its selected test folder to verify icons inside the frozen application.

Install 1.4.4 over the existing application to preserve shop records. Uninstall behavior is unchanged from 1.4.3.

# RepairShop Manager 1.4.3

Replaced the custom bootstrapper with a standard offline Inno Setup wizard, including Welcome, README, destination folder, Start Menu selection, Desktop shortcut, progress and Finish with optional launch. Windows Apps/Control Panel now uses the native logged uninstaller instead of a PowerShell script.

Confirmed uninstall removes all default local shop data, photos, accounts, settings, internal backups and messaging credentials, along with the program, shortcuts and uninstall registration. In-place updates preserve records. Exported copies outside the app data folder are not erased. Silent removal requires `/REMOVEALLDATA=1`; without it uninstall is refused. Running app processes or linked data directories block unsafe removal.

Verified the installed payload matches the build; silent uninstall without acknowledgment preserves files; complete uninstall removes app/data/shortcuts/registration; custom-folder reinstall opens the blank first-run shop setup; in-place update preserves a temporary account; final uninstall deletes that account and both dummy messaging credentials. Real wizard Welcome, README and destination pages and the reinstalled first-run window were inspected. Application business logic is unchanged from the 172-test UI release. See `INSTALLER.md` for build and cleanup scope.

# RepairShop Manager 1.4.2

Fixed collapsed dashboard cards caused by shared button styling overriding their minimum height. Cards now size to their contents, reflow with the window and support keyboard activation. The dashboard separates the work queue from location/history filters and explains an empty attention list.

Navigation keeps the brand and user details visible while grouped links scroll. Shared action rows wrap across repair, inventory, parts, warranty and customer screens. Tables explain empty results without inserting selectable placeholder records. Forms wrap long rows, preserve visible save/cancel controls, group intake fields, associate labels with inputs and prevent duplicate save clicks. Background work has a progress indicator and contextual completion feedback.

No database or business-rule changes. Validation: 172 automated tests passed; 11 UI tests also passed at 150% scaling. Rendered all 17 navigation pages at normal and small widths, all repair workspace tabs, customer tabs and both ends of the intake form. No page-level horizontal overflow remained at 1024 logical pixels. Large tables retain horizontal scrolling for their columns.

Offline setup: `dist/RepairShopManager-Offline-Setup-1.4.2.exe`. See `UI_REVIEW_1.4.2.md` for the audit, changed components and remaining improvements.

# RepairShop Manager 1.4.1

The desktop UI has been refreshed without changing the working repair, inventory, account, photo or document logic. The shared design system now has a modern enterprise palette, clearer typography, stronger focus states, consistent buttons, danger styling, reusable panels, badges, card metrics and improved table readability.

The main shell, dashboard, repair lists, intake landing page, inventory page and repair workspace now have clearer hierarchy and spacing. Dense parts, cards and warranty tabs are grouped into action panels so staff can scan current state, responsibility and the next action faster. Dialogs now use more comfortable spacing and inline error presentation.

An offline setup EXE is available for pen-drive installation on another Windows PC. It installs per user to LocalAppData Programs, creates Desktop and Start Menu shortcuts, registers an uninstaller, and does not require internet or admin rights. Shop data remains in LocalAppData RepairShopManager and is not removed by the uninstaller.

No schema migration is required. Validation: 166 automated tests passed in 53.76 seconds. A seeded synthetic demo launch smoke test exited successfully.

# RepairShop Manager 1.4.0

Shop inventory now tracks available, reserved, physically issued and installed parts, including serials, supplier evidence, defaults and immutable movements. Parts search inventory first; repairing-third-party supply is locked to the assigned vendor. Internal costs are separated from customer prices, with owner-only costing and quotation revision previews.

Courier dispatch/arrival/return and in-house assignment/handover/return now distinguish physical custody from work responsibility. New return cards preserve repair results, parts, warranties, repairer identity and receipt evidence; internal copies are clearly marked. Manual warranty checks support missing historical evidence without inventing records. Active claims control the effective warranty state and lock ordinary edits.

Schema 9 upgrades through the existing verified backup path. Full suite: 166 passed in 60.94 seconds. New UI and printed cards were checked with synthetic data. See `INVENTORY_CUSTODY_IMPLEMENTATION_REPORT.md` for architecture, file changes and limitations; actual extracted-package verification is in `package-verification.json`.

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
