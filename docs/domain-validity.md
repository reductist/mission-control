# Domain validity policy

Mission Control makes authoritative in-process state valid by construction. A
successfully constructed domain entity may be treated as internally valid; callers do
not carry a second set of defensive field checks throughout business logic.

The validation layers have distinct responsibilities:

| Layer | Responsibility |
|---|---|
| CUE and generated JSON Schema | Versioned serialized documents crossing API, plugin, CLI, configuration, job, or export boundaries |
| Frozen domain models | Types, meaningful value bounds, cross-field invariants, timezone awareness, and immutable state |
| Pure domain transitions | Legal state changes, new revisions, and transition timestamps |
| Repositories | Transactions, optimistic compare-and-swap, rehydration, and explicit corruption failures |
| Plugin-owned database migrations | Cheap critical constraints that remain valuable if an adapter is bypassed |

Domain validation uses frozen dataclasses, `__post_init__`, small explicit helpers, and
domain-specific errors. It does not use property setters: authoritative values are
immutable, and many invariants involve more than one field. It also does not require a
CUE schema for private Python objects or a model-validation framework.

## Landscape bounds

Landscape identifiers are limited to 128 ASCII identifier characters so database keys,
command targets, event references, and logs remain predictable. Titles are limited to
256 Unicode characters because they are concise agenda labels. Context is a short label
limited to 128 characters, while inline detail is limited to 4096 characters; larger
documents belong in a future attachment or Wiki capability rather than agenda state.

Core-owned annotations are limited to 16,384 Unicode characters. They are immutable
activity records rather than mutable entity description fields, so they can hold
field observations and measurements without changing a plugin entity's revision.
Annotation actor labels are limited to 256 characters.

Bounds are measured in Python/SQLite characters, not encoded bytes. Boundary tests cover
`N-1`, `N`, and `N+1` where a maximum is defined.

## Transition ownership

Landscape entities define state semantics such as `complete()` and `reopen()` and return
new validated instances. The repository invokes those transitions inside a transaction,
persists the new instance with an optimistic revision check, and appends the event. HTTP
and command adapters only translate outcomes; they do not reproduce transition rules.

Persisted rows are untrusted during rehydration. Invalid rows raise an explicit
`CorruptLandscapeRecordError` with the entity identity and failed invariant instead of
allowing invalid state to enter the application.
