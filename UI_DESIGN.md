# Customer registration and intake — 1.5.0

Registration groups customer/contact/photo/address fields with labelled required inputs and per-field errors. Phone duplicates prompt an explicit choice. Intake uses four scrollable pages with a persistent stepper, Back/Next, Save as Draft and a final Create Repair Job action. Source radios reveal customer sales or external warranty details. Advanced authorization and finance fields remain behind disclosures. Only selected accessories reveal quantity and serial controls; check indicators use a bundled local SVG. Existing brand/model master names remain searchable and accept known legacy names. The confirmation includes each product in the visit basket.

Source screenshots: `runtime/intake-preview-150-verified`. Preview uses synthetic records and production Fusion styling. Review normal and 150% scaling, checking arrows, checkboxes, currency values, page scrolling and persistent footer controls.

# Shared control design — 1.4.4

Fix the missing arrow affordance without changing selection behavior. Combo and calendar fields reserve 38 pixels at the right edge for a 32-pixel dropdown button. A pale background and divider distinguish the button from the value field. A dark 16-pixel vector chevron remains legible at Windows display scaling. Hover feedback uses the existing blue palette; disabled fields retain their arrow but remain non-interactive with muted values.

Editable combo line edits use the outer control border rather than drawing a second frame. Quantity controls share the same chevron family. Two local SVG assets are centrally referenced by the existing stylesheet and explicitly included in both setuptools and PyInstaller packages. No external icon service or new dependency is used.
# Repair journey redesign

Place compact repair identity and operational context above a two-pane workspace. The connected vertical Repair Journey has a clear route label, status legend and emphasized current node containing its required action and blockers. Completed stages open evidence-only dialogs; upcoming nodes remain secondary, with no actions. Scroll to the current node on stage changes while preserving user history browsing on ordinary refresh. On narrow windows stack journey above the original tabs. Group workspace detail into Responsibility, Diagnosis, Repair, Dates, Financial and Quality/Closure. Keep secondary actions distinct from an expandable utilities area. Centralize lifecycle palette, icons and labels in the reusable journey component. This specification implements the user's requested presentation-only scope.

# Repair journey presentation — 1.6.0

The journey changes shape with the space it is given. Beside the tabs on a wide
window it stays a connected column of full stage cards. Stacked above the tabs on
a narrow window it becomes a pinned chip rail: every stage on two or three
wrapped rows with the current stage expanded beneath it. The rail sits outside
the scroll area, so scrolling to the current stage never hides the overview.

At the decision point the current node names the routes still open, read from the
backend's own route list. These are choices, not promises: no route-specific
stage is drawn until the shop has selected one, and the footer says so.

Every node is clickable and opens its recorded history only; hovering shows the
stage, its state, when and by whom it was recorded, and for the current stage the
location, responsible party and route. Completed cards carry their timestamp and
the staff member beside it.

Status colour, icon and wording come from one `STATUS_STATES` table in the shared
design system, so the legend, the nodes and any future lifecycle surface cannot
drift apart. Meaning never rests on colour alone.

Workspace actions sit in three tiers: the primary action inside the current stage
card, stage-relevant actions under "Other actions for this stage", general tools
(parts, manual warranty, internal costing, vendor payment) under "Tools", and
historical or exceptional actions behind the "Utilities & administrative actions"
disclosure. A tier with nothing in it hides its caption.

Responsibility now carries current custodian and physical location beside the
assigned technician and repairer, and the warranty route reads in the same words
as the warranty dialogs rather than the stored code.

Source screenshots: `runtime/journey-preview`, rendered by
`scripts/preview_journey.py` through real `Lifecycle.execute()` transitions.
