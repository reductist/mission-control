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
