# Intake and customer registration update

The existing PyQt6 application, SQLite schema 9, service layer, customer photo storage, per-device jobs and atomic multi-product visits remain in use.

Customer registration is a dedicated dialog using existing customer and attachment services. The intake wizard arranges the existing fields into four pages and retains durable drafts and the visit basket. It performs step validation before the final existing intake service call. Shop product selection uses customer-owned sales and devices; warranty date status is derived from those records. External warranty details are preliminary customer-reported information stored in the existing job lifecycle JSON and audit, distinct from verified warranty coverage. No database migration is required.

Required validation: existing customer/shop sale/active warranty, inline new customer/external warranty/new category/accessory, back navigation, draft resume, multiple products, source switching, duplicate customer choice, photo capture/upload persistence and negative charges. Release requires independent review, regression tests and a frozen offline build.
# Repair journey presentation

JobWorkspace continues to obtain one authoritative Lifecycle.snapshot per refresh. A pure read-only journey projection combines that snapshot's tracker, stage and timeline into display nodes; it stores no workflow state. RepairJourney renders connected vertical cards with read-only history dialogs and emits the snapshot's primary action to the existing JobWorkspace.act handler. RepairDetails groups the existing workspace values. A responsive splitter places journey beside tabs on wide windows and above tabs on smaller windows. No service/state-machine or database migration is planned.

# Contacts & Services (schema 15)

Configure once, select many times. Reusable business contacts — third-party repairers
(`vendor`), authorized service centres (`centre`), suppliers and bus / transport services
(`transporter`) — remain rows of the existing `masters` table. `contacts.py` is their domain
service: per-kind profile fields, `snapshot()` for history, ranked `options()` for a repair,
`duplicates()` and `quick_create()`. `contacts_ui.py` provides `ContactSelector` (a
`MasterSelector`, so existing forms read it unchanged), the quick-create dialog and the
Contacts & Services screen, which replaces Directories in navigation.

During a repair only job-specific data is typed: the partner's ticket / RMA, expected
return and instructions go on the immutable assignment; journey details go on the
dispatch. Partner and bus-service contact details come from the selected master and are
frozen into `contact_snapshot` / `transporter_snapshot`. Selecting a partner is an
assignment only; custody still changes solely through recorded movements.

`Dispatches.attempts(job_id)` projects assignments + dispatches + receive events into
"attempt 1 / attempt 2" rows. A first-class `external_repair_attempts` table is the next
step if per-attempt diagnosis, estimate and result need to be edited independently; the
`assignment_id` now carried by every dispatch is the join it will need.

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
