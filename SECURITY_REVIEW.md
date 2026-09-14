# Security review

## 2026-09-13: 1.4.4 dropdown arrow repair

Independent review scope: the two bundled chevron SVG files, stylesheet asset
resolution and combo/date/spin button styling, SVG package declarations, and
1.4.4 version identifiers. Earlier application and installer changes are outside
this review; this is not a new security approval of those features.

Findings: no new security issue identified in the scoped change. No blocker or
high finding requires remediation.

- Both SVGs consist of a fixed viewport and a single stroked path. They contain
  no scripts, links, external resources, embedded files, or user-supplied data.
- Stylesheet image paths come from the application package and fixed filenames.
  Customer input and database fields do not enter those paths. Rendering does
  not introduce a network dependency or credential access.
- Packaging selects only `assets/*.svg` for the new resources. No customer
  records, photos, passwords, backups, or other runtime data are added by this
  declaration.
- This fix does not change authentication, authorization, persistence,
  migrations, backup handling, installation permissions, or uninstall behavior.

Security disposition: no additional mitigation required for this scoped fix.
Release remains dependent on the orchestrator's regression and frozen-build
verification; those tests are not claimed as performed by this reviewer.

### Follow-up: explicit smoke-test diagnostic

Independently reviewed the diagnostic in `repairshop/smoke_controls.py` and its
explicit `--smoke-test` call site. No new security finding. It captures only its
own synthetic controls, not the desktop or the customer-data window. The output
is a fixed `ui-controls-smoke.png` filename in the selected application data
directory. The call does not add an authentication bypass, change file
permissions, execute user content, or upload data. Normal startup does not write
this diagnostic image. Frozen verification should use the orchestrator's
isolated synthetic data directory.

## 2026-09-13: Customer registration and intake wizard

Reviewed new registration/photo upload, wizard input handling, duplicate-customer
selection, sale/warranty integration, and backend intake metadata validation.
No new authentication, SQL injection, arbitrary write, or sensitive-data exposure
finding identified. Photo import checks file size and dimensions and uses the
existing managed photo persistence; photo-save retry retains the customer ID.
Warranty snapshots are explicitly reported/date-only and do not authorize a
warranty claim. The backend rechecks linked sale ownership and photo integrity.

The HIGH workflow integrity defect recorded in CODE_REVIEW.md is resolved:
reactive wizard handlers are suppressed during basket restoration. The reviewer
independently ran the linked-return edit/save regression and confirmed preserved
parent and device links. The additional intake photo upload uses the same file
size/pixel limits and existing role-authorized managed photo persistence; null
images are rejected by that service. No new security finding identified.

Current disposition: no open security findings in this scope. This review does
not claim that all new tests or end-to-end release checks have passed.

### Final presentation delta

Reviewed name-valued brand/model selectors, local checkbox SVG/QSS, and demo
smoke form capture. No new security findings. Master creation uses the existing
authorized service; no SQL interpolation or alternate persistence path is added.
The SVG contains only a stroked check path. Explicit demo smoke capture renders
application forms to the chosen local data directory, restores its submission
interception in `finally`, and does not invoke customer or intake save callbacks.
The release owner is testing with isolated synthetic data.
