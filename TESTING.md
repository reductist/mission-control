# Mission Control testing strategy

Tests are part of the architecture. They must continuously prove that the core remains portable, that built-in and third-party plugins use the same public interfaces, and that plugins remain isolated from one another.

## Test layers

### Unit tests

Cover domain rules, event creation, projection updates, configuration validation, Markdown rendering, migration planning, manifest parsing, and compatibility evaluation without loading optional plugins.

### Database invariant tests

Run against a temporary SQLite database and verify:

- migrations apply in order and are repeatable
- immutable events cannot be updated or deleted
- failed mutations do not leave partial projections or events
- projection rebuilds produce the same state from the event history
- foreign keys and strict-table constraints are active
- plugin migrations cannot modify core or unrelated plugin storage
- plugin migration records remain independently queryable

### Public interface schema tests

The CUE contracts and generated schemas define the machine-readable test targets. As #3 expands those interfaces, CI must continue to verify:

- all manifests and configuration fixtures validate
- incompatible interface ranges fail before runtime import
- generated JSON Schema and OpenAPI artifacts are current
- generated output is reproducible
- runtime validators and generated documentation share the same source definitions
- built-in and reference plugins validate through the same path

### Plugin contract suite

Every plugin, including built-in plugins, runs the same reusable contract tests. The harness verifies:

- metadata and compatibility declarations are valid
- manifest inspection does not import runtime code
- configuration is validated before startup
- migrations are namespaced, transactional, and independently recorded
- enable, disable, restart, and upgrade lifecycle operations are deterministic
- registered events use valid namespaced schemas
- CLI, API, job, UI, permission, and health contributions conform to public contracts
- plugin failures identify the plugin and preserve core availability
- disabling a plugin does not delete its data
- no plugin writes to private core or another plugin's tables
- no plugin imports private core implementation modules
- no built-in plugin receives capabilities unavailable to the reference plugin

A minimal reference plugin should exist solely to exercise the complete extension surface.

### Isolation matrix

CI should exercise representative combinations:

```text
core only
core + built-in plugin A
core + reference plugin
core + plugin A
core + plugin B
core + plugins A and B
core + one intentionally failing plugin
core + one incompatible plugin
core upgrade + compatible plugin
core upgrade + incompatible plugin
```

For each combination, the suite compares core behavior and unrelated plugin outputs against their standalone baselines. This catches accidental coupling and regressions introduced through global registries, shared configuration, migrations, event registration, authorization, jobs, API routing, CLI composition, or UI composition.

The intentionally failing plugin should support failure injection during discovery, validation, migration planning, migration execution, import, initialization, job startup, request handling, and shutdown.

### Packaging smoke tests

The same application-level smoke scenario should run against:

- the direct development package
- the flake package
- the NixOS deployment adapter
- the OCI image and Compose adapter
- eventually the Raspberry Pi appliance image

The scenario initializes an instance with `mcctl`, creates and updates a task, enables a reference plugin, starts or restarts `mctrld`, verifies history and health, and renders Markdown.

Deployment adapters may add environment-specific assertions, but they may not replace this shared scenario or alter its application semantics.

### Installer tests

The guided installer must produce configuration that passes the application's own validator. Browser-flow tests should verify first-boot admin creation, plugin selection, failed plugin configuration, resume after interruption, a successful clean install without terminal access, and equivalence between installer-generated and declaratively generated configurations.

## CI policy

A change to a public core interface cannot merge unless all built-in and reference plugin contract tests pass. A plugin change must run core tests, its own tests, the shared contract suite, and at least one multi-plugin isolation scenario.

A change to a deployment adapter must run the common packaging smoke test. A change to machine-readable interface schemas must regenerate artifacts and prove the working tree remains clean.

No test may rely on privileged interfaces available only to built-in plugins. A built-in plugin that cannot pass the public contract suite represents an architecture defect, not a test exception.
