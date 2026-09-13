# Skill Framework README

This repository contains a reusable multi-skill framework for offline desktop business application work.

## Primary entry point

Use the App Orchestrator as the default starting point for requirements, design, implementation, testing, and release tasks.

## Framework structure

- `.github/chatmodes/` : specialist agent definitions
- `.github/instructions/` : shared standards and quality gates
- `.github/prompts/` : reusable prompt templates
- `AGENTS.md` : human-readable repository map
- `docs/templates/` : project documentation templates

## Lifecycle

For significant work, use the full lifecycle:

1. Requirements Analyst
2. Offline Solution Architect
3. UI/UX Designer
4. Database Engineer
5. Backend Developer
6. Frontend Developer
7. Test Engineer
8. Security Reviewer
9. Code Reviewer
10. Build/Release Engineer

## Example usage

- "Use the app orchestrator to create an offline computer repair shop application."
- "Use the app orchestrator to add customer photo capture using webcam."
- "Review this application using the architecture, security, database, testing and code-review skills."
- "Improve the UI/UX of the current application without changing existing functionality."
- "Create a Windows production build of this application."

## Principles

- Prefer the minimum safe change.
- Preserve existing functionality.
- Require requirements before major implementation.
- Require architecture review before significant design changes.
- Require migration safety and regression testing for database and behavior changes.
- Keep security review and independent code review in the release path.
