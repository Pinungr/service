# Repository Agent Map

This repository supports a repo-local software-delivery framework built around Microsoft Copilot chat modes and reusable instructions.

## Primary entry point

The primary entry point is the App Orchestrator.

## Available specialist roles

- App Orchestrator
- Requirements Analyst
- Offline Solution Architect
- UI/UX Designer
- Frontend Developer
- Backend Developer
- Database Engineer
- Test Engineer
- Security Reviewer
- Code Reviewer
- Build/Release Engineer
- Offline Desktop App Expert

## Standard files

- `.github/copilot-instructions.md` : repo-level instructions
- `.github/instructions/*.instructions.md` : shared standards and quality gates
- `.github/chatmodes/*.chatmode.md` : reusable specialist agents
- `.github/prompts/*.prompt.md` : reusable task prompts

## Shared documentation

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

## Operational principle

The orchestrator delegates work only to the specialist roles relevant to the request and keeps review, migration, and testing gates in place.
