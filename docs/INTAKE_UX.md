# Customer registration and repair intake — 1.5.0

## Workflow

1. **Customer:** search by name, phone or alternate number, or register a new customer inline. The selected customer is the submitting customer; any saved customer photo is reused automatically. A recorded shop sale can fill product and warranty details, but it is optional. For an unrecorded shop purchase, enter the product manually on the next step. The saved physical product is available to select for this customer on future visits.
2. **Product:** verify autofilled category, brand/model and serial, or enter them manually; add master choices inline. Photograph the product as received — several photos per product, captured or uploaded here and nowhere else. Linked shop sale warranty dates are calculated automatically. A shop purchase without a linked sale and an external product use customer-reported warranty status until verified; valid reveals optional provider, expiry and notes.
3. **Repair:** record the issue, condition, actual accessories and optional completion date. New accessories are saved to the selected category and immediately checked. No accessories clears the checklist. Repair/service classification is left for later diagnosis.
4. **Confirm:** enter optional transportation/initial deposit, expand additional financial controls if needed, and review. Create Repair Job saves through the existing service. For several devices, Add product and receive another preserves customer/photo and opens a fresh product entry. Each product receives a separate repair job in one atomic visit.

Back/Next preserves input. Save as Draft and existing autosave retain unfinished work, including the visit basket.

Two photo rules, deliberately separate. The **person** is photographed only in the customer section: registration may be saved without a photo, and intake then reuses the saved customer photo rather than asking for a duplicate. A customer with no photo at all is refused on the Customer step, naming Customer details as the place to fix it, instead of failing at the final save. The **product** is photographed only on the Product step, once per product and never shared between products in a visit. Product photos are optional, are stored against the customer while the device record does not yet exist, and are claimed for the device and the repair when the intake is saved — which is what lets the receiving job card reference them.

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
