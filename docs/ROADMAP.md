# Product roadmap

Mission Control brings information and actions from separate tools into one
workspace. It is not intended to replace those tools or become a universal task
database.

## Product rules

- The system that created an item remains its source of truth.
- Plugins own their data, business rules, state changes, and detailed history.
- Shared views use validated, read-only projections from each plugin.
- Commands are sent to the plugin that owns the item.
- The interface shows source and owner information in text, not only through
  color.
- Different item types may support different actions. Mission Control must not
  assume that every item can be completed, edited, or reopened.
- Notes and attachments stay linked to the item they describe.
- The web interface is the reference client, but public view and form contracts
  must also work for a future terminal client.

## Completed foundation

The project now has:

- versioned plugin registration, agenda, history, detail, activity, and command
  contracts
- plugin discovery and a public plugin adapter
- one validated application configuration model for direct and packaged use
- typed source, connection, collection, and person attribution
- isolated Google connections with Calendar and Tasks selection
- guided Google setup with secure credential handling
- equivalent direct and NixOS deployment configuration
- a single canonical service on `vectorsigma`; the temporary port-8001 showcase
  has been removed

## Next

1. **Define the workspace response.** Replace the prototype dashboard response
   with a versioned workspace snapshot and generic plugin contributions. Remove
   duplicated core task data and hard-coded House and Yard assembly.
2. **Move task creation onto public contracts.** Run Tasks through the normal
   plugin lifecycle and add a typed form and creation contract.
3. **Describe UI contributions as data.** Replace prototype-specific navigation
   and rendering paths with renderer-independent view, action, and form
   descriptions. Keep the web application as the first implementation.
4. **Improve the main views.** Test designs with real typed data, then build a
   compact Schedule and a useful summary Dashboard.
5. **Add attachments.** Define artifact storage and secure image and document
   uploads while preserving links to the owning item and activity event.
6. **Add organization and richer editing.** Implement tags, saved filters, and a
   richer task editor after the underlying contracts are stable.

Operational work such as
[event inspection](https://github.com/reductist/mission-control/issues/36) will
be scheduled when it becomes a higher product priority.

Each step should be reviewable on its own, pass contract and packaging tests,
and receive an end-to-end check on `vectorsigma` before later work depends on
it.

The detailed configuration and schema decisions are recorded in
[`configuration-and-schema-evolution.md`](configuration-and-schema-evolution.md).
