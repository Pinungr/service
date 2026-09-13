---
applyTo: "**/*.md"
description: "Quality gates and release readiness rules for significant work."
---

# Quality Gates

For significant features or new applications, enforce these gates:

1. Requirements understood.
2. Architecture defined.
3. Database impact reviewed.
4. UI/UX defined where applicable.
5. Implementation completed.
6. Automated tests pass.
7. Security review completed.
8. Independent code review completed.
9. Blocker/high-priority defects resolved.
10. Regression tests pass.
11. Release/build validated.

For small changes, the Orchestrator may skip non-essential gates.

## Gate expectations

- A change should not move to testing without requirement traceability.
- A schema change should not move to implementation without migration analysis.
- UI work should not proceed without design intent.
- Release packaging should not proceed without validation.
- Critical defects must be resolved before release.

## Exit criteria

A feature is ready to proceed when the relevant specialist outputs are complete, the implementation matches the agreed architecture, tests are passing, and findings from security/code review are addressed.
