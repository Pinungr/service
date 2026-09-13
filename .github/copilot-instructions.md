# Repository Copilot Instructions

This repository uses a repo-local software-delivery framework for offline desktop and business applications.

## Primary entry point

Use the App Orchestrator as the default entry point for most requests. It decides whether a request is a new application, feature addition, bug fix, UI improvement, DB change, testing task, security review, or release task.

## Supported repository-local skill model

The current environment supports repo-local reusable prompts and custom chat modes:

- `.github/chatmodes/*.chatmode.md` for specialist agents
- `.github/instructions/*.instructions.md` for shared standards
- `.github/prompts/*.prompt.md` for reusable usage patterns
- `AGENTS.md` as a maintainable human-readable repository map

Use these instead of inventing a proprietary format.

## Operating principles

- Prefer the smallest safe change that satisfies the requirement.
- Preserve existing behavior and avoid unnecessary refactoring.
- Respect the current technology stack unless a strong reason justifies a change.
- Keep UI, service, domain, and persistence responsibilities separated.
- Require requirements before major implementation work.
- Require architecture review before major design changes.
- Require migration planning for any database schema change.
- Require tests for bug fixes, behavior changes, and new features.
- Require security and independent code review before release.
- Keep documentation updated for the relevant specialty.

## Standard lifecycle

For new applications or significant features:

1. Requirements Analyst
2. Solution Architect
3. UI/UX Designer
4. Database Engineer
5. Backend Developer
6. Frontend Developer
7. Test Engineer
8. Security Reviewer
9. Code Reviewer
10. Build/Release Engineer

Small changes may skip unnecessary stages.

## Required artifacts

Before major changes, read or create the relevant project documentation:

- PROJECT_CONTEXT.md
- REQUIREMENTS.md
- ARCHITECTURE.md
- DATABASE.md
- UI_DESIGN.md
- TEST_PLAN.md
- SECURITY_REVIEW.md
- CODE_REVIEW.md
- RELEASE.md
- DECISIONS.md

Use the shared instructions files for standards, handoff rules, and quality gates.
