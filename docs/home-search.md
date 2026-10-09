# Home-search research

The Home Search plugin gives sourced house research a durable, reviewable place in
Mission Control. It does not scrape listings, invent recommendations, set an
affordability cap, or start a background watcher.

Enable it in the application configuration:

```toml
[plugins.home-search]
enabled = true
```

The House page then exposes a validated snapshot-import form. Imports use the
existing revision-checked command API and replace the current source result set
atomically. An invalid import leaves the last good snapshot untouched. Candidate
review decisions are kept separately and survive later imports when the stable
candidate ID is reused.

An empty, verified research result looks like this:

```json
{
  "schema_version": "mission-control.home-search-snapshot/v1",
  "revision": "research-run-2026-10-09",
  "checked_at": "2026-10-09T11:30:00Z",
  "sources": ["https://example.com/search/reading-ma-01867"],
  "candidates": []
}
```

Each candidate must be in `Reading, MA 01867` and include a stable ID, address,
verification and listing status, an HTTP(S) source URL, fit reasons, tradeoffs,
unknowns, and an all-in estimate record with explicit assumptions and confidence.
The amount may be `null` when research is incomplete; that candidate remains
visible with the missing cost called out. `indoor_sqft`, when known, is a sourced
fact rather than a hard cutoff. The current roughly 1,800 sq ft excluding finished
walkout-basement space is comparison context, and the preference is a meaningful
usable-space upgrade. Run-level `sources` are required so even an empty result is
auditable.

Research can also be imported by posting the same document as the `snapshot`
argument of an `import-snapshot` command targeting
`home-search/search/reading-ma-01867`. Obtain the target's current `revision` from
`/api/dashboard` or `/api/entities/home-search/search/reading-ma-01867`, and use
the daemon's same-origin write token as usual. This is an ingestion interface, not
an active daily feed.

## Frontend contract

The web interface is one client of the same backend contract available to a TUI or
third-party frontend. It does not own search state or validation:

- `/api/dashboard` exposes the `home-search` agenda contribution. The stable
  `search/reading-ma-01867` initiative is always present while the plugin is
  enabled; current candidates use the `candidate` entity type.
- `/api/entities/home-search/<type>/<id>` exposes criteria, source freshness,
  review state, fit reasons, tradeoffs, unknowns, source URL, and all-in cost as
  entity-detail attributes. Attribute keys are stable identifiers; labels and
  formatted values are presentation-ready.
- Entity and agenda `affordances` are the available actions. The search exposes
  `import-snapshot` through `home-search.snapshot.import`. A candidate exposes
  `set-review-status` through `home-search.review.set-status`; its `status`
  argument is `unreviewed`, `shortlisted`, or `rejected`.
- Commands use `mission-control.command/v1` and must include the current opaque
  entity revision. Successful writes return the new revision. Concurrent writes
  return `stale` with `current_revision`; validation failures return `rejected`
  with a stable error code and safe detail. Clients should refresh and require a
  new user decision after a stale response.
- The authoritative import validator is `snapshot.schema.json` plus the plugin's
  semantic checks (unique candidate IDs and HTTP(S) source URLs). Snapshot
  documents are versioned independently as
  `mission-control.home-search-snapshot/v1`.
- Reads are snapshots. The current web client polls and refreshes after writes;
  there is no push-update or subscription contract yet.

The shared affordance model currently identifies commands but does not carry a
machine-readable argument schema, labels, or input widgets. This plugin therefore
documents the two small command argument contracts above. A future shared
affordance-input schema would improve automatic frontend generation, but is not a
prerequisite for consuming this feature and is intentionally outside this change.
