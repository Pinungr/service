# Architecture decisions for web edition 2.0

## One local process and database

The Windows executable runs one FastAPI/Uvicorn process on `127.0.0.1` and
serves React from the same origin. A per-data-directory operating-system lock
prevents a second writer. This keeps the existing SQLite shop, migrations,
sessions and scheduler in one process. Multi-worker deployment is outside the
current architecture.

## Reuse the Python business rules

HTTP routers adapt requests to the existing service, lifecycle, billing,
custody and persistence modules. React presents server-supplied state and
actions; it does not implement another repair state machine or calculate
authoritative balances. The old PyQt screens live in `legacy_desktop/` for
parity review, and the production backend does not import them.

## Embed the interface in the Windows executable

The build compiles React first, then PyInstaller embeds its static files with
the Python backend. The optional Inno Setup installer contains that one
executable. Runtime data stays in `%LOCALAPPDATA%\RepairShopManager`; the
package carries no shop database, credentials or customer attachments.

## Preserve migration and rollback safety

This conversion adds no database migration. Existing numbered migrations and
pre-migration backup rules remain authoritative. An ordinary update installs
over the current application. Uninstall is a separate, explicit full-data
reset under the existing installer policy.
