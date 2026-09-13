---
applyTo: "**/*.md"
description: "Handoff rules between specialist skills and required outputs."
---

# Handoff Rules

## Requirement to architecture

Requirements Analyst produces functional and non-functional requirements.

Solution Architect consumes those requirements and produces:

- architecture summary
- service boundaries
- dependency direction
- integration boundaries
- module layout
- technical risks
- decisions

## Architecture to UI

UI/UX Designer consumes requirements and architecture and produces a screen-level design specification.

Frontend Developer consumes the UI specification and service contracts.

## Architecture to database

Database Engineer consumes requirements and architecture and produces:

- schema
- constraints
- indexes
- migration plan
- backup and rollback considerations

## Architecture to backend

Backend Developer consumes architecture, domain rules, and database specification.

## Implementation to testing

Test Engineer consumes requirements, architecture, and implementation and produces test plans with requirement IDs and regression coverage.

## Implementation to security and review

Security Reviewer reviews the implementation and identifies risk.

Code Reviewer independently reviews the implementation and classifies defects.

## Release

Build/Release Engineer packages only after quality gates pass and after release checks are complete.

## Key rule

Do not let specialist roles bypass the defined handoff chain. The output of each step should be explicitly reviewed before the next step proceeds.
