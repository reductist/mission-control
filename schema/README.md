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

## Runtime artifacts

The canonical CUE definitions and generated Draft 2020-12 JSON Schemas are:

| Contract | CUE definition | Packaged runtime schema |
| --- | --- | --- |
| Plugin registration | `schema/plugin/registration.cue` | `mission_control/schemas/plugin-registration.schema.json` |
| Agenda contribution | `schema/agenda/contribution.cue` | `mission_control/schemas/agenda-contribution.schema.json` |
| Agenda query | `schema/agenda/query.cue` | `mission_control/schemas/agenda-query.schema.json` |
| Closed-item contribution | `schema/closed-items/contribution.cue` | `mission_control/schemas/closed-items-contribution.schema.json` |
| Entity detail and activity | `schema/entity-detail/contract.cue` | `mission_control/schemas/entity-detail.schema.json` |
| Command envelope | `schema/command/contract.cue` | `mission_control/schemas/command-envelope.schema.json` |
| Command result | `schema/command/contract.cue` | `mission_control/schemas/command-result.schema.json` |

The generated artifacts are packaged with the Python application and consumed at untrusted runtime boundaries. They must not be edited by hand.

To regenerate them deliberately from `mission-control/`:

```sh
cue def --force --out jsonschema \
  -e '#PluginRegistration' \
  -o mission_control/schemas/plugin-registration.schema.json \
  ./schema/plugin

cue def --force --out jsonschema \
  -e '#AgendaContribution' \
  -o mission_control/schemas/agenda-contribution.schema.json \
  ./schema/agenda

cue def --force --out jsonschema \
  -e '#CommandEnvelope' \
  -o mission_control/schemas/command-envelope.schema.json \
  ./schema/command

cue def --force --out jsonschema \
  -e '#CommandResult' \
  -o mission_control/schemas/command-result.schema.json \
  ./schema/command

cue def --force --out jsonschema \
  -e '#AgendaQuery' \
  -o mission_control/schemas/agenda-query.schema.json \
  ./schema/agenda

cue def --force --out jsonschema \
  -e '#ClosedItemsContribution' \
  -o mission_control/schemas/closed-items-contribution.schema.json \
  ./schema/closed-items

cue def --force --out jsonschema \
  -e '#EntityDetail' \
  -o mission_control/schemas/entity-detail.schema.json \
  ./schema/entity-detail
```

Formatting is not part of the contract; CI compares generated and packaged schemas as decoded JSON values.

## Run locally

Install CUE v0.16.1, then run:

```sh
bash mission-control/scripts/check-schemas.sh
```

The check:

1. generates all runtime JSON Schemas from their canonical CUE definitions
2. fails when any packaged runtime artifact has drifted
3. validates the reference plugin and public examples directly against CUE
4. validates the same documents against generated JSON Schema
5. proves misspelled keys, invalid discriminators, impossible timing shapes, invalid defaults, and invalid value types are rejected through both schema paths
6. exercises planned agenda providers for landscape, maintenance, financial planning, home search, and Ansible automation

Python tests separately exercise the packaged artifacts through runtime parsers and CLI boundaries.

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
