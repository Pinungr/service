# Release 1.5.0 — customer registration and intake wizard

- Scope: four-step intake, grouped registration, camera/upload preview, explicit phone duplicate choices, sales/warranty autofill, searchable existing category/brand/model/service masters, category accessories, optional due dates/charges and final multi-product review.
- Database: schema 9 unchanged. Optional intake warranty snapshot uses existing lifecycle JSON and audit; no verified coverage or financial approval is inferred.
- Validation: full suite **209 passed**; registration/intake/dropdown checks at 150% display scaling **20 passed**. Both requested complete scenarios save successfully. Source form screenshots use isolated synthetic data.
- Independent code/security review: one HIGH linked-return restoration defect found and resolved; reviewer independently verified persisted parent/device links. No open findings in the reviewed scope.
- User data: current installation, accounts and shop records were not reset or changed. In-place installation is the update path; the existing uninstall action deliberately removes local data.
- Limitations: warranty duration derives from recorded dates; absent dates remain Unknown. Brand/model master lists are global. Physical camera tests use synthetic images; a separate clean PC has not been exercised.
- Detailed component and workflow report: `docs/INTAKE_UX.md`.

Final build verified: the frozen executable launches and restarts with exit codes 0/0, including at 150% scaling, with PATH limited to Windows System32 and development Python/Qt variables removed. Its own registration/wizard screenshots were inspected and bundled checkbox SVG verified. Validation used only `runtime/release-150-smoke` synthetic records. The standard offline Inno Setup installer compiled successfully with that payload.

Artifact: `dist/RepairShopManager-Offline-Setup-1.5.0.exe` — 73,556,773 bytes. SHA256: `6c5258d58af0f63c9873b5d97625afaac3f7d7701ff1f0cbeae5d933dca73491`. Only this installer remains in `dist`; the previous installer is archived under ignored `build/prior-releases`. No install/uninstall was performed on the current user profile during this release.

# Release 1.4.4 — visible dropdown arrows

- Requirement: restore visible, working arrow buttons on dropdowns throughout the existing Windows application (REG-DROPDOWN).
- Roles used: App Orchestrator, Frontend Developer, Test Engineer and Build/Release Engineer, with delegated independent Code Reviewer and Security Reviewer.
- Architecture impact: shared Qt stylesheet and local vector assets only; native selection behavior remains in Qt. The existing explicit smoke-test mode gains a synthetic control capture for frozen-build verification.
- Implementation: separate arrow hit area, visible chevrons, reserved text padding, editable-combo border cleanup, calendar/quantity arrows and packaged SVG resources.
- Files: `repairshop/ui_widgets.py`, `repairshop/assets/*.svg`, `RepairShopManager.spec`, `pyproject.toml`, version metadata, installer build version, `repairshop/smoke_controls.py`, `repairshop/__main__.py`, `tests/test_dropdown_controls.py` and related review/release documentation.
- Database changes: none. No customer files, accounts, settings or installation are reset for this update.
- Tests: full suite 177 passed; combined UI suite 22 passed; five rendered pixel/interaction cases passed at 150% scaling. Source-mode diagnostic capture passed.
- Security findings: none in scoped review; local static SVGs introduce no network, credential or user-data dependency. See SECURITY_REVIEW.md.
- Code review findings: none in scoped independent review, including smoke-test diagnostics. See CODE_REVIEW.md.
- Remaining risk: validation runs on this Windows host; a separate clean PC has not been exercised. Existing installer/uninstaller policy is unchanged.
- Deployment: close the application and install the updated setup over the existing installation to preserve shop data. `dist` retains only the latest offline setup EXE. Do not uninstall as part of an ordinary update, because the previously requested uninstaller performs a full data reset.

## Final build evidence

Release ready. The actual PyInstaller EXE contains both SVG assets and the Qt SVG image plugin. It launched and restarted with exit codes 0/0 using an isolated synthetic shop, PATH restricted to Windows System32 and development Python/Qt variables removed. Its own saved `ui-controls-smoke.png` was visually inspected: ordinary, editable and disabled dropdowns, calendar and quantity arrows render correctly.

Artifact: `dist/RepairShopManager-Offline-Setup-1.4.4.exe`, 73,514,135 bytes. SHA256: `b996d0ec679e5a29b994e720bca399ccddb706d1195df4011f40fe0f2f4f21d4`. The existing native offline installer compiled successfully with this verified application payload. The current installed application and customer data were not modified during this release's validation.

# Release 1.6.0 — repair journey presentation (not yet packaged)

- Scope: presentation and interaction on the Repair Lifecycle screen only.
  Orientation-aware journey (stacked cards / pinned chip rail), route options at
  the decision point, clickable read-only stages with hover summaries, one shared
  status palette, three-tier action grouping, and grouped workspace details with
  custody rows and readable warranty wording.
- Database: no schema change, no migration. Schema 9 unchanged.
- Business logic: no change to lifecycle transitions, warranty, routing,
  technician assignment, inventory, parts, payments, existing records or
  authorization. The primary button still dispatches `snapshot['primary']`
  through the existing handler.
- Validation: full suite **228 passed** (90.59s); journey/details/dropdown/UI/
  layout **35 passed** at 150% display scaling. Eight screens rendered through
  real transitions against a throwaway database and visually inspected.
- Independent review: three defects found and resolved (mnemonic ampersand, raw
  warranty code, collapsed rail height). No open findings. See CODE_REVIEW.md.
- User data: no installed database, customer record or setting was read or
  changed. All verification used synthetic throwaway data.
- **Open and explicitly not done:** the Windows executable has not been built for
  1.6.0, the frozen application has not been captured or launched, and the
  offline Inno Setup installer has not been compiled or verified. Version
  metadata reads 1.6.0, but no 1.6.0 artifact exists in `dist`. Run the existing
  `scripts/build_installer.ps1` gate on the Windows host before shipping.
