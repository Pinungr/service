# Requirements and acceptance traceability

The complete supplied brief is preserved in `REQUIREMENTS.md`. This table distinguishes automated evidence from external/platform validation dependencies. Tests use real temporary SQLite databases, synthetic contacts and disabled live sending.

| Acceptance scenario | Implementation | Automated evidence |
|---|---|---|
| 1. Reusable options survive restart | `Service.save_master`, normalized keys, category associations, selectors | `test_reusable_normalized_directories_restart` |
| 2. Accessories unchecked; save only received | Intake checklist, quantity and serial controls | `test_real_intake_accessories_start_unchecked_and_persist` |
| 3. Device dispatch leaves accessories | `Service.move`, independent holdings | `test_device_only_dispatch_accessories_remain` |
| 4. Partial quantities and missing items | Atomic decrement/increment, closure guard | `test_partial_custody_conservation_and_closure` |
| 5. Multiple vendor assignments/costs | Assignment history, independent vendor accounts | `test_assignments_do_not_move_and_keep_vendor_charges` |
| 6. Owner/submitter recipient deduplication | Per-job additional contact, normalized outbox destinations | `test_owner_submitter_dedup_and_no_cost_leak` |
| 7. Warranty eligibility separate from decision | Sale linkage, immutable centre decisions | `test_warranty_date_pending_decision_rejection` |
| 8. No-charge warranty retains transport | Independent coverage and policy snapshot | `test_accepted_warranty_retains_transport` |
| 9. Centre replacement identity/terms | Linked replacement item and audit evidence | `test_replacement_preserves_serial_and_terms` |
| 10. Exact quote-version approval | Immutable quotes, decisions, revised-work guard | `test_quote_version_approval_deposit_and_revision`, `test_no_deposit_required_and_immutable_quote` |
| 11. Approval and deposit guards | `_authorize_repair` called by both stage and work recording | `test_paid_work_records_cannot_bypass_approval`, `test_reversed_deposit_no_longer_authorizes_repair` |
| 12. Decline policy/refund due | Per-job agreed charges, separate actual refunds | `test_decline_policy_snapshot_and_refund_due` |
| 13. External complete is awaiting return | Custody/test guard and event wording | `test_external_completion_not_collection_ready` |
| 14. Unrepaired return without false test | Ready-unrepaired stage and collection | `test_unrepaired_collection_without_false_test` |
| 15. Advances, receipts, refunds, money | Integer paise, operation IDs, signed ledger | `test_financial_rounding_duplicate_and_refund` |
| 16. Vendor statement and INR 3 reduction | Posting-date ledger, opening/closing, allocations | `test_vendor_3553_to_3550_monthly_settlement`, `test_overallocation_rolls_back_entire_post` |
| 17. Collection/refusal does not settle debt | Independent accounts and closure | `test_collection_does_not_settle_debts` |
| 18. Shared transport / included cost | Exact expense allocation and margin query | `test_shared_transport_and_included_cost_not_double_counted` |
| 19. Offline durable queue / relevance | Transactional outbox, consent/version checks | `test_offline_outbox_survives_restart_and_consent`, `test_obsolete_quote_and_pickup_are_cancelled` |
| 20. Claims, duplicate posts, uncertainty | Atomic worker claims, safe uncertain state | `test_workers_claim_once_and_ambiguous_outcome`, `test_intake_operation_duplicate_does_not_create_second_job` |
| 21. Dashboard counts actual units | Holdings aggregation separate from stages | `test_dashboard_units_not_movement_rows` |
| 22. Consistent backup and missing drive | SQLite backup API, attachment manifest, external states | `test_backup_restore_attachments_balances_and_readonly`, `test_missing_external_drive_preserves_local_backup` |
| 23. Read-only viewing and safe restore | mode=ro viewer, owner confirmation, outbox pause | `test_backup_restore_attachments_balances_and_readonly` |
| 24. Corruption/disk-full/interruption | Checksums, safe paths, atomic archive, restore journal | `test_corrupt_archive_rejected_without_touching_live` (four variants), `test_failed_backup_preserves_last_good`, `test_interrupted_restore_rolls_back_on_startup` |
| 25. Upgrade and role boundaries | Versioned migrations, pre-upgrade snapshot, service permissions | `test_upgrade_preserves_history`, `test_limited_role_service_guards` |
| 26. Scale and UI | Indexed/paged query paths, background tasks, synthetic generator | `docs/benchmark-results.json`, desktop tests; measurements are local observations, not a universal guarantee |
| 27. Standalone Windows launch | Single-file PyInstaller x64 executable, first-run flow | ZIP membership and extracted executable launch/restart are checked by `scripts/verify_package.py`; a separate clean Windows VM/offline installation remains independent validation |

Additional tests cover stale-form conflicts, spreadsheet formula injection, issued document generation, corrected allocations, revised invoices without double billing, saved quote branding/customer snapshots, internal recipients, statement capture and obsolete collection reminders.

## Requirements by module

| Brief sections | Screens / implementation |
|---|---|
| 1–3: delivery, architecture, local identity | First run, role logins, data root, lock, SQLAlchemy/SQLite, `persistence.py` |
| 4–5: reusable lists, customer/sales/intake | Directories, Customers, Products sold, Jobs/intake |
| 6–8: custody, work and warranty | Dispatch & receive, job tabs, centre/replacement records |
| 9–11: transport, quotes and accounts | Shared expense form, quote/decision forms, customer/vendor accounts |
| 12–13: messaging and dashboards | Notifications, provider settings, recipients, reminders, real-query dashboard |
| 14: documents/reports/audit | Managed PDFs, export engine, report filters, immutable audit |
| 15–16: backup/persistence/scale | Archive/view/restore, WAL and migration policy, benchmark script |
| 17–19: tests, packaging and documentation | Tests, pinned dependencies, build script/spec, portable ZIP and guides |

## Explicit verification boundaries

Live WhatsApp and SMTP accounts were not connected. Meta template acceptance, real delivery and OAuth token renewal depend on the owner's account setup. Delivered/read webhooks and inbound reply ingestion are outside this outbound-only deployment. A separate clean Windows computer, real power-loss test and actual full-disk device were not used; corruption, failed writes and interrupted replacement were exercised through controlled synthetic tests. The scale dataset has bounded/no bulk photos; attachment correctness is tested separately with real files.


## Version 1.1 customer-photo additions

`tests/test_customer_photos.py` covers missing cameras and hot-plug retry, camera selection/release, four simulated camera failures, capture/retake/persistence, disk-full retry, required-photo enforcement, owner/submitter history, duplicate names and stable folders, traversal rejection, same-category devices/shared visits/repeat repairs, ownership guards, accessory-aware readiness/partial collections, transit/centre/unrepaired states, completed history, photo import/recovery/backup relocation/restore, summary conflicts, backup-before-migration failure, intake cancellation/draft restart/resumption and overview placeholders. The existing migration acceptance case now reconstructs a real version-1 schema and verifies the full pre-upgrade ZIP and preserved records.

Additional cases verify readiness blocked by a job hold, successful intake consuming its draft with idempotent retry, empty photo directories in archives and interrupted restoration preserving both customer folder trees.
