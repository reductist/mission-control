# Entity details and shared annotations

Mission Control composes an entity-focused view without converting plugin-owned
records into core-owned tasks. A stable `plugin_id + entity_type + entity_id`
reference selects the authoritative provider. The provider returns current display
state, revision, attributes, legal affordances, and domain activity; core adds only
shared activity that it owns, such as annotations.

## Ownership boundary

| Concern | Owner |
| --- | --- |
| Title, description, state, timing, and plugin-native attributes | Plugin |
| Legal lifecycle transitions and current affordances | Plugin |
| Domain event history and event summaries | Plugin |
| Textual annotations and their immutable storage | Core |
| Read-time activity composition and generic rendering | Core |
| Photos, documents, and completion evidence | Future artifact slice |

Core does not persist a copy of the plugin entity. Disabling a plugin hides its
detail projection but does not delete either plugin-owned state or core-owned notes.
When the plugin is enabled again, core composes the current entity detail with the
same notes by stable entity reference.

## Capability enforcement

A plugin must declare the coarse `entity-details` capability before it exposes a
detail provider. Each entity type separately declares `activity.read`,
`entity.annotate`, and any domain lifecycle capabilities it may support. A detail
projection may expose only a current subset of that registered envelope.

`entity.annotate` is implemented as a standardized core service. The plugin remains
responsible for resolving the current entity revision and advertising the
`entity.annotate` affordance. Core validates that affordance and revision before it
accepts an append-only note. Adding a note does not advance the plugin entity's
revision because it does not mutate plugin-owned state.

## Activity semantics

The entity-detail contract exposes one chronological activity sequence. Plugin
events and core notes retain separate identifiers and types; composition does not
rewrite either source. Notes are immutable at the SQLite boundary and contain a
bounded body, actor label, and timezone-aware timestamp.

This is intentionally not the artifact model. A later storage-focused slice will
associate photos and documents with the same entity reference and, when useful, a
specific activity or completion event.
