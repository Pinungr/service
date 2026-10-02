# RepairShop Manager

Offline repair-shop software for Windows. The current application opens in a
browser while one local FastAPI process serves the React interface, API and
existing SQLite shop data. It needs no cloud account or network connection.

## Run from source without making a Windows build

From the project folder in PowerShell, with Python 3.14 and Node.js installed:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m repairshop --data-dir '.\runtime\test-shop'
```

Open the local address printed by the launcher if your browser does not open.
Use a separate `--data-dir` for testing so the installed shop is untouched.
The first visit asks for the shop name and owner account. A second launch for
the same data folder opens the running instance instead of starting another
SQLite writer. The app binds to `127.0.0.1` only.

For frontend development, run the backend above and, in another terminal,
`npm.cmd --prefix frontend run dev`. Vite
proxies `/api` to the backend; production needs no Vite process. A synthetic
demo can be generated once with `scripts/demo.py --data-dir demo-data`, then
opened using `python -m repairshop --demo --data-dir demo-data`.

## Test

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q --basetemp runtime\test-temp
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m repairshop --smoke-test --data-dir '.\runtime\web-smoke'
```

The Python suite includes domain, API, architecture-boundary and transitional
desktop regression tests. `requirements-lock.txt` includes PyQt for those
legacy tests; a production backend installed from `pyproject.toml` does not
require PyQt. The smoke command checks the API and the built React assets.

## Windows package

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
.\.venv\Scripts\python.exe scripts\verify_package.py
```

The build creates a one-file `dist\RepairShopManager.exe` and a portable ZIP.
`verify_package.py` extracts the ZIP and launches it twice against a separate
synthetic shop with development Python paths removed. The optional offline
installer uses the verified EXE and `scripts\build_installer.ps1`; it requires
the local Inno Setup compiler described in [installer instructions](docs/INSTALLER.md).
Installing an update over an existing copy preserves shop data. The existing
uninstaller is a permanent reset after confirmation, so do not uninstall to
apply an update.

## Architecture and operating guides

- [Architecture](ARCHITECTURE.md): process, module, database and security boundaries.
- [User guide](docs/USER_GUIDE.md): intake, lifecycle, custody, accounts and backups.
- [Database](DATABASE.md): existing SQLite schema and migration history.
- [Test plan](TEST_PLAN.md): regression and release checks.
- [Release status](RELEASE.md): verified artifacts and remaining acceptance.

Production data lives in `%LOCALAPPDATA%\RepairShopManager`, outside the
executable and project folder. Backups contain private customer and financial
records; store exported copies in an owner-controlled location.
