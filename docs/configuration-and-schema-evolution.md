# Configuration, integration identity, and schema evolution

Status: accepted pre-1.0 architecture decision

## Context

Mission Control is an integration shell. Its core value depends on plugins being
configurable without allowing deployment adapters, the browser, or one plugin to
invent alternate meanings for configuration and identity.

The first Google Calendar showcase proved the agenda, entity-detail, job, health,
credential, cache, and mapping boundaries. At the time, it exposed three missing
pieces:

- daemon flags and per-plugin JSON files were not yet one application configuration;
- `plugin_id` was being used in presentation as if it identified a Google account,
  calendar, or person; and
- closed CUE document shapes had no precise pre-1.0 evolution rule.

The first four delivery slices below established canonical configuration, one
CUE-owned plugin configuration boundary, and transport-neutral JSON capability
calls. Typed attribution is the current prerequisite for browser setup, multiple
Google accounts, and owner/source filters.

## Decision

### One canonical application configuration

Mission Control will define `mission-control.config/v2` in CUE and generate the
runtime JSON Schema from it. Direct execution, NixOS, containers, appliances, and
the setup wizard are configuration producers; none may define different merge,
validation, default, credential, or plugin semantics.

NixOS is a convenient current release and integration-test target, not the
reference application environment. Core code and public contracts may not assume
Nix, the Nix store, systemd, immutable hosts, or NixOS credential mechanics.
Those belong only to deployment adapters that translate into the portable
application document and credential-file boundary.

The operator model is:

1. application defaults;
2. one optional TOML base file;
3. zero or more lexically ordered TOML fragments;
4. a deliberately small set of command-line overrides.

Maps deep-merge. Scalars replace earlier scalars. Arrays replace wholesale rather
than append. A table/scalar or otherwise incompatible type collision fails and
reports both sources. Every effective leaf retains its full source chain so
`mcctl config explain` can show why it has its value. Normal rendering is redacted.

Plugin blocks are keyed by stable plugin ID and contain `enabled`, plugin-owned
settings, and named credential references. Disabled blocks remain preserved and
representable rather than being deleted. Credential values never appear in
configuration; adapters resolve references through files or their native secret
mechanism.

The initial effective snapshot is immutable and startup-only. Mission Control
validates the complete outer configuration, every enabled plugin's configuration,
credential requirements, compatibility, and resources before importing plugin
implementation code, opening the application database, or applying migrations.
An enabled block for an unavailable plugin is an error. Disabled plugin blocks are
preserved opaquely and receive outer-shape validation only, so uninstalling or
temporarily disabling a plugin does not make its retained settings prevent core
startup. Enabling a block always requires its plugin schema and full validation.
Reload is deferred until a real setting has earned explicit prepare/commit/abort
semantics.

### Setup writes are explicit and bounded

The setup wizard consumes and produces the same canonical configuration. It owns
at most one explicitly configured managed fragment and writes it atomically. It
does not edit operator-owned base files or fragments. In a declaratively managed
deployment it may validate and export a candidate without being allowed to apply
it.

The normal web server is currently unauthenticated and therefore must not expose
configuration or credential writes. The first writable wizard runs as a separate
loopback-only `mcctl setup` bootstrap process protected by a one-time token. It
returns `restart_required` after a successful commit; it does not pretend the
startup-only runtime supports hot reload.

Static CUE fields and form hints are not treated as a setup protocol. A plugin that
supports guided setup declares a versioned JSON setup capability with typed
actions such as `validate`, `authorize`, `discover`, and `test`. Core owns setup
sessions, draft configuration, action routing, redacted rendering, and commit;
the plugin owns provider-specific authorization, discovery, and remediation.
Responses are data rendered by core, never arbitrary plugin JavaScript.
The web wizard is the reference renderer for those documents; the same setup
actions remain usable by `mcctl` or a future terminal UI.

Credential handles are scoped by plugin ID, connection ID, and credential name.
Configuration contains only the handle/reference. In a directly managed install,
the bootstrap process stores newly acquired credentials atomically in a dedicated
mode-0700 managed directory with mode-0600 credential files and returns only the
handle to the browser. In a declarative deployment, setup validates or exports the
required references and instructions but does not write secrets or operator-owned
configuration.

### Keep authoritative ownership separate from integration attribution

The identities have distinct meanings:

- **Plugin ID** identifies one authoritative implementation and command owner,
  such as `google-calendar` or `landscape`. Integration IDs use a flat
  `vendor-capability` convention (`google-calendar`, `google-photos`) rather
  than path-like or dotted names; the same ID remains safe in configuration,
  command routing, URLs, package metadata, and database namespaces.
- **Connection ID** is a stable plugin-owned configuration key for one external
  account, workspace, controller, or endpoint.
- **Collection ID** identifies a collection within a connection, such as a calendar,
  task list, repository, or channel.
- **Principal ID** identifies a person or group in the core-owned workspace catalog
  so the same principal can group entries from Google, Tasks, and future plugins.
  It is not inferred from titles, email-looking labels, organizers, or attendees.

Source references continue to route authoritative reads and commands by plugin.
Their `entity_id` is unique within the plugin across every connection; Google must
derive it from connection, collection, and upstream entity identity. Connection,
collection, and principal attribution are separate typed read metadata. A contribution
may name zero or more principals because shared ownership is real; each principal
reference points to the workspace catalog. Connection IDs are scoped by plugin,
and collection IDs are scoped by plugin plus connection, so filter keys always include
that scope. Plugin configuration stores principal IDs, not duplicate person
records. Agenda output references are validated against the workspace catalog at
the provider read boundary. Plugin-configuration principal references must also be
validated before import or database open, but static JSON Schema cannot join a
plugin document to the workspace catalog by itself. The Google-connection slice
must therefore add a generic typed-reference annotation to configuration bundles
or an equivalent whole-document semantic validator; this guarantee must not be
implemented as a Google-specific core check. Color is a workspace
presentation preference keyed to typed identity, not identity itself, and every
view retains a textual owner/source indication.

Google Calendar will initially own a map of connections beneath the single authoritative
`google-calendar` plugin. Core-level plugin instances are deliberately deferred. They become
justified only when another plugin requires core-managed independent lifecycle,
migrations, health, or command ownership for multiple instances. This promotion
rule avoids forcing instance identity through every source-bearing contract before
there is a second use case.

### Closed document versions are immutable

CUE definitions are closed public documents, so a reader compiled with an older
schema rejects newly added fields even when those fields are optional to a newer
reader. Mission Control therefore treats every published closed document shape as
immutable.

Any field addition, removal, rename, type change, discriminator change, constraint
change, or semantic change creates a new `schema_version`. `plugin_api` expresses
host/runtime compatibility and is not used to negotiate an exchanged document's
shape.

Before 1.0, the runtime supports only the current document version and rejects an
older or newer version explicitly. We will make deliberate coordinated transitions
to corrected contracts and migrate persisted application data where necessary.
We will not add dual readers, automatic up-converters, or compatibility shims for
external consumers that do not exist.

When a real third-party ecosystem requires a compatibility window, version dispatch
will occur at the boundary: validate by declared version, parse into one current
internal model, and serialize deliberately for a negotiated version. Compatibility
adapters will have an explicit removal release; version conditionals may not leak
into plugin domains, aggregation, or renderers.

### Optimize the public boundary for plugin authors

The lifecycle proved useful isolation, but its first implementation exposed two
authoring problems:

- manifest `arguments` duplicate Google's CUE configuration definition; and
- Python plugins import core domain classes and return in-process objects.

Plugin registration v2 has removed the argument DSL. A plugin defines its
configuration once in CUE and packages generated validation, static-default, and
presentation-metadata artifacts. The manifest names and version-binds those
resources. Runtime and CUE parity fixtures must produce the same effective values
and failures; a CUE feature is not allowed in a public plugin configuration until
the packaged runtime evaluator preserves its semantics. JSON Schema validation
alone does not apply CUE defaults.

Capability calls exchange versioned JSON documents. Core owns validation and
conversion into internal immutable values. A small public Python adapter may make
those calls convenient, but a plugin must not import core aggregators, repositories,
renderers, or private domain types. This keeps the authoring context to the plugin
manifest, the relevant CUE contracts, the plugin's own domain, and the conformance
suite.

The first runtime remains in-process Python to avoid adding transport and process
supervision before the contract is proven. JSON documents keep the exchanged
schemas portable, but a future process boundary must explicitly preserve command
transaction semantics rather than being assumed free. Built-ins receive no
additional calls or context.

Plugins retain the current core-owned, namespaced SQLite transaction boundary.
The public adapter gives a plugin its own storage namespace, so a plugin can
atomically update its domain rows and its own namespaced event rows. Plugins do
not receive private core repositories, and cross-plugin foreign keys remain
prohibited. A core event-envelope writer is still planned; the adapter must not
claim that service until its transaction contract exists. Separate databases are
deferred unless a concrete process-isolation design supplies an outbox or
another proven atomic commit protocol.

## Delivery sequence

Each item is one independently reviewable pull request unless implementation
evidence shows it should be split further.

1. **Complete:** record this decision and the cross-PR acceptance matrix.
2. **Complete:** implement canonical CUE configuration, TOML loading/merge provenance,
   redaction, and `mcctl config validate|effective|explain` for issue #28.
3. **Complete:** introduce one CUE-owned plugin configuration schema and generated runtime
   validation/default/form artifacts. Remove the duplicate manifest argument DSL;
   validate enabled plugins before import or migrations.
4. **Complete:** introduce versioned JSON capability calls, a small public adapter, and a
   conformance command/reference plugin. Preserve the existing namespaced shared
   transaction boundary; built-ins use the same adapter.
5. **Complete:** introduce the next agenda version with scoped connection/collection/principal
   attribution, independent of presentation colors and authoritative `SourceRef`.
6. **Complete:** add Google-owned multiple connections, explicit calendar/task enablement and
   selection policies, partitioned cache/sync, attribution mapping, and a versioned
   connection-health projection whose aggregate defines plugin health.
7. Add the generic setup-action capability and contract-driven loopback wizard:
   credential acquisition/reference, test, discovery, selection, principal
   assignment, review, validation, atomic managed fragment write, and restart.
8. Make direct and NixOS adapters consume the same configuration fixtures, deploy
   feature parity to the canonical service, and remove the separate port-8001
   showcase service.
9. Define a versioned workspace snapshot and generic dashboard contributions;
   remove raw task duplication and hard-coded House/Yard aggregation from core.
10. Move Tasks through the public plugin lifecycle and add a typed creation/form
   contract before enriching task creation.
11. Define declarative UI contributions and extract or retire prototype-specific
    navigation and renderers. Contributions describe transport-neutral view data,
    affordances, and forms rather than HTML or browser code, preserving a future
    TUI over the same contracts.
12. Review UX mockups using real typed data, then implement compact schedule filters
    and the higher-level dashboard.
13. Add artifact storage/link contracts and secure image/document upload.
14. Add tags, saved-view predicates, and the rich task composer. Views reference
    normalized metadata; plugin entities do not store UI view IDs.

## Acceptance matrix

Every applicable contract/runtime PR exercises:

- core only;
- Google with zero, one, and two connections;
- Google plus Landscape;
- an invalid plugin and an incompatible plugin;
- one failed Google connection without loss of another connection or plugin;
- direct and NixOS configuration from equivalent fixtures;
- current document versions and explicit rejection of unsupported versions; and
- schema generation that leaves the working tree clean.

Configuration failures must create no database, import no plugin implementation,
and apply no migrations. Connection revocation may clear only that connection's
private cache. Disable preserves plugin state. The browser cannot gain access to
credential values through configuration, API responses, logs, or generated files.

A reference plugin must be implementable without importing private Mission Control
modules. The conformance suite receives only packaged schemas and the public adapter,
and built-in plugins must pass that exact suite.

## Consequences

The pre-1.0 break is larger than incrementally extending the current shapes, but it
leaves one honest contract instead of permanent transitional complexity. The
configuration and attribution work precedes visual polish so the calendar, future
dashboard, attachments, and saved views consume stable identities rather than
provider-specific strings.

Google multi-account support remains plugin-owned, keeping core routing and existing
cross-plugin references small. If another integration demonstrates the need for
generic instances, the decision will be revisited with two concrete domains and a
known lifecycle requirement.
