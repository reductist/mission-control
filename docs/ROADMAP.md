# Product roadmap

Mission Control is a plugin-oriented work and context system, not a global to-do application. Tasks and actions are only some of the entity types that plugins may own.

## Product and architecture guardrails

- A card is a projection of a richer plugin-owned entity, not the entity itself.
- Plugins own domain meaning, legal state transitions, detailed state, and plugin-specific metadata.
- Registration defines the maximum capability envelope for each plugin-owned entity type.
- Each entity exposes a state-dependent subset of that envelope as its current affordances; renderers do not infer operations from state names or entry kinds.
- Core may aggregate stable entity references, projections, shared annotations and artifacts, activity, and normalized organizational metadata without taking ownership of plugin domain models.
- Completion is not universal. Different entities may be completable, reopenable, acknowledgeable, dismissible, editable, or read-only.
- Notes and artifacts must remain associated with their underlying entity and may also be linked to the event that created or finalized them.
- Agenda organization must preserve plugin provenance and support first-class filtering, sorting, and grouping; color alone must not carry plugin, priority, or state meaning.
- Capability enforcement is distinct from operational permissions and is not a sandbox for trusted in-process plugin code.

## Near-term sequence

Capability envelopes, completed-item history, rich entity detail/activity, external
plugin discovery, and the read-only Google Agenda/Calendar showcase are complete.
That showcase exercises configuration, credentials, jobs, health, cache, and
generic projections, and revealed the integration/configuration work below.

The canonical sequence is maintained in
[`configuration-and-schema-evolution.md`](configuration-and-schema-evolution.md).
In summary:

1. Establish canonical configuration and the simplified public plugin-authoring
   boundary.
2. Add scoped attribution and Google-owned multi-connection support.
3. Add the generic setup-action contract and guided Google setup. The
   storage-free provider flow is complete; the loopback browser host and atomic
   commit/export adapter are next.
4. Converge direct and NixOS configuration, move accepted showcase behavior into
   the canonical service, and remove the port-8001 showcase service.
5. Replace the ad-hoc dashboard response and core-specific task/UI paths with typed
   workspace, creation-form, and declarative renderer-neutral UI contracts. The
   web UI remains the reference renderer while fixtures prove future TUI use.
6. Review real-data UX mockups and implement the compact Schedule and summary
   Dashboard experience.
7. Add artifact storage and attachment links, followed by tags, saved views, and
   the rich task composer.
8. Implement deferred operational improvements such as
   [issue #36](https://github.com/reductist/mission-control/issues/36) event
   inspection when they become the active product priority.

Each slice should remain independently reviewable, preserve plugin ownership, pass contract and packaging validation, and be deployed to `vectorsigma` for an end-to-end acceptance check before the next slice depends on it.
