---
applyTo: "**/*.{py,md}"
description: "Shared domain guidance for offline desktop business applications and local-first design patterns."
---

# Offline Desktop App Expert

## Domain guidance

- Prefer local-first workflows with clear storage, backup, and recovery paths.
- Use Windows-appropriate data locations for application state and shop data.
- Keep database, local files, and report generation under explicit application ownership.
- Support offline operation without cloud dependencies.
- Design for desktop workflows with keyboard navigation, large tables, and business-specific records.

## Common technology patterns

- Python for business logic and desktop features.
- PyQt6 or similar desktop UI frameworks when a GUI is required.
- SQLite with migration-controlled schema versions for local persistence.
- SQLAlchemy when a stronger ORM layer is useful.
- Local file storage and reports for printed or generated documents.
- Windows packaging, installer, and upgrade logic that preserves user data.

## Operational standards

- Protect local secrets and sensitive data.
- Avoid silent data loss during upgrades or uninstall.
- Keep backups explicit and recoverable.
- Record crash and recovery behaviors in the project documentation.
- Prefer deterministic behavior over convenience features for offline reliability.

## Use this specialist as a shared consultant

When a specialist is not certain about a local desktop pattern, it should consult this expertise to validate the architecture, release approach, backup strategy, or data-handling decisions.
