# RepairShop Manager architecture — web edition 2.0

## Runtime

One local FastAPI process serves the React application and `/api/*` on
`127.0.0.1`. It owns one SQLite database, the managed file store, sessions and
an in-process background scheduler. `repairshop.server` obtains an operating
system lock per data directory and starts Uvicorn with one worker. A second
launch opens the existing instance. Do not run multiple workers or point two
independent processes at the same SQLite shop. Horizontal scaling requires a
future database and session architecture change; PostgreSQL is not part of
this release.

```
Browser → React/TypeScript → same-origin /api → FastAPI routes
                                           → Service / Lifecycle / domain
                                           → SQLite + managed files
```

In development, Vite may run on port 5173 and proxy `/api` to the one backend
on port 8765. In production, FastAPI serves the built files from
`repairshop/api/static` in the frozen executable, or `frontend/dist` when
running from source. Neither the browser nor React can open SQLite or learn
local file paths. File access is through authenticated attachment IDs.

## Source boundaries

- `repairshop/api/app.py` composes one FastAPI app. Its `modules/` routers are
  thin HTTP adapters for auth, dashboard/search, customers, intake, repairs,
  contacts, dispatch/custody, inventory/parts/warranty, finance, documents,
  reporting, notifications, backup and settings. They call Python services
  directly; there is no internal HTTP or second backend process.
- `repairshop/services.py`, `lifecycle.py`, `contacts.py`, `dispatch.py`,
  `custody.py`, `billing.py` and the other domain modules remain the source of
  business rules. `readmodels.py` prepares bounded API read responses;
  `action_forms.py` describes fields for an allowed lifecycle action. These
  modules do not import FastAPI or PyQt.
- `repairshop/persistence.py` owns SQLite and explicit migrations through
  schema 15. This conversion makes no schema migration and preserves IDs,
  repair numbers, audit, job cards, movements and historical snapshots.
- `repairshop/images.py` uses Pillow and bytes for backend image handling.
  `legacy_desktop/` contains the transitional PyQt presentation and adapters;
  the web backend imports none of it. PyQt is an optional development extra,
  not a production backend requirement.
- `frontend/src/features/` contains React presentation by business area.
  `frontend/src/api/client.ts` is its same-origin HTTP boundary. The backend
  supplies lifecycle state, actions, journey nodes, permissions and validation;
  React renders them and collects input.

## State and safety rules

`Lifecycle.snapshot()` supplies the authoritative current state. The journey
API projects the existing tracker/history through `build_journey()`; it stores
no second state machine. Action endpoints invoke `Lifecycle.execute()` or
the relevant existing service. Lifecycle commands require the last-read job
version, return HTTP 409 for stale state, and use operation IDs so retries do
not apply twice. Intake visits, custody movements, dispatch handovers and
financial entries retain their existing idempotency and audit rules.

Assignment and physical custody are separate. Choosing a repairer records
responsibility; only a custody movement changes where the device is. Contact
and transporter snapshots preserve the details used at the time of a repair,
even after a directory entry changes. Courier remains free text; reusable bus
services remain configured contacts. Money stays integer paise in the backend.

Signed-in sessions are held by the one process and identified by an opaque,
HTTP-only, SameSite cookie. Every protected request reconstructs the user from
the database and checks service permissions; UI visibility is only a
convenience. Unsafe `/api` requests require the application header. API errors
share a stable `{error:{code,message,field}}` shape and unexpected errors go to
the local rotating technical log without a browser stack trace. The local
server binds to loopback only.

The in-process scheduler processes notification claims/reminders, customer
folder projections and due backups while an active user session exists. A
failed optional task is logged and retried later; it cannot roll back a
committed repair transaction. Shutdown cancels the scheduler and disposes the
database engine. Backups and restores remain backend-owned.

## Build and migration status

`scripts/build.ps1` builds React before PyInstaller; the spec embeds the
generated HTML/CSS/JS under `repairshop/api/static`. The frozen smoke check
requires a healthy API, React root and JavaScript asset, then repeats after a
restart using a separate synthetic data directory. Installation over an
existing release keeps the existing `%LOCALAPPDATA%\RepairShopManager`
database and migrations. Do not uninstall as an update: the existing
uninstaller intentionally removes local shop data after confirmation.

`legacy_desktop/` remains available during parity review. Retirement requires
browser acceptance for every operator flow, including camera hardware and an
independent Windows installation test. Database and domain code are shared;
there is no parallel web-only business model.
