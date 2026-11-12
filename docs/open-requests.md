# Follow through on requests

The **Requests** view keeps a request visible after its research or development
work finishes, so the remaining step does not disappear into a chat history.
Enable the `open-requests` plugin in the normal application configuration. It
requires no credentials. The first view is empty; no private chat is imported.

Each request has:

- a title and short context;
- an explicit status: **Open**, **Waiting**, **Ready for you**, or **Closed**;
- a next step and searchable tags;
- zero or more linked Mission Control task sources;
- separate **follow-up work** links and **result / solution** links.

For example, a request can link two MC tasks, a work thread with a usable web
URL, and a Google Drive report. The same task or result can serve several
requests. Task links retain the full plugin/type/id reference. If a linked task
is unavailable or its plugin is disabled, its reference is retained and shown
as unavailable; it is never silently removed. Linking does not alter a task. Linked task detail pages show reciprocal
**Related requests** links while the tracker is enabled.

Use **Ready for you** when a result needs reading or action. A completed task or
new result link does not close the request. Close it explicitly when follow-through
is finished using its completion checkbox. Completed requests move into the collapsed
**Completed history** section; expand it and uncheck a request to reopen it.
Search and tag filters apply to history too. Each card displays its stable,
selectable Request ID so you can refer to it unambiguously. Change history is retained.

## First-slice limits

This is a manual UI and command-API integration, not a chat crawler or background
synchronizer. An assistant can create/update records through the same authenticated
commands the UI uses. It must supply actual known links; no placeholder link is
invented for work that does not have a shareable URL. Use the next step/context
for now when a result is only in a conversation.

Only absolute HTTP(S) links without embedded credentials are accepted. The app
does not fetch them, verify access, change sharing, upload documents, or cache
remote content. Check recipient access before linking sensitive documents.

The compact record is limited to 4096 serialized Unicode characters (including
identifiers and timestamps) to fit the existing transport-neutral detail contract.
Long answers belong in a linked document. Individual limits are title 256,
context 1200, next step 512, 20 tags of 48 characters, 20 task references, and
10 links per category (label 128, URL 1024). The total limit still applies.
Tags are trimmed and lowercased. This proof of concept deliberately does not
extend core schemas to store document bodies.

## API and concurrency

Read `/api/entities/open-requests/tracker/requests` through the normal entity
endpoint. The detail
revision is the tracker revision; each `request:<id>` attribute contains one
JSON record. The same contract can be consumed without a browser.

Send `mission-control.command/v1` envelopes to `/api/commands`, targeting:

```json
{"plugin_id":"open-requests","entity_type":"tracker","entity_id":"requests"}
```

`create-request` takes `{"request": { ... }}`. `update-request` takes
`{"request_id":"existing-id","request": { ... }}`. Supply all eight request
fields: `title`, `description`, `status`, `next_step`, `tags`, `task_links`,
`work_links`, `result_links`. Server-assigned `id`, `created_at`, and `updated_at`
are returned in snapshots and must not be included in command request fields.

Task references use `plugin_id`, `entity_type`, `entity_id`. URL entries use
`label` and `url`. Include the current `expected_revision` and a unique command
ID. Retries with the identical envelope replay the committed result; reusing an
ID for different input is rejected. Concurrent stale updates are rejected rather
than silently overwriting newer changes. Request updates, audit history, revision,
and replay receipt commit atomically in the plugin's own namespaced tables.
No hard delete is exposed. Disabling the plugin preserves its records.

## Verification

Run the Python suite, web tests, schema drift check with CI's pinned CUE v0.16.1,
and native browser tests as documented in `TESTING.md`. Request tests cover
restart persistence, shared/multiple links, tags, close/reopen, invalid URLs,
atomic rejection, idempotent retries, stale edits, concurrency, and isolation
from the family rewards plugin.
