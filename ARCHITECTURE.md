# Intake and customer registration update

The existing PyQt6 application, SQLite schema 9, service layer, customer photo storage, per-device jobs and atomic multi-product visits remain in use.

Customer registration is a dedicated dialog using existing customer and attachment services. The intake wizard arranges the existing fields into four pages and retains durable drafts and the visit basket. It performs step validation before the final existing intake service call. Shop product selection uses customer-owned sales and devices; warranty date status is derived from those records. External warranty details are preliminary customer-reported information stored in the existing job lifecycle JSON and audit, distinct from verified warranty coverage. No database migration is required.

Required validation: existing customer/shop sale/active warranty, inline new customer/external warranty/new category/accessory, back navigation, draft resume, multiple products, source switching, duplicate customer choice, photo capture/upload persistence and negative charges. Release requires independent review, regression tests and a frozen offline build.
# Repair journey presentation

JobWorkspace continues to obtain one authoritative Lifecycle.snapshot per refresh. A pure read-only journey projection combines that snapshot's tracker, stage and timeline into display nodes; it stores no workflow state. RepairJourney renders connected vertical cards with read-only history dialogs and emits the snapshot's primary action to the existing JobWorkspace.act handler. RepairDetails groups the existing workspace values. A responsive splitter places journey beside tabs on wide windows and above tabs on smaller windows. No service/state-machine or database migration is planned.

# Repair journey presentation — 1.6.0 delta

No service, state-machine, schema or authorization change. `RepairJourney` gains
an orientation: `JobWorkspace.resizeEvent` already re-orients its splitter, and
now tells the journey to switch between the stacked column and the pinned rail at
the same threshold. `Rail` is a thin wrapper that answers `heightForWidth` for
the existing `FlowLayout`, which a resizable scroll area needs before it will
allocate room for wrapped rows.

`journey_model.route_options` reads `Lifecycle`'s own `route_label` to decide
whether the route is still open and, if so, returns `ROUTE_LABELS`. It adds no
stage and reaches no decision of its own. Status semantics moved from
`repair_journey` into `ui_widgets.STATUS_STATES`; `JOURNEY_STATES` remains as an
alias so existing imports keep working.
