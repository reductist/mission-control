# Mission Control public schemas

CUE defines Mission Control's public, language-neutral data contracts; it does not describe plugin implementation code or domain-specific state machines.

The current contracts cover:

- the registration document a plugin presents before Mission Control imports or activates it
- the query core sends when requesting agenda contributions for an explicit horizon
- the immutable agenda contribution a provider returns for aggregation and rendering
- the immutable closed-item contribution a provider returns for completed/history views
- the entity-focused detail and immutable activity projection composed at read time
- the command envelope a client sends to exactly one authoritative owner
- the structured outcome returned for accepted, rejected, stale, unauthorized, or failed commands
- the renderer-neutral state exchanged during an explicit plugin setup session

CUE definitions are closed by default, so misspelled or undeclared keys fail validation rather than silently expanding a public object.

## Agenda contract

The agenda boundary is deliberately read-only. Providers retain ownership of their domain records, detailed states, recurrence definitions, and transitions. They project current facts into a closed tagged union:

- `initiative` for broad work that may be unscheduled and not directly completable
- `action` for completable work with `anytime`, `due-on`, `due-at`, or `window` timing
- `event` for concrete `all-day` or `timed` occurrences

A query carries an explicit time window and separate flags for unscheduled actions and initiatives. Providers expand only their own recurrence rules into concrete occurrences within that horizon. The aggregate validates and combines immutable values; it does not calculate plugin-specific recurrence or mutate provider state.

Agenda entries contain source references, not callbacks, SQL handles, or executable payloads. An entry may advertise a closed list of state-dependent affordances, each mapping a registered entity capability to a command name. A client turns one advertised affordance into a separate command envelope and supplies the revision it read. Core routes the command by the source plugin identifier to exactly one registered owner.

## Command contract

The command envelope owns generic routing metadata only: a command identity, source target, expected revision, namespaced operation name, and JSON arguments interpreted by the owner. Core authenticates the caller, resolves exactly one owner, and returns a closed structured outcome.

The first implementation routes the browser's core-task state change and Landscape lifecycle operations through this boundary. Registration bounds the maximum capabilities of each plugin-owned entity type, while authoritative command state exposes the currently legal subset. `core/task:set-state` is intentionally non-retryable when the client cannot determine whether a request completed: refresh the projection and submit a new command against its current revision. Durable idempotency records remain follow-up work.

## Closed-item contract

Closed items are projected separately so the default agenda remains focused on active work. A plugin must declare the top-level `closed-items` capability before activation. Its provider decides which entities are currently closed, supplies the opaque revision and display state, and advertises only the affordances legal in that state. Core validates those affordances against registration, aggregates provider snapshots, and never infers that every closed entity is reopenable.

This is a current-state read model, not the immutable event stream or the planned richer entity activity view. Reopening still travels through the ordinary command envelope to the authoritative owner.

## Entity-detail contract

Entity details remain a read model over one stable source reference. A plugin owns
the entity's current title, description, state, revision, display attributes,
affordances, and domain events. Core may compose shared notes into the activity
sequence without copying or mutating plugin state. The provider must declare the
coarse `entity-details` capability, while `activity.read` and `entity.annotate`
remain entity-type capabilities enforced through the registration envelope.
Core-composed note entries additionally carry their `core/annotation` source,
active/inactive state, opaque note revision, and one current
`lifecycle.dismiss` or `lifecycle.reopen` affordance. Plugin-supplied domain events
cannot impersonate those core-owned controls.

## Runtime artifacts

The canonical CUE definitions and generated Draft 2020-12 JSON Schemas are:

| Contract | CUE definition | Packaged runtime schema |
| --- | --- | --- |
| Plugin registration | `schema/plugin/registration.cue` | `mission_control/schemas/plugin-registration.schema.json` |
| Plugin configuration defaults | `schema/plugin/configuration.cue` | `mission_control/schemas/plugin-config-defaults.schema.json` |
| Plugin configuration presentation | `schema/plugin/configuration.cue` | `mission_control/schemas/plugin-config-presentation.schema.json` |
| Plugin setup state | `schema/setup/contract.cue` | `mission_control/schemas/setup-state.schema.json` |
| Plugin setup transition | `schema/setup/contract.cue` | `mission_control/schemas/setup-transition.schema.json` |
| Application configuration | `schema/config/application.cue` | `mission_control/schemas/application-config.schema.json` |
| Agenda contribution | `schema/agenda/contribution.cue` | `mission_control/schemas/agenda-contribution.schema.json` |
| Attribution catalog | `schema/attribution/contract.cue` | `mission_control/schemas/attribution-catalog.schema.json` |
| Agenda query | `schema/agenda/query.cue` | `mission_control/schemas/agenda-query.schema.json` |
| Closed-item contribution | `schema/closed-items/contribution.cue` | `mission_control/schemas/closed-items-contribution.schema.json` |
| Entity detail and activity | `schema/entity-detail/contract.cue` | `mission_control/schemas/entity-detail.schema.json` |
| Command envelope | `schema/command/contract.cue` | `mission_control/schemas/command-envelope.schema.json` |
| Command result | `schema/command/contract.cue` | `mission_control/schemas/command-result.schema.json` |

The generated artifacts are packaged with the Python application and consumed
at untrusted runtime boundaries. They must not be edited by hand. Run
`scripts/check-schemas.sh` to regenerate them into temporary files, apply the
CUE-owned exporter overlays, and compare decoded JSON with the packaged copies.
The same check validates direct CUE fixtures and generated-schema fixtures.

## Run locally

Install CUE v0.16.1, then run:

```sh
bash mission-control/scripts/check-schemas.sh
```

The check:

1. generates all runtime JSON Schemas from their canonical CUE definitions
2. fails when any packaged runtime artifact has drifted
3. validates the reference plugin, capability calls, and public examples directly against CUE
4. validates the same documents against generated JSON Schema
5. proves misspelled keys, invalid discriminators, impossible timing shapes, invalid defaults, and invalid value types are rejected through both schema paths
6. exercises planned agenda providers for landscape, maintenance, financial planning, home search, and Ansible automation

Python tests separately exercise the packaged artifacts through runtime parsers and CLI boundaries.

`schema/plugin/runtime.cue` defines the shared call/result envelopes and the
runtime-description, command-state, health, and job documents. Capability
payloads such as Agenda, closed items, entity details, and command results keep
their own focused schemas; the adapter composes them rather than creating one
giant union that every plugin author must understand.

Setup uses the same validated call envelope but a separate manifest entry point
and `mission-control.setup-state/v1` output. Its draft contains only non-secret
settings and opaque credential handles. Core owns session revision checks and
final configuration validation; plugin setup code owns provider-specific test,
discovery, selection, and remediation. The document contains no renderer or
deployment-platform implementation fields.

Bundled plugins own their CUE configuration definitions and package generated
JSON Schema, explicit-default, and renderer-neutral presentation artifacts.
The manifest contains resource references rather than a second argument DSL.
Google Calendar defines and continuously validates its exact
registration/capability envelope, explicit configuration,
evergreen Google-shaped Calendar/Tasks fixture, and one-way mapping conformance
cases under `schema/google/`. Live Google inputs remain recursively open because
the upstream APIs may add fields independently; mapped, filtered, and rejected
outcomes are closed and the production mapper must match their golden fixtures.

### Semantic configuration references

A plugin may annotate a string field in its generated configuration-schema
overlay with `x-mission-control-reference`. The supported values are
`credential` and `workspace-principal`. Core resolves credential names against
that plugin's configured credential references and principal IDs against the
workspace catalog before any implementation import or migration. A credential
annotation requires the registration's `credentials` permission. An annotation
on a non-string schema, an unknown reference kind, or a missing catalog entry is
a configuration error. Union annotations apply only to branches that validate
the configured value.

Plugin conformance accepts `--workspace WORKSPACE.json` when settings contain
workspace-principal references. The file contains the ordinary workspace object
with `principals` and `accents`; it is test input, not another application
configuration format. Plugins continue to receive only their already-validated
settings and credential paths.

## Boundaries

CUE answers **what exchanged data is valid**. Runtime behavior remains defined by prose and executable contract tests, including:

- lifecycle ordering, timeouts, retries, and cleanup
- provider-owned recurrence expansion
- temporal ordering such as an event ending after it starts
- provider/source ownership and duplicate-identity detection
- registration envelopes, current affordances, and command routing
- transactions and authorization

Generated language bindings may later consume JSON Schema or OpenAPI artifacts. Bindings alone do not make plugins language-neutral; an out-of-process transport will still be required for plugins implemented outside the host runtime.

## References

- https://cuelang.org/docs/concept/schema-definition-use-case/
- https://cuelang.org/docs/tutorial/converting-cue-to-json-schema/
- https://cuelang.org/docs/integration/
