# Task hierarchy semantics

Task hierarchy groups a concrete outcome with the real tasks needed to reach it.
It does not turn children into checklist text: every child remains an ordinary
task with its own lifecycle, notes, deadline, and tags. The web application is
the reference client, but these rules belong to the core task contract so a
future terminal client can provide the same behavior.

## Shape and validation

The initial hierarchy is deliberately limited to two levels:

- a root task may have zero or more child tasks;
- a child has exactly one `parent_id` and cannot have children of its own;
- `parent_id` is nullable and refers to another existing core task;
- a task cannot parent itself, an ancestor, or any task that would create a
  cycle or a third level; and
- attaching or moving a task validates the complete resulting hierarchy in the
  same transaction as the write.

Invalid or missing parents, cycles, self-parenting, and excessive depth are
rejected without partially moving the task. Detaching a child makes it a root
task again. Converting a task to a parent does not create a replacement record:
the task becomes a parent when its first child is attached.

`sibling_order` controls presentation among tasks with the same `parent_id`,
including root tasks whose parent is null. It is not a dependency, priority, or
permission to start work. Reordering is an explicit operation that leaves task
lifecycle state and metadata unchanged. Moves and reorders produce an
unambiguous order, and simultaneous edits use the normal revision/conflict
behavior instead of silently overwriting one another. Blocked-by relationships
are outside this contract.

## Lifecycle and progress

Parents and children retain independent state. Marking a child done or canceled
does not complete its parent. Marking a parent done, canceled, or reopened does
not mutate any child.

Parent progress is a read-time summary of its direct children, not another
stored lifecycle value. The projection reports at least:

- total children;
- done children;
- canceled children; and
- unfinished children, meaning every child that is neither done nor canceled.

The projection may also report `closed = done + canceled` and a closure percent
based on that count. Done and canceled must remain visibly distinct: a closure
percent must not be labeled as a done or completion percentage. An open parent
with children is `ready_to_close` when its unfinished count reaches zero; this
is a prompt for an explicit parent decision, not an automatic transition. A
parent with no children, or one already done or canceled, is not made ready by
this derived rule.

Completing a parent is always a direct mutation of that parent. If unfinished
children remain, the backend rejects completion with their identities so every
client can surface the remaining work. It must never mark those children done,
hide them as implicitly finished, or describe the parent as having completed
all work. Canceling or reopening the parent likewise leaves children untouched.

## Dates, tags, filters, and calendar

Hierarchy does not imply metadata inheritance:

- each task owns its deadline and may have no deadline;
- each task owns zero or more tags; and
- moving a task never copies, removes, or combines parent or child metadata.

The Calendar displays a parent deadline only when the parent has its own
explicit date, and a child date only when that child has its own explicit date.
It must not synthesize a child occurrence from the parent's deadline or a
parent occurrence from child dates. Child occurrences include enough parent
identity and label context to orient the user while still linking to the child.

Tag filtering evaluates every task's own tags. When a child matches, grouped
views retain a non-matching parent as context and identify it as context rather
than a filter match. They may omit non-matching siblings, but must disclose that
the displayed group is filtered. When a parent itself matches, its normal
collapsed/expanded group remains available. No filter may make a child's tags
appear inherited from its parent.

## Renderer-neutral client contract

Core task reads must expose hierarchy as data rather than requiring clients to
infer it from DOM position or title spelling. A client projection needs stable
task IDs, nullable `parent_id`, sibling order, independent state/deadline/tags,
revision, child IDs or nested child records, and the derived progress fields
above. Filtered and calendar projections also carry explicit parent context for
matched children.

Core task commands, rather than browser-only behavior, own these mutations:

- add a new child;
- attach, detach, or move an existing task;
- reorder a child within its parent; and
- change the state or metadata of either task independently.

Each command is validated server-side and returns the authoritative resulting
projection or a structured validation/conflict error. This lets the web UI,
CLI, and a future TUI share cycle, depth, lifecycle, ordering, and revision
semantics.

The reference web UI presents a dense, collapsible parent row with progress and
indented children. Expand/collapse and reorder controls must be operable by
keyboard and touch without relying on drag alone. Parent detail remains legible
at mobile widths. Compact default views may truncate long display text, but
they preserve the stored text and provide a clickable, keyboard-accessible
expansion without covering edit or hierarchy controls.

## Synthetic review screenshots

These fixtures contain demonstration content only. They show the collapsed,
dense parent summary at [desktop width](assets/task-hierarchy-desktop.png) and
[mobile width](assets/task-hierarchy-mobile.png); no production task data is
included.
