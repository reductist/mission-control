# Mission Control Agent Instructions

## Delegation policy

Use subagents for bounded, independent exploration, test/schema review, CI
triage, and final correctness review when beneficial. Keep architecture,
integration, and overlapping writes with the main agent. Announce each
delegation and its purpose.

Prefer delegation when it materially improves wall-clock speed, protects the
main thread's architectural context, or adds an independent correctness check.
Avoid it when coordination and repeated context would cost more than the work
itself.

## Design-grounding preference

Treat architecture and design plans as hypotheses to test against the working
software. Unless the user marks a decision as non-negotiable, surface what is
and is not working as intended, explain the implementation evidence, and
propose simpler or better-grounded alternatives before entrenching a plan.

Favor plugin-author simplicity and small, enforceable contracts over preserving
an earlier design or accumulating compatibility edge cases. During the
pre-release phase, breaking changes are acceptable when they produce a cleaner
schema and migration path.

Treat the web UI as Mission Control's primary and reference interface, not as the
contract itself. Keep shared snapshots, affordances, setup actions, forms, and
plugin UI contributions transport-neutral so a future TUI can use them without
depending on DOM structures, browser code, or duplicated plugin semantics.

## Product communication

Lead user-facing documentation with the human outcome: Mission Control absorbs
the sharp edges and interface churn of many tools into calm, consistent controls
that reduce cognitive load and required attention. Keep the README approachable,
personal, and task-oriented for unfamiliar users. Move dense contract terminology
and contributor design detail into clearly linked reference documents rather than
making it the product introduction.
