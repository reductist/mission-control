# Mission Control public interfaces

This document is the initial human-readable contract catalog. Built-in and third-party plugins must use the same interfaces. Private shortcuts for built-in features are prohibited.

Issue #3 tracks the remaining versioned, language-neutral schemas and generated documentation.

## Stability levels

Every public interface declares one stability level:

- `experimental`: may change between minor releases; intended for early validation
- `stable`: follows semantic compatibility rules and requires a documented deprecation path
- `deprecated`: remains supported for a declared compatibility window
- `removed`: no longer accepted by the current core version

Plugin manifests declare the core interface range they support. Compatibility is checked before runtime code is imported and before migrations are applied.

## Plugin manifest

A manifest is readable without importing plugin runtime code and declares:

- unique plugin identifier
- display name
- plugin version
- supported core interface range
- required and optional capabilities
- entity types and their maximum behavior capability envelopes
- configuration document identifier and generated schema/default/presentation resources
- migration set identifier
- coarse capabilities and operational permissions
- runtime entry point

Unknown required capabilities or incompatible interface ranges cause validation to fail before startup.

Integration plugin IDs use a flat `vendor-capability` convention, such as
`google-calendar` and `google-photos`. Slashes and dots are not namespace
separators: one stable ID must remain safe across configuration keys, command
routing, URLs, package metadata, and normalized database prefixes. The manifest
ID is authoritative; a package directory name is not an implicit identity.

Entity capabilities are distinct from coarse plugin contributions. A plugin may
declare `commands` because it owns command handlers while separately declaring
that its `action` entities may support `lifecycle.complete` and
`lifecycle.reopen`. Standard entity capabilities use core-defined semantics;
plugin-specific behavior must use the declaring plugin's namespace.

## Configuration interface

The application configuration contains core settings, enabled plugin identifiers, and namespaced plugin configuration. The same schema is consumed by:

- `mcctl`
- `mctrld`
- the NixOS deployment adapter
- container deployment adapters
- the guided setup wizard
- appliance images

Plugins may validate only their own configuration namespace. Cross-plugin configuration references require an explicit public capability contract.

Each plugin defines its complete namespaced configuration boundary once in CUE,
including non-secret settings and named credential file references. The manifest
points to generated JSON Schema, explicit defaults, and renderer-neutral
presentation metadata. Mission Control validates and binds all three artifacts,
materializes defaults once, and validates the effective document before opening
the database or importing provider code. A provider receives only its detached,
validated settings and its own credential-name mapping.

## Event interface

Core owns the event envelope. It includes:

- event identifier
- event type
- schema version
- timestamp
- actor and source metadata
- correlation and causation identifiers where available
- payload validated against the registered event schema

Plugin event types are namespaced by plugin identifier. The public core event
writer is planned, not yet exposed by the current adapter. Today a plugin may
atomically maintain its own namespaced event rows through its scoped storage
connection, but it may not write core event tables. Introducing the shared
writer requires an executable transaction contract and conformance tests before
this section becomes a runtime guarantee.

## Storage and migration interface

Core migrations and plugin migrations are recorded separately. Plugin storage access is limited to the plugin's namespace unless a public read model explicitly grants broader access.

A plugin migration declares:

- plugin identifier
- ordered migration version
- supported prior state
- transactional migration operation
- compatibility requirements
- optional reversible or backup requirements

Core validates the migration plan before execution. A plugin may not modify core tables or another plugin's private tables.

The current runtime gives every built-in or explicitly discovered Python plugin the same namespaced SQLite adapter. The adapter authorizes only tables and schema objects in the injective, length-prefixed, core-reserved `plugin__<id-length>__<normalized-id>__*` namespace. The length and doubled separators keep prefix-related IDs distinct, and no plugin ID can collide with a core table. Plugin code obtains names through `context.storage.table_name("local_name")`; the database path is not part of the public context. Core owns migration ordering, checksums, transactions, and the shared ledger. Landscape exercises that boundary through its domain-specific repository, `plugin__9__landscape__*` tables, and append-only events; its packaged agenda document is an import seed, not a runtime source of truth. In-process plugins remain trusted code rather than an operating-system security sandbox, but accidental SQL access to core and unrelated plugin tables is rejected at the supplied connection boundary. A process-isolated storage service remains a later hard-security boundary.

## Command and query interface

Plugins expose domain operations through registered command and query handlers. Handlers receive only documented context objects, including authorized identity, transaction scope, configuration, logging, and approved core services.

Plugins may not reach into private core modules or mutate projections outside their registered operation boundaries.

The current in-process adapter exchanges `mission-control.plugin-call/v1` and
`mission-control.plugin-call-result/v1` JSON documents. Calls use closed,
operation-specific inputs for Agenda snapshots, closed items, entity details,
command state and execution, jobs, health, and shutdown. Outputs are validated
again against their existing versioned capability schemas before core converts
them to internal immutable values. The plugin-facing Python surface is limited
to `PluginContext`, `CapabilityRouter`, and structured call rejection; plugins
do not construct core provider objects.

`runtime.describe` returns a versioned list of implemented operations. Core
requires every operation implied by the manifest, rejects undeclared extras,
and does this during activation before the provider enters aggregation or
routing. `mcctl plugin conformance` exercises the same boundary in a temporary
workspace. This JSON boundary is transport-neutral: a future subprocess or TUI
does not need the built-ins' Python domain classes, though process isolation
still requires an explicit storage/transaction transport.

CLI, HTTP, event, and declarative UI capability names remain reserved in the
manifest vocabulary, but an executable runtime cannot claim them until their
call contracts and adapters are implemented. They are not silent escape
hatches around `runtime.describe`.

Registration defines the maximum capability envelope for each plugin-owned
entity type. A current entity projection exposes zero or more affordances from
that envelope, each mapping one capability to a command. The authoritative
owner exposes the same state-dependent command view for dispatch, including for
entities not present in an active agenda projection. Core rejects undeclared
entity types, affordances outside the envelope, stale revisions, and commands
that are not currently available before invoking the owner. The owner rechecks
revision and domain transition legality transactionally.

Capabilities do not grant filesystem, network, subprocess, secret, or database
access. Those are operational permissions and require a separate permissions
model. In-process plugins remain trusted code; capability enforcement is a
public-contract boundary, not a security sandbox.

The experimental `mission-control.command/v1` envelope routes by a stable source target containing `plugin_id`, `entity_type`, and `entity_id`. It carries the caller's expected revision so the owner can reject stale intent before mutation. Arguments remain owner-specific JSON and are never interpreted by the aggregate renderer.

Core-owned command targets use the same envelope and affordance rules without
pretending to be plugins. Core declares a fixed maximum envelope for each such
entity type. Shared annotations are the first example: an entity-detail note carries
a `core/annotation/<note-id>` source, its own opaque revision, current active or
inactive state, and exactly one `lifecycle.dismiss` or `lifecycle.reopen`
affordance. A note visibility transition appends core audit state and does not
advance the parent plugin entity revision.

The `mission-control.command-result/v1` tagged result reports `accepted`, `rejected`, `conflicted`, `stale`, `unauthorized`, or `failed`. Operator-facing failures are normalized and must not expose raw tracebacks. The transitional `core/task:set-state` slice and Landscape lifecycle capabilities prove the boundary; durable idempotency and actor-aware event envelopes remain experimental follow-up work.

## Agenda contribution interface

Plugins declaring the `agenda` capability may provide immutable, read-only
snapshots of initiatives, actions, and events through the versioned agenda
contract. The provider retains authoritative ownership of detailed state,
recurrence, and transitions. Agenda renderers and aggregators cannot mutate a
provider; complete, defer, approve, and run operations use the separate command
interface and route to exactly one authoritative owner.

Affordances describe currently available behavior; renderers must not infer
operations from an entry kind or state string. An empty affordance list is
valid. Every non-empty affordance list carries the owner's opaque revision.

Agenda v2 also carries renderer-neutral attribution. This metadata is not command
ownership: `source` remains the sole authoritative routing reference. Each entry
has zero or more principal references into the core-owned workspace catalog and
may identify one plugin-scoped connection and a collection within it. Collection
identity is the tuple `(plugin_id, connection_id, collection_id)`; renderers must
not compare a bare collection ID across integrations.

Plugins provide human-readable connection and collection labels, never presentation
colors or CSS values. Core-owned accent preferences target typed principal, plugin,
connection, or collection identities with a closed semantic token palette. Textual
people/source provenance remains visible even when a renderer uses those accents.
The catalog and agenda documents contain no browser-specific concepts. The web UI
and `mcctl` table renderer currently consume both; the legacy `mcctl agenda list`
JSON output remains an entry list without an embedded catalog. A future TUI will
consume the versioned workspace snapshot rather than infer people from that list.
Until the versioned workspace snapshot lands, `/api/dashboard` carries the catalog
as a transitional envelope field; that ad-hoc dashboard response is not the public
TUI contract.

Plugin configuration schemas may mark a string field with the generated JSON
Schema extension `x-mission-control-reference`. Core currently defines
`credential` and `workspace-principal` reference kinds. Credential references
resolve against names configured for that plugin and require its `credentials`
permission; workspace-principal references resolve against the core workspace
catalog. Unknown kinds, non-string annotations, and missing references fail
before database creation, migrations, or plugin import. The extension belongs in
the plugin's CUE-owned schema overlay. `mcctl plugin conformance --workspace
WORKSPACE.json` supplies the principal catalog to plugin-author tests without
exposing Mission Control's internal models to the plugin.

## Closed-item contribution interface

Plugins declaring the `closed-items` capability may project entities that are currently completed or otherwise closed through `mission-control.closed-items/v1`. Activation rejects a provider whose implementation and registration disagree. This current-state projection remains separate from the active agenda and from immutable owner-domain event history. Each item carries its stable source reference, owner-defined display state, closure timestamp, optional context, opaque revision, and current affordances.

Core validates closed-item affordances against the same registration-time entity capability envelope used by active projections. Renderers offer reopen or another operation only when the item advertises that capability; they do not infer lifecycle behavior from `state`, entity type, or the fact that the item appears in this projection. Mutations use the ordinary command path and the provider remains authoritative for transition legality and persistence.

## `mcctl` contribution interface

Plugins may register namespaced subcommands beneath `mcctl`. Contributions declare:

- command path
- argument and option schema
- permission requirement
- input/output schema
- handler capability
- machine-readable and human-readable output support

A plugin must not shadow core commands or commands owned by another plugin.

## HTTP API interface

Plugins may register namespaced HTTP resources through the server interface. Contributions declare request, response, error, authentication, permission, and versioning schemas. OpenAPI documentation should be generated from the same source definitions used for runtime validation.

## Background job interface

A job contribution declares:

- unique namespaced job identifier
- trigger or schedule
- concurrency and retry policy
- permission and secret requirements
- health and progress reporting
- shutdown behavior

Jobs start only after plugin initialization completes and must stop cleanly when the plugin is disabled or Mission Control shuts down.

The current experimental supervisor runs a provider job immediately and then at its declared fixed interval, contains failures at the job boundary, prevents overlap by assigning one thread per job, and joins jobs during shutdown. Providers remain responsible for bounded retries and safe health detail.

## UI contribution interface

UI contributions are declarative manifests that reference approved extension points. A plugin may contribute navigation, dashboard panels, forms, views, and settings surfaces without importing private web application modules.

UI manifests declare required API capabilities and permissions. An unavailable or failed plugin must not prevent unrelated application UI from loading.

The web application is the primary and reference renderer, but UI contribution
documents are renderer-neutral. They describe data, semantic presentation roles,
affordances, form controls, validation, and navigation intent—not HTML, CSS
selectors, DOM events, or executable browser code. A terminal UI may render the
same contribution differently while preserving capability, validation, and
command semantics.

## Authorization interface

Every contribution declares its required permissions. Core evaluates authorization before dispatching to plugin code. Plugins may perform narrower checks but may not bypass or weaken core authorization.

## Health and lifecycle interface

Each plugin reports a structured state such as:

- discovered
- incompatible
- disabled
- migrating
- starting
- ready
- degraded
- failed
- stopping

Health reports include a stable code, safe operator-facing detail, and optional remediation guidance. Secrets and raw exception data must not be exposed by default.

`/api/health` and the dashboard provider catalog currently expose this safe health projection. A transient degraded Google refresh retains cached projections and does not make the core health endpoint unavailable. A terminal `reconnect-required` result erases imported Google cache data instead of retaining private records after authorization is revoked.

## Compatibility policy

Closed CUE document shapes are immutable once published. Field additions—including
optional fields—removals, renames, type or constraint changes, discriminator
changes, and meaning changes require a new `schema_version`. The runtime/plugin API
version is a separate compatibility dimension and does not negotiate document
shape.

Before 1.0, Mission Control supports only the current document version and rejects
unsupported versions explicitly. Breaking transitions update every built-in and
reference plugin together and migrate persisted data when required; the project
does not retain speculative dual readers for external consumers that do not exist.

After external plugins or clients require a compatibility window, version adapters
will be isolated at validation/parsing/serialization boundaries, target one current
internal model, and have a declared removal release. Migrations never run until
both runtime and document compatibility checks succeed. See
[`docs/configuration-and-schema-evolution.md`](docs/configuration-and-schema-evolution.md).

Generated schemas and documentation must be reproducible. CI will eventually fail when checked-in generated artifacts drift from their source schema.
