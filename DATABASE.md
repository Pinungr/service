# Database impact — intake UX 1.5.0

Schema remains version 9. Customer fields, photos, category/accessory relations, brand/model masters, sales links, per-device jobs and intake drafts reuse existing tables and service transactions.

The optional `intake_warranty` object is added to existing `jobs.lifecycle_data` JSON and recorded as `intake_warranty_recorded` audit evidence in the same intake transaction. Shop snapshots derive from the selected, ownership-checked sale. External snapshots are validated customer reports; hidden valid-only fields are cleared for other statuses. Existing verified manual warranty checks and coverage decisions are not replaced. Older jobs without the optional object retain their behavior. No migration, reset or destructive data conversion is required.
