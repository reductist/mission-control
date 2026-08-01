# Mission Control

Mission Control is a portable, self-hosted source of truth for projects, tasks, decisions, and durable operational history.

A NixOS host is the first deployment target and proving ground, not an application dependency. Mission Control remains usable independently of NixOS and any particular host configuration.

## Naming

| Surface | Name |
| --- | --- |
| Product | Mission Control |
| Application/package | `mission-control` |
| Python package | `mission_control` |
| Administrative CLI | `mcctl` |
| Long-running daemon | `mctrld` |
| systemd unit | `mission-control.service` |
| NixOS module | `services.mission-control` |

`mcctl` is the canonical administrative command. The shorter `mc` name is deliberately avoided because it is already used by widely deployed tools. `mctrld` is the application server and long-running daemon; the former `mcd` name is not used because it collides with Mtools.

## Implementation philosophy

Every subsystem must earn its existence. Mission Control starts with the smallest implementation that satisfies a demonstrated requirement, preserves the documented boundaries, and can be tested end to end. Frameworks, abstractions, and infrastructure are introduced when a concrete limitation justifies them—not because they may be useful someday.

The application favors a functional core and imperative shell: external data is parsed into precise immutable values, pure functions build projections and state snapshots, and filesystem, SQLite, process, network, and console effects remain visible at the edges. This is a design preference rather than a prohibition on ordinary readable Python.

## Current thin slice

The executable implementation provides:

- a small Python application core
- the canonical `mcctl` executable
- the minimal `mctrld` HTTP server and browser shell
- ordered SQLite migrations
- task creation, updates, listing, and immutable event history
- browser task creation, completion, and reopening through the authoritative task repository
- a responsive Overview and synthetic House demo workspace
- an explicitly selected Landscape/Yard provider with plugin-owned SQLite state, immutable history, and read-only agenda projections
- deterministic Markdown task rendering
- pre-activation plugin registration parsing against a packaged CUE-derived JSON Schema
- frozen registration domain values, enum-backed finite vocabularies, and an immutable discovery catalog
- explicit available, rejected, and duplicate-ID conflict catalog outcomes
- a CUE-defined read-only agenda query and contribution boundary
- CUE-defined command envelope and structured outcome contracts
- single-owner command routing with optimistic revision checks
- frozen initiative, action, event, and timing variants
- deterministic cross-provider agenda aggregation
- core tasks projected through the same agenda contract intended for plugins
- Rich-backed opt-in human tables with stable JSON remaining the default
- `version`, `init`, and `doctor` commands
- executable migration, repository, event-invariant, rendering, plugin-contract, discovery, agenda, presentation, CLI, and HTTP tests

From the repository root:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'

mcctl --database ./mission-control.db init
mcctl --database ./mission-control.db doctor
mcctl --database ./mission-control.db task add "Review the thin slice"
mcctl --database ./mission-control.db task list
mcctl --database ./mission-control.db task list --format table
mcctl --database ./mission-control.db task update TASK_ID --state ready
mcctl --database ./mission-control.db task history TASK_ID
mcctl --database ./mission-control.db agenda list
mcctl --database ./mission-control.db agenda list --plugin landscape
mcctl --database ./mission-control.db agenda list --format table
mcctl --database ./mission-control.db render markdown
mcctl plugin validate ./plugins/reference/registration.json
mcctl plugin list --root ./plugins
mcctl plugin list --root ./plugins --format table
pytest
```

`MC_DATABASE` may be used instead of passing `--database` to every command. `mcctl render markdown --output tasks.md` writes the rendered document directly to a file. Plugin registration validation and discovery do not initialize the database or import plugin implementation code.

### MVP browser demo

Run the demo against a disposable database:

```sh
mctrld --database ./mission-control-demo.db --demo --plugin landscape
```

Then open `http://127.0.0.1:8000`. House content is a packaged synthetic fixture. On first activation, Landscape imports its validated equipment-access seed into plugin-owned, namespaced SQLite tables; later starts read the durable state and never overwrite it from the package. Yard and Overview receive immutable agenda projections from that state. Core task completion and reopening already use the owner-routed command endpoint. Landscape's repository has the corresponding persistence primitive, while public Landscape command registration remains the next slice.

#### Upgrading an existing Yard demo

An existing demo database may retain the earlier core-owned `Measure the driveway drop-off for equipment access` and `Review low-voltage shade lighting options` tasks. Mission Control does not delete or reclassify stored tasks by title. Complete those two legacy demo tasks before enabling `--plugin landscape` so they do not appear as duplicate active work. Use a fresh database only when the old demo state and history are confirmed disposable.

The current MVP has no user authentication. It binds to loopback by default. Keep it on loopback or reach it through an SSH tunnel or Tailscale Serve; do not expose it directly to an untrusted network. Authentication and production deployment are separate follow-up slices.

## Agenda ownership boundary

The agenda is an aggregated read model, not a shared mutable task database. Core tasks and future plugins project immutable values through one public contract:

```text
core/plugin domain state
        |
        | pure projection
        v
initiative | action | event
        |
        | validation and deterministic aggregation
        v
read-only JSON, CLI table, and web views
```

Providers retain authoritative ownership of their records, detailed state machines, recurrence rules, and transitions. The aggregate does not calculate plugin-specific recurrence, copy records into a second source of truth, or write directly to owner tables.

Unscheduled work is explicit rather than represented by invented or nullable dates. Actions use `anytime`, `due-on`, `due-at`, or `window` timing; events use `all-day` or `timed` timing. Providers receiving an agenda query expand their own recurring definitions into concrete occurrences within that horizon and may separately include initiatives or unscheduled actions.

The CLI and browser shell project core tasks plus explicitly selected provider state through the same pure aggregator. Landscape validates registration and seed data before importing its implementation or touching SQLite, then applies independently recorded migrations and performs an idempotent first-run import. General third-party plugin activation and transport are not implemented yet. User operations such as complete, defer, approve, or run follow a separate command path back to the authoritative owner; renderers remain incapable of mutation.

## CLI presentation boundary

List commands default to deterministic JSON so scripts and other programs receive a stable machine-readable format. Passing `--format table` opts into Rich-backed terminal presentation.

Rich is confined to the imperative CLI shell. Presentation functions construct tables from existing domain values but do not read files, access SQLite, mutate state, or print by themselves. The CLI owns stdout and stderr consoles and performs the final rendering effect.

Rich may later provide trees for nested configuration and plugin argument definitions, terminal Markdown previews, and progress displays for long-running backup, restore, migration, installation, synchronization, health-check, and automation commands. It does not define public contracts, replace CUE or JSON Schema, serialize JSON, generate durable Markdown artifacts, implement lifecycle decisions, or render the web UI. Textual remains deferred until a concrete full-screen interactive workflow requires it.

## Product layers

```text
./
├── mission_control/  Python package, bundled providers, and runtime resources
├── plugins/          reference and filesystem-discovered plugin assets
├── schema/           canonical language-neutral CUE contracts
├── scripts/          schema and repository validation
├── tests/            core, contract, integration, and CLI tests
└── docs/             architecture and operator documentation

deploy/
├── nixos/         declarative NixOS deployment adapter
├── container/     OCI image and Compose deployment adapter
└── raspberry-pi/  appliance image and first-boot deployment adapter
```

This standalone repository owns application code, schemas, tests, plugins, packaging, and product planning. Deployment repositories consume released or pinned revisions and own only their host-specific integration.

## Core model

- SQLite is the default source of truth.
- Schema changes use ordered, explicit migrations.
- Landscape migrations and tables are namespaced and recorded independently from core migrations.
- Every material task mutation appends an immutable event.
- The `tasks` table is the current projection used for efficient reads.
- Supported task states are `backlog`, `ready`, `in-progress`, and `done`.
- Task metadata includes `blocked`, `waiting_on`, and `review_after`.
- Core behavior must not depend on any plugin being installed.

## Plugin model

Plugins provide capabilities such as tasks, wiki, dashboards, GitHub, calendars, Docker, Home Assistant, notes, landscape planning, home maintenance, financial planning, property search, or Ansible automation. Built-in and third-party plugins use the same documented public interface and receive no private extension path.

The core owns stable extension contracts. Each plugin owns its migrations, configuration, permissions, events, jobs, API/CLI/UI contributions, health reporting, and tests. A plugin must be installable, disabled, upgraded, and removed without modifying unrelated core or plugin code. Plugin failures must not corrupt the core event log or prevent the application from starting in a recoverable mode.

The first language-agnostic CUE contract defines plugin registration data and generates the JSON Schema packaged with the application. Untyped JSON is accepted only at parser and filesystem boundaries, then converted into frozen `PluginRegistration` values. Discovery builds a new immutable catalog snapshot on each scan; malformed registrations are rejected explicitly and duplicate IDs become conflicts rather than allowing one source to win silently. No plugin implementation code is imported during this process.

The agenda query and contribution contracts keep provider snapshots read-only; plugin-specific state and recurrence remain inside the owner. Landscape now demonstrates independently migrated plugin state, idempotent packaged-data import, immutable plugin history, and projection from the authoritative repository. The experimental command contracts prove single-owner routing and stale-revision rejection for core-task state changes. Landscape handler registration, durable command idempotency, richer authorization, and owner-scoped transactions remain tracked in #4. Broader application, event, health, and lifecycle contracts remain tracked in #3.

## CLI direction

Implemented now:

```text
mcctl version
mcctl init
mcctl doctor
mcctl task add
mcctl task update
mcctl task list [--format json|table]
mcctl task history
mcctl agenda list [--format json|table] [--plugin landscape]
mcctl render markdown
mcctl plugin validate
mcctl plugin list [--format json|table]
mctrld [--database PATH] [--host HOST] [--port PORT] [--demo] [--plugin landscape]
```

Planned additions:

```text
mcctl plugin enable
mcctl plugin disable
mcctl backup create
```

## Deployment direction

The same application should support:

- a declarative NixOS service
- an OCI container and Docker Compose
- a Raspberry Pi appliance image
- a first-boot browser wizard for admin setup and plugin selection

These are deployment adapters. They produce or consume the same validated application configuration and must not implement alternate application behavior.

## Delivery sequence

1. Portable core, SQLite migrations, `mcctl`, tests, and Markdown rendering.
2. Stable public plugin contracts plus a reference plugin and contract test harness.
3. Minimal `mctrld` server and browser demo; authentication and production hardening remain follow-up work.
4. Declarative NixOS deployment adapter.
5. OCI/Compose deployment adapter.
6. Guided first-boot setup and Raspberry Pi appliance image.
7. Backup/restore automation and migration from GitHub tracking data.
8. Machine-readable public schemas and generated interface documentation as tracked in #3.

See `ARCHITECTURE.md`, `INTERFACES.md`, and `TESTING.md` for the boundaries this implementation must preserve.
