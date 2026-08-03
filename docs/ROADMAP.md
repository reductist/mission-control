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

1. **Deploy capability envelopes.** Pin merged Mission Control PR #37 in `nixconfigs` and validate capability-driven complete and reopen behavior on `vectorsigma`.
2. **Complete the lifecycle workflow.** Implement [issue #35](https://github.com/reductist/mission-control/issues/35): a discoverable completed-item history with first-class reopen controls, optimistic revision handling, cross-projection refresh, and restart persistence.
3. **Add rich entity details and activity.** Open an agenda card into an entity-focused detail surface with description, plugin-native context, immutable activity, and notes or structured observations through `entity.annotate`. The Landscape measurement workflow is the proving case.
4. **Add artifact storage and completion evidence.** Implement photo and document upload through `entity.attach` as a separate storage-focused slice. Artifacts may attach to the entity generally or to a specific activity/event, including completion evidence.
5. **Organize the aggregate agenda.** Add normalized plugin provenance and organizational metadata, then first-class filters and user-selected sorting/grouping such as sort by priority and group by plugin.
6. **Improve event operations.** Implement [issue #36](https://github.com/reductist/mission-control/issues/36): read-only `mcctl events` inspection with filters, JSON Lines output, stable cursors, redaction, and optional `-f`/`--follow` mode.

Each slice should remain independently reviewable, preserve plugin ownership, pass contract and packaging validation, and be deployed to `vectorsigma` for an end-to-end acceptance check before the next slice depends on it.
