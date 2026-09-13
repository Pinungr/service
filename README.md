# RepairShop Manager

Native Windows desktop software for an offline computer/electronics repair counter. Built with Python 3.14.6, PyQt6, SQLite through SQLAlchemy, explicit versioned schema migrations, ReportLab, openpyxl, HTTPX and Windows keyring integration.

## Run the Windows package

Extract `RepairShopManager-Windows-x64.zip`, then double-click its only file, `RepairShopManager.exe`. The executable embeds its application and runtime dependencies; no separate `_internal` folder or installed Python is needed. Source files, guides, build scripts and dependency lists stay in the developer workspace and are not included in the end-user ZIP. The package is portable: no administrator rights or Windows service installation is required. The executable temporarily unpacks its runtime when launched; shop data continues to live outside the executable.

For pen-drive installation on another Windows PC, copy `dist\installer\RepairShopManager-Offline-Setup-1.4.1.exe`. The setup runs completely offline, installs per user, creates Desktop and Start Menu shortcuts, and registers an uninstaller while preserving shop data separately.

On first launch, enter your shop name and create an owner username and password (at least 10 characters). There is no production default password. Production data is kept at `%LOCALAPPDATA%\RepairShopManager`, outside the program folder. Do not place a live SQLite database on a network drive.

## Development setup

Version 1.4.0 adds shop inventory, reserved/issued stock, separate internal costing, courier and technician handovers, structured repair returns and manual warranty verification. See [the implementation report](docs/INVENTORY_CUSTODY_IMPLEMENTATION_REPORT.md) for schema changes, validation and limits, and [the user guide](docs/USER_GUIDE.md) for the operating steps.

To build without replacing an application currently running from `dist`, use `scripts/build.ps1 -OutputDirectory 'dist/releases/1.4.0'`. The portable ZIP still contains exactly one EXE.

From this project folder in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m repairshop
```

Use a separate data directory when testing:

```powershell
.\.venv\Scripts\python.exe -m repairshop --data-dir '.\runtime\test-shop'
```

## Synthetic demonstration

```powershell
.\.venv\Scripts\python.exe scripts\demo.py --data-dir demo-data
.\.venv\Scripts\python.exe -m repairshop --demo --data-dir demo-data
```

The generator refuses to overwrite an existing database. The demo contains only synthetic records and uses local message capture. Demo-only logins: `demo` / `DemoShop2026!`, `counter` / `DemoCounter2026!`, `technician` / `DemoTechnician2026!`. The production first-run flow never creates these accounts. The developer preview script also uses only this separate synthetic database.

## Tests and scale measurements

```powershell
New-Item -ItemType Directory -Path runtime -Force
.\.venv\Scripts\python.exe -m pytest -q --basetemp=runtime/test-temp
.\.venv\Scripts\python.exe scripts\benchmark.py --generate
```

The benchmark generator creates 60,000 customers, 100,000 jobs, 200,000 items, 200,000 custody events, 100,000 quotations and 200,000 financial entries in a separate `benchmark-data` directory. It refuses to overwrite existing data. Omit `--generate` to measure the existing dataset. Results are saved in `docs/benchmark-results.json`.

## Build a Windows distribution

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

The reproducible dependency pins are in `requirements-lock.txt`; the PyInstaller build input is `RepairShopManager.spec`. The build creates `dist\RepairShopManager.exe` and a portable ZIP containing exactly that executable. Run `scripts/verify_package.py` to validate its contents and test launch/restart with developer Python paths removed. No websites, cloud infrastructure, bank transfers, or system scheduled tasks are created.

To create the offline setup installer, run `powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1` after the application EXE is built.

## Customer photos and repair overview

Version 1.1 adds required customer webcam photos for new intake, resumable drafts, stable physical device IDs, product photos, permanent customer folders and a consolidated repair overview. Existing records remain accessible without a camera. See `docs/PHOTOS_AND_CUSTOMER_OVERVIEW.md` for usage, storage, migration and recovery details.

## Operator documentation

- `docs/USER_GUIDE.md`: owner/staff workflows.
- `docs/ARCHITECTURE.md`: storage, state rules, accounting and recovery design.
- `docs/MESSAGING.md`: actual provider setup, credentials and outbound-only limits.
- `docs/TRACEABILITY.md`: requirements and acceptance coverage.
- `docs/RELEASE_NOTES.md`: verification results and known limits.

Runtime files, customer databases, managed attachments, backups, generated builds, logs and secrets are excluded from source control. Backups contain private shop data and should be stored in an owner-controlled location. Credentials are not included in archives and must be re-entered on another computer.

## Repair lifecycle, cards, parts and warranties

Version 1.2 integrates the supplied three-route lifecycle, stable Master Job with sequential Job Cards, structured parts and spare stock, approved part revisions, installed-part warranties and linked future warranty claims. See `docs/LIFECYCLE_IMPLEMENTATION_REPORT.md` for architecture, migrations, operator flow, validation and limits. Run `.venv/Scripts/python.exe scripts/lifecycle_demo.py --preview` for the isolated eleven-scenario demo.
