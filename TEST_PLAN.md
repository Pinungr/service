# Targeted regression plan

## Intake and registration — 1.5.0

`test_customer_registration.py`: required fields, phone duplicates with both choices, image upload/capture/staging/cancel/retry and existing-customer edits.

`test_intake_wizard.py`: four-step navigation; shop history/autofill/active warranty and deposit persisted; complete inline registration/external warranty/new category/accessory scenario; draft resume and negative amounts; source switching; alternate-number search; linked-return basket edit preserving parent and physical device; existing brand master and manual model names. Existing UI and visit tests cover the real submission callback, unchecked accessories and multi-device atomic save/recovery.

`test_intake_warranty.py`: authoritative shop dates, expiry boundaries, manual metadata validation, hidden-field clearing, transactional rollback and compatibility with legacy intake callers. No verified warranty approval is inferred.

Visual capture uses the production widgets and synthetic data in `scripts/preview_intake.py`. The explicit frozen demo smoke mode also captures all wizard pages and registration. Focused UI/registration/dropdown run at 150%: 20 passed. Full regression: 209 passed. Frozen launch/restart: 0/0, including 150% scaling without development paths. Final installer evidence is recorded in RELEASE.md.

## REG-DROPDOWN — 1.4.4

Requirement: all existing dropdowns must display their arrow buttons and continue to open/select values, including editable selectors, disabled fields and calendar dates. Quantity controls should retain visible up/down actions.

`tests/test_dropdown_controls.py` exercises production Fusion/QSS rendering. It checks actual dark glyph pixels inside the arrow hit target, opens both kinds of selector, changes selection through the keyboard, opens the calendar and increments a quantity. It excludes text and borders from the glyph inspection. Run at normal and 150% scaling. Results: five cases passed at both scales; combined UI suite 22 passed; full regression suite 177 passed.

Packaging verification: build the actual application and run its existing `--demo --smoke-test --data-dir <isolated test shop>` mode with development Python/Qt paths removed. Inspect `ui-controls-smoke.png` from that executable, confirm both SVG resources and Qt SVG runtime ship in its archive, and check successful launch/restart. No installed customer database is used for validation.

## Repair journey presentation — 1.6.0

`tests/test_repair_journey.py` drives real `Lifecycle.execute()` transitions and
projects the resulting snapshot, so a node can only be wrong if the backend is.
The full in-house sweep walks received, initial inspection, warranty check,
waiting for route selection, route selected with technician assignment,
diagnosis, parts required, estimate, customer approval, approved, repair in
progress, technician test, QC, billing, ready for collection, delivered and
closed, asserting exactly one current node at every step and a tick mark only
over recorded evidence. Parametrised cases cover the service-centre and
third-party routes, in-transit and external waiting, an accepted warranty claim
skipping estimate and approval, a not-repairable outcome, a hold, and a legacy
job.

New for 1.6.0: route options appear only while the route is open and name the
backend's own routes; rail mode lists every stage as a chip, sizes the strip to
its wrapped rows, keeps the primary action inside the expanded current card and
restores the column on switching back; a stage click opens history and dispatches
no transition; the workspace keeps general tools apart from stage actions, hides
an empty caption and renders a literal ampersand in the utilities disclosure.
`tests/test_repair_details.py` covers the warranty wording and the custody rows.

Results: full regression 228 passed; journey, details, dropdown, UI and layout
suites 35 passed at 150% display scaling. Visual verification used
`scripts/preview_journey.py` against a throwaway database: eight screens in
`runtime/journey-preview` covering received, the route decision, awaiting
approval, repair in progress, not repairable, warranty covered and two narrow
windows, each inspected. Windows packaging and installer verification for 1.6.0
have not been run and remain open.
