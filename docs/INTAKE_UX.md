# Customer registration and repair intake — 1.5.0

## Workflow

1. **Customer:** search by name, phone or alternate number, or register a new customer inline. Capture/upload a photo. Choose a shop purchase or an external product.
2. **Product:** verify autofilled category, brand/model and serial; add master choices inline. Shop warranty dates are calculated automatically. External warranty offers valid, expired, none or unknown; valid reveals optional provider, expiry and notes.
3. **Repair:** record the issue, condition, actual accessories, service and optional completion date. New accessories are saved to the selected category and immediately checked. No accessories clears the checklist. Active warranty suggests Warranty Assessment while leaving the service editable.
4. **Confirm:** enter optional transportation/initial deposit, expand additional financial controls if needed, and review. Create Repair Job saves through the existing service. For several devices, Add product and receive another preserves customer/photo and opens a fresh product entry. Each product receives a separate repair job in one atomic visit.

Back/Next preserves input. Save as Draft and existing autosave retain unfinished work, including the visit basket. Required customer photo enforcement remains in the service. Registration may be saved without a photo; intake cannot be finalized without one.

## Components and data

- `customer_registration.py`: grouped dialog, inline validation, explicit phone duplicate choice, camera/upload preview and existing customer/photo service calls.
- `intake_wizard.py`: step presentation, conditional fields, sales selection, summary, due-date shortcuts and validation.
- `intake_fields.py`: searchable brand/model masters with inline creation; values remain in existing device text columns.
- `ui.py`, `customer_ui.py`, `visit_intake.py`: existing intake integration, accessory controls and draft/basket preservation.
- `queries.py`: alternate-number customer search.
- `services.py`, `warranties.py`, `parts_ui.py`: validated intake warranty snapshot in existing lifecycle JSON/audit and separately labelled Warranty-tab display. No schema migration.
- `assets/checkmark.svg`, `smoke_intake.py`, `scripts/preview_intake.py`: local indicators and isolated visual verification.

## Validation and limits

Required fields have step/inline errors; optional blank charges become zero and negative/invalid amounts are rejected. Registration photo failures retain the created customer ID for a safe retry. Warranty provider/notes from a hidden previous state are not persisted. Source switching clears obsolete sale/device links. Basket edit restores device defaults before saved values and preserves the parent repair.

Automated coverage includes both requested complete scenarios (existing customer/shop purchase/active warranty and inline new customer/external warranty/new category/accessory), duplicate decisions, photo staging/upload/cancellation/retry, drafts, multi-product visits, linked returns, source switching, currency and date validation. See `TEST_PLAN.md` and `RELEASE.md` for final results.

Existing sales store warranty start/end dates rather than a duration in months; the UI displays a calculated day duration when both exist. Missing expiry is Unknown. Existing brand/model master lists are global, with no brand-to-model mapping; no unsupported mapping is invented. Recorded-date eligibility and customer-reported warranty do not authorize coverage or paid work. Physical camera hardware is exercised through the existing dialog; automated capture tests supply synthetic images.
