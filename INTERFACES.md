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
- display name and description
- plugin version
- supported core interface range
- required and optional capabilities
- entity types and their maximum behavior capability envelopes
- configuration schema identifier
- migration set identifier
- registered event types
- CLI, API, job, UI, permission, and health contributions
- runtime entry point

Unknown required capabilities or incompatible interface ranges cause validation to fail before startup.

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

## Event interface

Core owns the event envelope. It includes:

- event identifier
- event type
- schema version
- timestamp
- actor and source metadata
- correlation and causation identifiers where available
- payload validated against the registered event schema

Plugin event types are namespaced by plugin identifier. Plugins append events through the public event writer and may not write directly to core event tables.

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

The current Landscape vertical slice exercises the intended ownership boundary with a domain-specific `LandscapeRepository` protocol, a `SQLiteLandscapeRepository` adapter, `landscape_*` tables, an independently recorded migration version, and append-only Landscape events. Its packaged agenda document is an import seed, not a runtime source of truth: activation records the import once and subsequent starts project only from persisted state. A generalized storage capability and third-party migration planner remain future interface work.

## Command and query interface

Plugins expose domain operations through registered command and query handlers. Handlers receive only documented context objects, including authorized identity, transaction scope, configuration, logging, and approved core services.

Plugins may not reach into private core modules or mutate projections outside their registered operation boundaries.

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

## UI contribution interface

UI contributions are declarative manifests that reference approved extension points. A plugin may contribute navigation, dashboard panels, forms, views, and settings surfaces without importing private web application modules.

UI manifests declare required API capabilities and permissions. An unavailable or failed plugin must not prevent unrelated application UI from loading.

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

## Compatibility policy

Before the interfaces become stable, changes may be made directly but must update the contract tests and reference plugin. After stabilization:

- additive optional fields are compatible
- required-field additions require a new interface version
- meaning changes require a new interface version
- removals require deprecation and a declared support window
- migrations never run until compatibility checks succeed

Generated schemas and documentation must be reproducible. CI will eventually fail when checked-in generated artifacts drift from their source schema.
