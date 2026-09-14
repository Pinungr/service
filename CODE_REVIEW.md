# Code review

## 2026-09-13: 1.4.4 dropdown arrow repair

Independent review scope: `repairshop/assets/chevron-down.svg`,
`repairshop/assets/chevron-up.svg`, combo/date/spin control styling and asset path
substitution in `repairshop/ui_widgets.py`, asset inclusion in
`RepairShopManager.spec` and `pyproject.toml`, and the 1.4.4 version identifiers.
Earlier dashboard, workflow, and installer changes are outside this review.

Findings: no concrete blocker, high, medium, or low defect identified in this
scope.

- The controls reserve space for explicit arrows and give the dropdown button
  its own visible background and border. Existing native control interactions
  and service calls are not replaced.
- SVG paths resolve beside the Python package rather than against the working
  directory. Forward slashes and quoted QSS URLs support the Windows project
  path, which contains spaces.
- Independently executed PyInstaller asset collection returns both SVG files
  under `repairshop/assets`. Setuptools also declares those files as package
  data. Both placeholders are replaced in the production stylesheet.
- Independently checked that the package and project versions equal 1.4.4; the
  setup builder also defaults to 1.4.4.

Release handoff: static review passes for the scoped fix. The orchestrator must
complete its rendered arrow/pixel and interaction regression tests, including
scaled rendering, and verify arrows in the frozen application. Asset collection
alone does not establish that the packaged Qt SVG plugin renders successfully.

### Follow-up: explicit smoke-test diagnostic

Independently reviewed `repairshop/smoke_controls.py` and its call under the
existing `args.smoke_test` branch in `repairshop/__main__.py`. No additional
findings. The diagnostic checks both bundled SVGs for successful Qt decoding,
renders normal/editable/disabled combos plus calendar and quantity controls,
checks that the screenshot saves, and closes its temporary window. The main
window remains open until the existing timed smoke-test exit. Ordinary startup
does not invoke this helper.

The orchestrator reports 177 passing tests and five passing dropdown pixel and
interaction tests at 150% scaling. These results were reported, not independently
rerun by this reviewer. Exact frozen application capture and visual inspection
remain the final packaging check.

## 2026-09-13: Customer registration and intake wizard

Independent review covers the new registration/wizard modules and their UI,
visit, warranty, query, and service integration. Regression tests and source were
reviewed; the reviewer additionally ran an isolated synthetic Qt reproduction.

### Finding: editing a visit product loses its original repair link

- Severity: HIGH; resolved and independently regression-verified.
- File: `repairshop/visit_intake.py`, `edit_selected` (lines 95-105), interacting
  with `repairshop/intake_wizard.py`, `customer_changed` (lines 305-310).
- Problem: edit restores `support.parent` before `support.restore` changes the
  selected customer. The wizard's new customer-change handler clears that parent
  even when this is a programmatic restoration for the same customer. The later
  wizard restore restores the sale but not the parent.
- Impact: a linked return copied into the visit basket silently becomes an
  unlinked repair after editing. Independent synthetic reproduction showed
  `parent_id=1` in the basket and `support.parent=None` after `edit_selected`.
- Recommended fix: guard reactive wizard customer/source handlers for the
  complete restoration operation, and explicitly restore the parent after any
  signals. Add a linked-return basket edit/save regression asserting persisted
  `jobs.parent_id` and device identity.

No further concrete findings identified in the reviewed registration, warranty
snapshot, currency handling, and photo persistence changes at this point.

Resolution verification: `IntakePhotos.restore` now guards wizard reactive
handlers throughout restoration and loads owner/device defaults before restoring
edited category and remaining draft fields. Independently ran
`test_linked_return_basket_edit_preserves_original_job`, which checks the saved
database parent and physical device, and
`test_new_customer_external_inline_category_accessory_complete_flow`, which
registers a customer/photo inline and saves the new category, accessory and
external warranty. Both passed. Reviewed the additional intake photo upload;
it uses bounded image reading and the existing validated photo service.

Current disposition: no open findings in the reviewed change. Full-suite and
release-build gates remain the orchestrator's responsibility.

### Final presentation delta

Reviewed `MasterNameField` in `repairshop/intake_fields.py`, the local checkbox
style and `checkmark.svg`, and the explicit demo smoke renderer. No additional
findings. Brand/model choices still expose text values to existing form/draft
and device persistence and allow legacy/free-text names. Independently ran
`test_brand_master_names_and_free_text_preserve_device_identity`: passed. The
checkbox asset is covered by existing SVG package inclusion. The smoke renderer
temporarily intercepts form submission in a `try/finally` block and runs only
under both demo and smoke flags; regular intake submission is unchanged.

The orchestrator reports 209 passing full-suite tests and 20 focused passing
tests at 150% scaling. Those broader runs were not independently repeated by this
reviewer. Packaged rendering/build validation remains pending with the release
owner.

## 2026-09-14: 1.6.0 repair journey presentation

Scope: `repairshop/journey_model.py`, `repairshop/repair_journey.py`,
`repairshop/repair_details.py`, the `JobWorkspace` wiring in
`repairshop/lifecycle_ui.py`, `STATUS_STATES` and `button()` in
`repairshop/ui_widgets.py`, and the matching tests.

### Finding: the utilities disclosure lost its ampersand

- Severity: LOW; resolved.
- File: `repairshop/lifecycle_ui.py`, utility toggle caption.
- Problem: Qt reads a lone `&` as a mnemonic, so "Utilities & administrative
  actions" rendered as "Utilities _administrative actions". Found by inspecting
  the rendered screen, not by reading the source.
- Fix: escape as `&&`, and strip mnemonics correctly in `button()` so the tooltip
  and accessible name show one real ampersand.

### Finding: the warranty route showed a stored code

- Severity: LOW; resolved.
- File: `repairshop/repair_details.py`, Responsibility group.
- Problem: `warranty_status` was printed raw, so the screen read
  `out_of_warranty` where every warranty dialog says "Out of warranty".
- Fix: map through `WARRANTY_WORDS`, falling back to the stored value so legacy
  free text is shown rather than hidden. Nothing stored changes.

### Finding: the wrapped rail collapsed inside the scroll area

- Severity: MEDIUM; resolved.
- File: `repairshop/repair_journey.py`.
- Problem: `FlowLayout` wraps correctly but hints one row of height, so a
  resizable scroll area allocated one row and laid the remaining rows below the
  clip, where they were invisible. Caught by rendering the screen; the widget
  tree alone looked correct.
- Fix: `Rail` answers `heightForWidth` for the layout above it, and the strip was
  moved outside the scroll area so scrolling to the current stage cannot hide it.

### Checked and accepted

- No duplicate lifecycle state. `build_journey` reads one snapshot;
  `route_options` reads `Lifecycle`'s own `route_label` rather than re-deciding
  whether a route is open, and returns route names only — never a stage.
- The primary button keeps emitting `snapshot['primary']` to the existing
  `JobWorkspace.act` handler in both orientations. Stage clicks are read-only:
  a regression test asserts a click dispatches no transition.
- Status colour, icon and wording have one definition in `ui_widgets`.
  `JOURNEY_STATES` remains an alias, so existing imports are unaffected.
- Action re-tiering only changes which row a button is added to. Every action in
  `snapshot['actions']` still gets a button, and authorization is untouched.
- No schema, migration, service or transition change in this scope.

Release handoff: static review and the rendered screens pass. The Windows build,
frozen-application capture and installer verification for 1.6.0 remain with the
release owner and have not been performed.
