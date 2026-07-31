# ADR: First domain plugin

- **Status:** Accepted
- **Date:** 2026-07-31

## Context

The platform contracts are ahead of everyday usefulness. The first domain plugin should exercise real ownership, persistence, agenda projection, command routing, browser presentation, and durable export without introducing sensitive financial data or external service dependencies.

Landscape and Yard work already has real initiatives, observations, research, blockers, seasonal constraints, and granular actions. It can force the extension boundaries to earn their complexity while immediately improving a recurring household workflow.

## Decision

Landscape/Yard is the first real domain plugin and dogfooding vertical slice. Its initial acceptance target is one property/site, the backyard equipment-access initiative, granular work and blockers, research and seasonal windows, an observation with an attachment reference, agenda projection, owner-routed mutations, shared Overview/Yard state, restart persistence, and Markdown export.

The implementation should add only the public plugin machinery required by this slice. It must not build a speculative general plugin platform or make optional weather, maps, calendars, plant databases, or image analysis mandatory.

A wiki plugin is the leading early follow-up. It should own durable notes, decisions, research, and links through the same public interfaces, and it must remain independently installable rather than becoming privileged core functionality.

## Consequences

- The next abstractions are driven by a real workflow and representative data.
- Finance ingestion, OCI packaging, appliance work, and automation execution remain later milestones.
- Yard-specific states, recurrence, and domain detail remain owned by the plugin; the shared agenda receives immutable projections only.
- The wiki can support continued dogfooding without displacing the first Yard milestone.
