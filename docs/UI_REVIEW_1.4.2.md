# UI review and implementation — 1.4.2

## Architecture and audit

The existing app is a native Python/PyQt6 Windows application. MainWindow owns 17 navigation pages. Shared Form and Grid widgets serve registration, intake, quotations, accounts, settings, inventory and repair actions. CustomerOverview and JobWorkspace contain device, photo, history, custody, parts, warranty and costing tabs. Signals invoke the existing service/lifecycle APIs backed by SQLite/SQLAlchemy; documents, photos, backups and notifications retain their existing modules.

The reported dashboard failure was a sizing defect: a QPushButton with child labels used the shared 22px minimum height after stylesheet polish. Its child layout did not determine the button's size hint. Other findings: branding scrolled out of view; undifferentiated navigation links; empty tables without guidance; long action rows and explanatory labels widening pages; ungrouped intake fields; inaccessible labels; technical backup timestamps; generic background completion messages.

## Implemented design and components

- `ui_widgets.py`: centralized Segoe UI typography, navy navigation, teal primary actions, blue information, amber waiting states and red overdue/destructive states. White cards, consistent borders, spacing, hover/focus feedback and readable secondary text. Added MetricCard, responsive CardGrid and wrapping FlowLayout components. Grid has an empty-state overlay that cannot be selected as a record. Form wraps long rows, constrains its initial size to the available screen, associates labels with fields, groups sections and guards duplicate submissions.
- `ui.py`: grouped navigation with fixed branding/user area; purpose-specific page subtitles; work queue cards and separate location/history filters; leading intake action; wrapped report filters, legacy repair actions and long page notes; scrollable page content; contextual progress/completion feedback and formatted backup dates.
- `customer_ui.py`: wrapping customer and photo actions, wrapped customer contact text, and photo/device controls positioned relative to their associated fields rather than hard-coded row numbers.
- `lifecycle_ui.py`: scrollable repair workspace, wrapping actions and footer, and simplified next-action display.
- `inventory_ui.py`, `parts_ui.py`, `visit_intake.py`: wrapping action controls, primary-action emphasis and compact visit basket with explanatory empty state.
- `tests/test_ui_layout.py`: regression coverage for styled card geometry, keyboard activation, action wrapping and non-selectable empty states.
- `scripts/review_ui.py`: reproducible screen renders from a temporary synthetic database; registers installed Windows fonts for offscreen rendering. Never reads the real shop database.
- Version metadata, README, release notes and offline installer input updated to 1.4.2. The builder fails if its explicit build payload is absent instead of falling back to an older installed EXE.

## Validation

172 automated tests passed, including repair lifecycle, customer registration, photo persistence, multi-product intake, category/service association, inventory/custody, costing, quotations, accounts, documents, messaging and backup behavior. The focused UI suite also passed at 150% scaling (11 tests).

Rendered all 17 navigation pages at 1366 and 1024 logical pixel widths, empty dashboard at 1920/1366/1024 widths, eight repair workspace tabs, eight customer tabs and the intake form at its top and bottom. Reviewed screen overview sheets and full-size dashboard images. The final renderer reported no page-level horizontal overflow at 1024. Wide record tables deliberately retain column scrolling. The normal layout tests exercise native Windows Qt; the screenshot audit uses Qt's offscreen renderer.

No schema, accounting calculations, permissions, customer records or workflow rules were changed. Existing backend validations remain authoritative. No new UI dependencies were introduced.

The 1.4.2 setup's embedded application resource was extracted and its SHA256 matched the new PyInstaller build. That embedded executable launched and restarted successfully (exit codes 0/0) with PATH limited to Windows System32 and Python/Qt development environment variables removed, using an isolated synthetic shop. This verifies the actual distributed payload on this host; it does not substitute for testing a clean second PC. Setup SHA256: `06804eeb302706903e4419c621096b26f61f3f10794e630a03352fc6f1afd641`.

## Limits and future improvements

Primary light theme remains the supported theme; dark mode was deferred to avoid inconsistent photo/document/native-dialog colors. Long tables still use existing paging and horizontal scrolling; a future column chooser would help dense repair history. Forms share the improved layout and error panel; field-specific error mapping remains a future service/UI integration. Real webcam hardware and a clean second Windows PC were not exercised by the automated layout review. Independent computer installation remains a final real-device acceptance check.
