# Mission Control

Mission Control gives you one place to see and act on work that lives in other
tools. It currently brings together local tasks, Google Calendar and Google
Tasks, and a household Landscape plugin.

Most dashboard projects display a collection of widgets. Mission Control takes
a different approach:

- **Source systems remain authoritative.** A calendar event stays a calendar
  event. A plugin keeps its own data, rules, history, and available actions.
- **The interface is consistent across tools.** Mission Control turns data from
  each source into common schedule, detail, history, and action views.
- **Actions go back to the owner.** The dashboard does not maintain a second,
  conflicting copy of an item. Commands are validated and routed to the plugin
  that owns it.
- **Integrations are isolated.** Each plugin has its own configuration,
  credentials, database migrations, health status, and background jobs. A
  failing integration should not corrupt or block unrelated parts of the app.
- **It is self-hosted and portable.** The application uses the same validated
  configuration whether it runs directly, on NixOS, or through a future
  container or appliance package.

The goal is not to replace every specialized tool. It is to reduce the time and
attention needed to keep track of them.

## Why I built this

As a neurodivergent developer, I have limited pools of attention, patience, and
focus. Juggling an endless collection of apps is a constant drain on all three.
Even when each app is useful on its own, remembering where everything lives and
repeatedly switching context carries a real cost. Mission Control is meant to
reduce that cost.

I have also become frustrated by service providers increasingly siloing my data
and artifacts in their private gardens. Too often, this is not done to provide
value to me as the user, but to make it difficult to migrate to a competitor. I
find this untenable. The systems I use should preserve my access to my own data,
along with the context and portability needed to move it elsewhere.

I use Ansible extensively in my day job and appreciate its modularity and
flexibility. However, the interfaces between plays, plugins, and modules are
largely stringly typed. Making their state robust and validating it correctly
can be painfully manual and repetitive.

Mission Control borrows that modular approach but uses CUE to define robust,
typed data schemas for plugin interfaces. The application uses those schemas to
validate that registered plugins meet their contracts. The same well-defined,
machine-readable interfaces should make plugins easier to write, test, and
generate—especially with AI, which can use the contracts to guide development
instead of relying on undocumented conventions or guesswork.

## Current status

Mission Control is pre-release software. The current version includes:

- a responsive web interface with Dashboard, Schedule, History, and entity
  detail views
- local task creation, state changes, notes, and immutable activity history
- a read-only Google integration for Calendar events, appointments, Tasks, and
  migrated Reminders
- support for multiple isolated Google connections
- background refresh, cached data, connection-level health, and safe handling
  of revoked credentials
- guided Google setup through a private, loopback-only setup process
- a Landscape plugin that demonstrates plugin-owned data, actions, migrations,
  history, and agenda contributions
- a configuration-backed Household plugin for maintenance cases, contractor
  contacts, related task IDs, reference links, investigation notes, and
  scheduled visits
- a command-line interface for administration, configuration inspection, and
  machine-readable queries
- SQLite storage with ordered migrations
- CUE-defined public contracts and generated JSON Schema

The web application does not yet provide user authentication. It binds to
loopback by default. Use an SSH tunnel or access-controlled Tailscale Serve for
remote access, and do not expose it directly to an untrusted network.

## Quick start

Mission Control requires Python 3.11 or later.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
```

Create `mission-control-demo.toml`:

```toml
schema_version = "mission-control.config/v2"
demo = true

[database]
path = "mission-control-demo.db"

[plugins.google-calendar]
enabled = true

[plugins.google-calendar.settings.connections.demo]
label = "Google demo"
mode = "demo"
demo_anchor_date = "2026-08-14"

[plugins.google-calendar.settings.connections.demo.calendars]
mode = "defaults"

[plugins.google-calendar.settings.connections.demo.tasks]
mode = "all"

[plugins.landscape]
enabled = true

[plugins.home-search]
enabled = true
```

Start the server:

```sh
mctrld --config ./mission-control-demo.toml
```

Open <http://127.0.0.1:8000>. The demo uses synthetic Google and household
data and does not contact Google.

To install the existing private HTTPS deployment as an online-only Android app,
follow [`docs/android-pwa.md`](docs/android-pwa.md).

To connect a real Google account, follow
[`docs/google-integration.md`](docs/google-integration.md). OAuth credentials
are stored separately from application configuration.

To record household maintenance cases and scheduled contractor visits, see
[`docs/household.md`](docs/household.md).

To import sourced house-purchase candidates without enabling a scraper or daily
watcher, follow [`docs/home-search.md`](docs/home-search.md).

## Command-line tools

`mcctl` is the administrative command. `mctrld` runs the application server.

Common commands:

```sh
mcctl version
mcctl --database ./mission-control.db init
mcctl --database ./mission-control.db doctor
mcctl --database ./mission-control.db task add "Review Mission Control"
mcctl --database ./mission-control.db task list
mcctl --database ./mission-control.db agenda list

mcctl config validate ./mission-control.toml
mcctl config effective ./mission-control.toml
mcctl config explain ./mission-control.toml /plugins/google-calendar

mcctl plugin list --root ./plugins
mcctl plugin validate ./plugins/reference/registration.json
mcctl plugin conformance ./plugins/reference/registration.json

mkdir -p ./config.d
mcctl --config ./mission-control.toml --config-dir ./config.d \
  setup google-calendar --credential-dir ./mission-control.credentials
```

List commands return stable JSON by default. Use `--format table` for
human-readable terminal output where supported.

## How the plugin model works

Mission Control combines data without claiming ownership of it.

```text
plugin or core data
        |
        | validated projection
        v
shared workspace and schedule views
        |
        | validated command
        v
authoritative owner
```

A plugin owns its domain data, rules, migrations, configuration, credentials,
jobs, and actions. It publishes validated read models for shared views and
handles commands for the entities it owns. Built-in plugins use the same public
interfaces as external plugins.

This design avoids two common dashboard problems: integrations cannot silently
overwrite each other's data, and the dashboard does not become a second source
of truth that drifts from the original system.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for component responsibilities and
[`INTERFACES.md`](INTERFACES.md) for the public contracts.

## Configuration

Mission Control uses one TOML application configuration. An optional base file
can be combined with lexically ordered `*.toml` fragments. The same merge,
validation, defaults, and credential rules apply to direct and packaged
deployments.

Configuration contains credential file references, never secret values. Use
`mcctl config validate`, `effective`, and `explain` to inspect the result before
starting the application.

The full configuration design is documented in
[`docs/configuration-and-schema-evolution.md`](docs/configuration-and-schema-evolution.md).

## Repository layout

```text
mission_control/  application code and built-in plugins
plugins/          reference and filesystem-discovered plugin assets
schema/           CUE contracts
tests/            unit, contract, integration, CLI, and HTTP tests
scripts/          schema and repository checks
deploy/           NixOS, container, and appliance adapters
docs/             design decisions and operator documentation
```

This repository owns the application, public contracts, tests, packaging, and
product documentation. Host repositories only select a version and provide
host-specific service, storage, network, and secret configuration.

## Development

Run the main checks from the repository root:

```sh
python -m pytest
python -m ruff check .
bash scripts/check-schemas.sh
nix flake check
```

Changes should be small enough to review and test end to end. New abstractions
need a demonstrated use case. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`TESTING.md`](TESTING.md) for details.

## Roadmap

The next major step is to replace the prototype dashboard response with a
versioned workspace model and generic plugin contributions. Later work includes
typed creation forms, renderer-independent UI descriptions, file attachments,
tags, saved views, and a richer task editor.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the ordered plan.
