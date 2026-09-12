# Architecture and data rules

One installable native application, a local SQLite database and relocatable managed files form a modular monolith. Python 3.14.6 on Windows 11 x64 is the measured baseline. PyQt6 is the only Qt binding. No browser/server/Redis/AI/cloud dependency is used for core work.

| Module | Responsibility |
|---|---|
| `__main__` | Application-data location, first run, login, interactive database lock |
| `domain` | Decimal-to-paise conversion, normalization, stages and validation errors |
| `persistence` | SQLAlchemy connection lifecycle, numbered migrations, transactional boundaries |
| `services` | Permissions and all write-side business commands |
| `queries` | Indexed searches, dashboard aggregates, ledgers and reports |
| `ui`, `ui_widgets` | Native screens, forms, reusable selectors and background tasks |
| `messaging` | Durable outbox, safe claims and official outbound adapters |
| `documents` | Managed evidence, issued PDF snapshots and safe spreadsheet exports |
| `backup` | Consistent archive, verification, read-only view and recoverable restore |

The SQLAlchemy engine creates a fresh thread-owned driver connection per read/transaction using NullPool. Foreign keys are enabled on every connection; WAL, FULL synchronous and a 5-second busy timeout are deliberate durability settings. Business commands use BEGIN IMMEDIATE. SQL and financial/custody decisions stay in services and query modules, outside UI event handlers.

Schema migrations are explicit, numbered and transactional. Version 1 creates the schema; version 2 adds append-only triggers and issued-quote protections; version 3 adds operation deduplication, quote identity snapshots and allocation corrections; version 4 adds staff/vendor recipients and document attachments in the outbox. A populated database is backed up before migration. Unrecognized existing databases and unsupported newer versions are refused; startup never recreates live data.

Customers can have repeat jobs and sales. A job owns a primary device plus received accessories. `items` defines units and provenance; `holdings` projects current quantities; immutable `movements` record each handover. Responsibility is in assignment history, independently of holdings. Partial movements decrement a sufficient source quantity and increment a destination in one transaction.

Operational stage, route, warranty decision, quote approval, finance and outbox state are separate. Repair approval refers to a quote version. Additional repair work checks the latest approval and deposit. Shop-ready rules check physical custody and testing. Exceptions need owner authorization/reasons. Closing a job neither changes account entries nor fabricates customer delivery or payment.

Money is integer paise. Decimal input uses ROUND_HALF_UP. Customer and vendor accounts have independent signed ledgers. Posted entries, allocations, movements, audit and decision records are immutable through app and database triggers. Operation IDs protect duplicate finance/custody submissions. Charge/payment allocations must belong to the same counterparty and stay within both totals. Current account balances are sums; negative balances are retained. Quotation values, customer prices, vendor estimates and actual expenses remain distinct.

Documents are immutable files identified by UUID-based relative `managed/...` paths. An issued file is registered only after successful generation/copy. A failed registration removes only that newly created file. CSV/XLSX text is protected against formula injection. PDFs escape user text before ReportLab markup processing.

Business notifications are inserted in the event transaction. A worker claims one row with a guarded state change, commits, then calls the network outside the write transaction. Restarting after an in-flight submission marks it uncertain. Bounded retries are used only for known safe failures; provider acceptance is not delivery. Secrets go to the OS keyring and are excluded from settings/archive manifests.

Backups use SQLite's online backup API, validate integrity/foreign keys, include every referenced managed file and checksum, write a temporary archive and atomically finalize it. Restore validates before installation, takes a full pre-restore backup, checkpoints WAL, stages the candidate and keeps previous database/attachments together. A durable recovery journal allows an interrupted file swap to roll back on next startup. Restoration pauses old outbox records. Archive viewers use SQLite mode=ro and no workers.

Audit history is append-only through the app, not tamper-proof against an operating-system administrator. Credentials, runtime logs, databases and backups do not belong in Git. PyQt6 and other bundled dependencies retain their own licenses; distribution includes the license notices collected by PyInstaller.


## Schema 5: photos and physical-device projections

`migration5.py` adds `devices`, relative customer/device folder identities, customer current-photo and job intake-photo references, photo metadata/checksums on existing attachments, staff-owned `intake_drafts`, a durable `folder_queue` and generated-file ownership/checksum records. Existing explicit sale/parent links are reused; ambiguous historical descriptions are never merged. Old jobs have nullable photo references; the service requires a valid persisted photo only on new intake. Device identity and photo validation are performed in the same transaction as receipt and advance recording.

`customer_records.py` publishes local images by unique filenames using flushed temporary files and atomic rename. A failed database registration may leave an unreferenced uniquely named file; it never makes intake succeed and never removes historical evidence. Recovery requires the original recorded checksum. `camera.py` uses PyQt6 QtMultimedia with a replaceable backend, bounded startup/capture timeout, hot-plug enumeration and explicit release. Image saving/import and folder generation run off the GUI thread. `customer_ui.py` extends the existing modal intake and history views. Drafts are captured before camera access and resumed with their original operation ID to preserve intake deduplication.

Folder summaries are projections generated under the backup/write guard. A business audit event queues its affected customer; shared master/settings changes queue relevant projection refreshes. Each generated file records its checksum. Conflicting external edits are preserved and reported, while interrupted writes with unchanged content can be resumed. The overview counts unique devices with remaining custody across device and accessory rows, excludes completed historical visits from readiness and keeps financial balances independent.

`backup.snapshot_archive` is shared by startup migration and authenticated backups. It takes a SQLite snapshot and archives existing attachment paths, all customer files, registered summaries and directory metadata, using the snapshot's actual schema version. This permits verified full pre-upgrade archives before authentication/schema changes. Restoration swaps `Customers` alongside `managed` and the database, queues projections and pauses historical outbox work. Recovery journals record which roots originally existed, so interruption does not strand a newly installed customer tree beside the previous database.
