# ADR 0001: Standards-aligned portable record boundary

- Status: accepted for an experimental foundation
- Date: 2026-10-24
- Scope: portable record and snapshot contracts only

## Context

Mission Control needs a durable contact and calendar/task interchange boundary
without making its current agenda projection or task persistence model the
portable domain model. JSCalendar and JSContact already define the identities,
temporal values, relationships, contact structures, and extension mechanisms
needed at that boundary. Mission Control still needs operational information the
standards do not model exactly: provider provenance, opaque revisions, workflow,
planning-target intent, and deterministic sibling order.

The first implementation must be small enough to validate before a Contacts
plugin, export renderer, DAV adapter, persistence migration, or frontend is
built.

## Decision

Mission Control will exchange a closed, versioned envelope containing an open,
standards-native record:

- JSCalendar 1.0 `Task` and `Event` objects from
  [RFC 8984](https://www.rfc-editor.org/rfc/rfc8984.html) are the portable
  calendar/task payloads.
- JSContact 2.0 `Card` objects use
  [RFC 9553](https://www.rfc-editor.org/rfc/rfc9553.html) as updated by
  [RFC 9982](https://www.rfc-editor.org/rfc/rfc9982.html). New contact records
  use version `2.0`; `uid` is therefore optional.
- The Mission Control envelope owns `record_id`, source identity, revision,
  observation provenance, workflow, planning intent, and sibling order.
- A separate immutable snapshot freezes a set of envelopes under one generation
  timestamp and explicit selector description.
- Agenda and entity-detail contracts remain read projections. Provider
  protocols, persistence, format conversion, rendering, and delivery remain
  separate adapters or later application services.

This is a **Mission Control supported profile derived from the RFCs**, not a
claim that the CUE contract is a complete validator for JSCalendar, JSContact,
the live IANA registries, vCard, or iCalendar.

## Supported profile

### Identities

Three identifiers have separate owners and must survive independently:

1. `record_id` is the stable Mission Control envelope identity.
2. `source.{plugin_id,entity_type,entity_id}` is the provider-owned identity.
3. `record.uid` is the standards identity.

JSCalendar requires `uid` for Event and Task objects (RFC 8984 section 4.1.2).
JSContact 2.0 permits a Card without `uid` (RFC 9982 sections 3 and 4). Mission
Control does not synthesize a contact `uid` from either of its other identities;
RFC 9982 section 5 specifically changes vCard conversion so a UID-less vCard
stays UID-less in JSContact 2.0. A UID-less Card cannot use `members` or
`relatedTo`.

The contracts do not require the three textual values to differ. Their
namespaces and authority differ even if a provider happens to reuse a value.

### Temporal values

JSCalendar `start` and `due` are local date-times. They do not contain a UTC
offset; `timeZone` supplies a named IANA zone or is `null`/absent for floating
time (RFC 8984 sections 1.4.5, 4.7.1, 5.1.1, and 5.2.1-5.2.2). Metadata such as
`updated`, `created`, snapshot `generated_at`, and envelope `observed_at` uses a
UTC `Z` timestamp.

For the first profile, Mission Control interprets local midnight plus
`showWithoutTime: true` as a date-like value. This is an MC normalization
convention, not a unique representation mandated by RFC 8984. Named zones must
exist in the host IANA time-zone database. Custom JSCalendar `timeZones` are
preserved if present but are outside semantic validation in this profile.

`mc.planning.intent` distinguishes `planning-target`, `hard-deadline`, and
`none`. A planning target is not exported as a hard deadline or booked event.
Hard-deadline intent requires a JSCalendar `due` value.

### Workflow and progress

JSCalendar Task `progress` and Mission Control workflow are related but not the
same state machine. Exact mappings are:

| JSCalendar progress | Mission Control workflow |
| --- | --- |
| `in-process` | `in-progress` |
| `completed` | `done` |
| `cancelled` | `canceled` |

Both `backlog` and `ready` map only broadly to `needs-action`, so the MC value is
retained in `mc.workflow.state`. Importing `needs-action` without MC workflow is
reported as ambiguous. `failed` has no exact MC workflow equivalent. `blocked`
and free-text `waiting_on` remain MC workflow metadata rather than invented
progress values.

### Relationships and order

JSCalendar `relatedTo` identifies other objects by their standard `uid` and
natively supports `parent`, `child`, `first`, and `next` relations (RFC 8984
sections 1.4.10 and 4.1.3). Parent/child hierarchy is represented there.
`mc.sibling_order` remains an independent, deterministic UI/workflow ordering
hint.

[RFC 9253](https://www.rfc-editor.org/rfc/rfc9253.html) extends iCalendar, not
JSCalendar. It distinguishes hierarchy (`PARENT`, `CHILD`, `SIBLING`), ordering
(`FIRST`, `NEXT`), dependency (`DEPENDS-ON`), and temporal relationships. The
first JSCalendar profile represents a real task dependency with the permitted
vendor relation `mission-control.dev:depends-on`. A future iCalendar adapter may
map that value to RFC 9253 `RELTYPE=DEPENDS-ON`; this ADR does not claim the
vendor value is defined by RFC 8984. A relation cannot be both `parent` and the
MC dependency relation.

### Extension preservation

The envelope, source, standard selector, MC metadata, and snapshot selector are
closed CUE objects. The standards-native `record` and its supported nested
standard objects remain open to arbitrary I-JSON values. This preserves newer
IANA properties, valid unknown JSContact properties required by RFC 9553
section 1.7.4, and controlled-domain vendor extensions described by both
standards. Known fields in the supported profile are still type checked.

Canonical serialization sorts object keys for deterministic bytes but does not
reorder arrays or discard unknown properties. Exact source whitespace and object
key order are not part of the preservation guarantee.

## Conversion and loss reporting

[RFC 9555](https://www.rfc-editor.org/rfc/rfc9555.html) defines JSContact/vCard
conversion and escape hatches such as `vCardProps`, `vCardParams`, `JSPROP`, and
`JSPTR`. Those mechanisms are optional in places, and no converter is included
in this change. Therefore Mission Control does not yet claim arbitrary vCard
round trips are lossless. The same limitation applies to JSCalendar/iCalendar
conversion.

The experimental task projection emits structured notices:

- `retained`: present in the portable record but absent from the narrow view;
- `normalized`: represented through a documented MC convention;
- `ambiguous`: multiple MC meanings are possible;
- `unsupported`: no exact current MC projection exists.

An empty report is meaningful only for an operation actually exercised by the
tests. It is not evidence of full standards or format-conversion losslessness.
Future provider, DAV, and export adapters must return an inspectable loss report
and prove their own extension behavior.

## Validation boundary

CUE owns the versioned JSON shape and generated runtime schemas. Python semantic
validation adds invariants that the generated schema does not express cleanly:

- kind/standard/object-type agreement;
- UTC versus local date-time semantics and installed IANA zones;
- JSContact 2.0 UID-less relationship restrictions;
- compatible exact workflow/progress pairs;
- parent versus dependency separation;
- unique envelope and source identities in one snapshot;
- acyclic, single-parent hierarchy among selected task records;
- record observation timestamps not later than snapshot generation.

Snapshots may contain unresolved relationship targets because an explicit
selector can legitimately exclude related records. Consumers must not infer a
closed world from one snapshot.

## Consequences and limitations

- Unknown standard fields survive storage/transport through this boundary.
- Mission Control semantics are not forced into the standards or silently
  collapsed into agenda fields.
- The initial schema intentionally validates only a useful subset of known
  fields. It does not evaluate recurrence, custom time-zone definitions, every
  nested JSCalendar/JSContact type, or registry evolution.
- No frontend, Contacts provider, export renderer, DAV synchronization,
  persistence migration, or live task behavior changes in this decision.
- Synthetic fixtures exercise eight fictional remediation tasks and two
  fictional contacts. No real household, medical, contractor, or user-path data
  belongs in repository fixtures.

## Next phase

Build a read-only Contacts provider and a pure export snapshot renderer against
this boundary, with converter-specific loss reports. Only after representative
provider/vCard/iCalendar round trips pass should Mission Control consider a task
persistence migration or active DAV synchronization. Frontend exposure remains
a separate follow-up.
