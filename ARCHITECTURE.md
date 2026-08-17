# Mission Control architecture

## Boundary

Mission Control is a portable application deployed through environment-specific adapters; it is not part of any host's internal configuration model.

The application may consume platform-provided paths, sockets, credentials, and network bindings, but application code must not import host configuration or assume NixOS. Deployment adapters translate platform configuration into the application's stable configuration model.

## Process and package names

- Mission Control is the product name.
- `mission-control` is the application and distribution package name.
- `mission_control` is the Python import package.
- `mcctl` is the canonical administrative CLI.
- `mctrld` is reserved for the long-running daemon.
- `mission-control.service` is the systemd unit.
- `services.mission-control` is the NixOS option namespace.

These names are public interfaces and should not drift casually after the first release.

## Core responsibilities

The core owns:

- immutable event recording and event-envelope validation
- projections and query interfaces
- core schema migrations
- application configuration validation
- plugin discovery and lifecycle contracts
- plugin contribution registration and per-entity capability envelopes
- validation of state-dependent affordances before command dispatch
- authorization boundaries exposed to plugins
- failure containment and health aggregation

The core does not own product features or integrations with external services. Tasks, wiki, dashboards, and other built-in capabilities must use the same public plugin interface available to third-party plugins.

## Plugin responsibilities

Each plugin owns:

- a globally unique identifier, version, and declared core compatibility range
- its configuration schema and defaults
- its database migrations and namespaced data
- its event types and payload schemas
- its entity types, maximum capability envelopes, and current affordances
- optional API, `mcctl`, background-job, and UI contributions
- permissions required by each contribution
- health reporting, shutdown, disable, and cleanup behavior
- tests proving compliance with the public plugin contract

Plugins may use only documented core interfaces. They must not import private core modules, mutate core projections directly, modify another plugin's tables, bypass authorization, or emit unvalidated events.

The target authoring boundary is versioned JSON validated from CUE, with a small
public language adapter. In-process Python is an initial runtime mechanism, not a
license for plugins to exchange core-private classes. Core supplies a narrow,
plugin-namespaced storage and event adapter inside one transaction so domain
mutation and event append remain atomic. See
[`docs/configuration-and-schema-evolution.md`](docs/configuration-and-schema-evolution.md).

## Public plugin lifecycle

All plugins, including built-in plugins, follow the same lifecycle:

1. Discover and read the manifest without importing runtime code.
2. Validate identity, version, compatibility, permissions, and configuration.
3. Plan and transactionally apply namespaced migrations.
4. Import and initialize the plugin through the public runtime interface.
5. Register declared contribution and per-entity capability envelopes.
6. Start background work only after the application becomes ready.
7. Stop jobs and unregister contributions during disable or shutdown.
8. Preserve plugin data when disabled unless an explicit destructive removal is requested.

The runtime must be able to identify a failed plugin, isolate its contributions, and start Mission Control in a recoverable mode when core invariants remain intact.

The Google vertical slice exercises the current application lifecycle: configuration and named credential requirements validate before runtime import, core applies the declared namespaced migrations before activation, and periodic work begins only after the application is ready. Each source refresh replaces one complete cached collection transactionally. A transient failed refresh retains the last good collection and reports degraded health without blocking core or unrelated providers; a terminal authorization revocation erases imported Google cache data and requires reconnection. OAuth secrets and access tokens are not persistence fields.

## Public contribution interfaces

The interface catalog is defined in `INTERFACES.md`. At minimum, the public API must cover:

- plugin manifests and compatibility
- application and per-plugin configuration
- event envelopes and payload registration
- storage and migration access
- query and command handlers
- `mcctl` command contributions
- HTTP API contributions
- background jobs
- UI contribution manifests
- authorization and permissions
- health and lifecycle reporting

The source of truth for these contracts should eventually be machine-readable and language-agnostic. CUE is the canonical public contract language, with generated JSON Schema, validation artifacts, and future reference documentation tracked in #3.

The web application is the primary and reference user interface, but it is not
the definition of a view. Workspace snapshots, affordances, setup actions, form
descriptors, and declarative plugin contributions remain transport-neutral. A
future terminal UI must be able to consume those same contracts without importing
web modules or reimplementing plugin semantics; renderers own layout and interaction
appropriate to their medium.

## Isolation guarantees

The architecture should preserve these properties:

1. Starting Mission Control with no optional plugins remains supported.
2. Built-in plugins receive no private capabilities unavailable to third-party plugins.
3. Enabling one plugin does not change unrelated plugin behavior.
4. A plugin import or startup failure is reported by name and does not corrupt core state.
5. Plugin migrations are transactional, namespaced, and recorded independently.
6. Disabling a plugin stops its jobs and hides its contributions without deleting data.
7. Upgrading the core rejects incompatible plugins before applying destructive changes.
8. A plugin cannot write directly to private core or unrelated plugin storage.
9. The same plugin configuration has equivalent meaning across deployment adapters.
10. Public interface compatibility is testable before startup and upgrade.

## Configuration

The detailed source, merge, identity, setup-write, and pre-1.0 schema-evolution
decisions are recorded in
[`docs/configuration-and-schema-evolution.md`](docs/configuration-and-schema-evolution.md).

Mission Control accepts one application-level configuration format with:

- database and state paths
- bind address and public URL
- authentication settings
- enabled plugin identifiers
- per-plugin validated configuration

NixOS modules, Compose files, and the setup wizard are configuration producers. They must not become alternate implementations of application logic. Installer output must pass the same validator used by `mcctl` and `mctrld`.

Non-secret plugin settings and named credential file references are separate inputs. Deployment adapters may materialize credentials using their native secret mechanism, but the application passes only the named runtime path to the owning plugin. Secret values must not be serialized into application configuration, SQLite, process arguments, health output, or logs.

## Deployment adapters

Deployment adapters package and configure the same application for a target environment. An adapter may provide service supervision, filesystem ownership, secrets, network bindings, discovery, updates, and first-boot behavior. It may not fork domain rules, plugin semantics, configuration meaning, or migration behavior.

Initial adapters are:

- NixOS
- OCI and Docker Compose
- Raspberry Pi appliance image and guided first boot

## Repository strategy

This standalone repository owns application code, tests, schemas, packaging metadata, and migrations. Host-specific deployment belongs in separate deployment repositories or adapters that consume a pinned package revision.

Deployment repositories must not duplicate or privately fork application behavior; they consume released or pinned revisions from this repository.
