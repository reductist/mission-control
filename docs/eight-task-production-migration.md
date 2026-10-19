# Eight-task production hierarchy migration plan

This is an operator runbook for grouping the existing eight numbered mold tasks
after the hierarchy feature has been reviewed, merged, and approved for
deployment. It intentionally contains no production IDs, titles, dates, notes,
statuses, tags, screenshots, or other private data. Keep the completed mapping,
command output, backup location, and validation evidence in private operational
storage, not in this repository or a pull request.

**Do not run this plan yet.** Merging the feature does not authorize a
production deployment or data migration. Obtain separate deployment and
migration approval immediately before the maintenance window.

## Intended result

Create one new parent task and attach the eight existing task records to it in
their approved numbered order. Do not recreate or copy the existing tasks.
Attaching the existing records preserves their IDs and all independently owned
fields, including descriptions, dates, notes and note history, statuses, tags,
event history, and timestamps. The only intended changes to an existing task
are its `parent_id`, sibling order, hierarchy revision/event data required by
the released implementation, and the normal update timestamp if that contract
advances it.

The new parent has deliberately chosen metadata. Do not infer its deadline or
tags from the children, and do not copy its metadata back to them. Its title,
description, status, deadline, and tags require an explicit operator decision
in the private change record.

## Private mapping worksheet

Make a private copy of this template and replace every placeholder from a fresh
production read. Never commit the completed copy.

| Position | Existing task ID | Preflight revision | Expected status | Expected deadline | Expected tag set | Notes/history check |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `<TASK_01_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |
| 2 | `<TASK_02_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |
| 3 | `<TASK_03_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |
| 4 | `<TASK_04_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |
| 5 | `<TASK_05_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |
| 6 | `<TASK_06_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |
| 7 | `<TASK_07_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |
| 8 | `<TASK_08_ID>` | `<REVISION>` | `<STATUS>` | `<EXACT VALUE OR NULL>` | `<EXACT SET>` | `<COUNTS/HASH>` |

Also record `<NEW_PARENT_ID>`, the released application version and migration
ledger version, backup identity, approver, execution time, and operator. Check
that the selected set contains exactly eight unique IDs and excludes unrelated
personal or medical tasks.

## Preflight

1. Confirm explicit approval for both the production release and this data
   change. Confirm the reviewed commit is the exact artifact to deploy.
2. Put normal writers into the deployment's supported maintenance mode. Take a
   verified, restorable SQLite backup using the deployment runbook; retain its
   checksum and test that it opens and passes integrity checks in an isolated
   location.
3. Run schema migrations and application health checks without changing task
   relationships. Confirm migration compatibility from the installed version
   and that existing tasks still read with `parent_id = null` and no lost
   metadata.
4. Fetch the eight candidates by exact ID into the private worksheet. Verify
   their human labels and numbering with the approver. Capture exact revisions,
   statuses, deadlines, tags, descriptions, note/history counts (or private
   hashes), and current hierarchy fields.
5. Abort if any ID is missing or duplicated; any candidate already has a
   parent or children; the order is ambiguous; a revision changes during the
   window; an unrelated task is selected; or backup/health verification fails.

## Dry run and execution

Use the released core task commands or an accompanying reviewed migration tool,
not ad hoc production SQL. First run its non-writing validation against the
private manifest. It must resolve all eight IDs, validate the two-level result,
show one new parent plus eight relationship changes, and show no lifecycle,
deadline, tag, description, note, or history mutation.

After a second review of that output:

1. Create the parent with the approved explicit metadata and record its ID.
2. In one transaction, or with the released tool's documented all-or-nothing
   behavior, attach task positions 1 through 8 to that parent using their
   preflight revisions and assign sibling order accordingly.
3. Stop on any validation or stale-revision error. Do not skip an item or leave
   a partially approved hierarchy; use the tool's rollback behavior and repeat
   preflight before retrying.

Do not change child state to make parent progress look cleaner. Parent progress
is derived, canceled remains distinct from done, and closing the parent remains
an explicit later action.

## Verification

Before ending the window, independently read the result through the backend
contract and the desktop and mobile web views:

- the parent has exactly eight children in the approved order;
- every original ID is unchanged and appears exactly once;
- each child's title, description, status, deadline, tags, notes, event history,
  and creation timestamp match the private preflight record, while any revision
  or update timestamp change is exactly the hierarchy change expected by the
  released contract;
- no date or tag was inherited in either direction;
- progress counts agree with the eight independent child states and canceled is
  not reported as done;
- filters that match a child retain parent context, and Calendar shows only
  explicitly dated records; and
- an unrelated-task sample, including any sensitive category checked privately,
  has no changed row, relationship, history, or projection.

Store verification output privately. Any screenshots attached to a public issue
or pull request must use synthetic demonstration content, never this production
hierarchy.

## Backout

If application verification fails but stored data is intact, keep writers
paused and use the released hierarchy commands to detach the eight children in
one reviewed operation, preserving their records and metadata. Remove or archive
the newly created parent only if the application's supported operation is
reversible and the private audit confirms it has received no independent notes,
edits, or history that must be retained.

If schema or data integrity is uncertain, stop the service and restore the
verified preflight backup according to the deployment runbook instead of
attempting hand-written repairs. Re-run integrity, migration-ledger, task-count,
metadata, and unrelated-record checks before reopening writers. Record the
failure and resulting state privately, and require fresh approval before any
retry.
