# Contacts

Mission Control's Contacts section provides a small local address book without
introducing a second contact domain model. Each row is stored as the complete
`mission-control.portable-record/v1` envelope established by ADR 0001, with a
JSContact 2.0 `Card` as its standards-native payload.

The first UI supports:

- a compact searchable contact list;
- creating cards with name, kind, organization, primary email, primary phone,
  and address;
- editing those primary fields with optimistic revision checks; and
- persistence across server restarts.

Mission Control assigns independent core source, envelope, and JSContact
identities when a local card is created. Edits retain the complete Card, so
additional standard fields, secondary entries, and namespaced extensions are
not discarded just because the first UI does not render them. A stale edit is
rejected instead of silently overwriting a newer card.

This phase does not import contacts, synchronize CardDAV/DAV sources, export
address books, or change live data outside this local store. Contact-to-task
associations are also deferred until a shared transport-neutral relationship
contract exists; the UI does not invent a browser-only link model.
