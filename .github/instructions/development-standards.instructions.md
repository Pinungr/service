---
applyTo: "**/*.{py,md,sql,yml,yaml,json}"
description: "Shared standards for offline desktop application work and repo-local skill orchestration."
---

# Shared Development Standards

## Architecture

- Keep UI code separate from persistence and business logic.
- Prefer a layered approach: UI -> Services -> Domain -> Repositories -> Database/File System.
- Avoid direct SQL or repository access from UI code.
- Keep modules cohesive and small.
- Preserve backward compatibility where practical.

## Design

- Favor clear naming, typed interfaces, and small functions.
- Avoid overengineering; apply DRY and SOLID where they provide real value.
- Prefer explicit validation, safe error handling, and structured logging.
- Keep business rules in domain or service layers instead of UI widgets.

## Offline desktop application rules

- Design for local-first operation with clear recovery paths.
- Treat database and file backups as first-class operational concerns.
- Assume user data may already exist; do not wipe or replace it without migration planning.
- Assume local Windows file permissions and application-data location requirements.
- Keep release and installation paths well-defined and testable.

## Quality bar

- Require tests for non-trivial changes.
- Add regression tests for bugs and behavior changes.
- Keep findings actionable and specific.
- Make only the minimum safe change to satisfy the requirement.

## Documentation

- Update only the documentation relevant to the specialty involved.
- Use the shared templates for project context, requirements, architecture, database, UI, test, security, code review, release, and decisions.
- Record important design decisions in DECISIONS.md.
