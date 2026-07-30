# Mission Control public schemas

CUE defines Mission Control's public, language-neutral data contracts; it does not describe plugin implementation code or domain-specific state machines.

The current contracts cover:

- the registration document a plugin presents before Mission Control imports or activates it
- the query core sends when requesting agenda contributions for an explicit horizon
- the immutable agenda contribution a provider returns for aggregation and rendering

CUE definitions are closed by default, so misspelled or undeclared keys fail validation rather than silently expanding a public object.

## Agenda contract

The agenda boundary is deliberately read-only. Providers retain ownership of their domain records, detailed states, recurrence definitions, and transitions. They project current facts into a closed tagged union:

- `initiative` for broad work that may be unscheduled and not directly completable
- `action` for completable work with `anytime`, `due-on`, `due-at`, or `window` timing
- `event` for concrete `all-day` or `timed` occurrences

A query carries an explicit time window and separate flags for unscheduled actions and initiatives. Providers expand only their own recurrence rules into concrete occurrences within that horizon. The aggregate validates and combines immutable values; it does not calculate plugin-specific recurrence or mutate provider state.

User commands are a separate future contract. Agenda entries contain source references, not callbacks, SQL handles, executable payloads, or mutation instructions.

## Runtime artifacts

The canonical CUE definitions and generated Draft 2020-12 JSON Schemas are:

| Contract | CUE definition | Packaged runtime schema |
| --- | --- | --- |
| Plugin registration | `schema/plugin/registration.cue` | `mission_control/schemas/plugin-registration.schema.json` |
| Agenda contribution | `schema/agenda/contribution.cue` | `mission_control/schemas/agenda-contribution.schema.json` |
| Agenda query | `schema/agenda/query.cue` | `mission_control/schemas/agenda-query.schema.json` |

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
  -e '#AgendaQuery' \
  -o mission_control/schemas/agenda-query.schema.json \
  ./schema/agenda
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
- transactions, authorization, and command routing

Generated language bindings may later consume JSON Schema or OpenAPI artifacts. Bindings alone do not make plugins language-neutral; an out-of-process transport will still be required for plugins implemented outside the host runtime.

## References

- https://cuelang.org/docs/concept/schema-definition-use-case/
- https://cuelang.org/docs/tutorial/converting-cue-to-json-schema/
- https://cuelang.org/docs/integration/
