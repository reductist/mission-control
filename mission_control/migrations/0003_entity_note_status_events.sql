PRAGMA foreign_keys = ON;

CREATE TABLE entity_note_status_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  note_id TEXT NOT NULL REFERENCES entity_notes(note_id),
  previous_revision TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('active', 'inactive')),
  actor TEXT NOT NULL CHECK (
    length(trim(actor)) > 0
    AND length(actor) <= 256
  ),
  occurred_at TEXT NOT NULL,
  UNIQUE(note_id, previous_revision)
) STRICT;

CREATE INDEX entity_note_status_events_note_sequence_idx
  ON entity_note_status_events(note_id, sequence);

CREATE TRIGGER entity_note_status_events_require_current_revision
BEFORE INSERT ON entity_note_status_events
BEGIN
  SELECT RAISE(ABORT, 'stale entity note revision')
  WHERE NEW.previous_revision != COALESCE(
    (
      SELECT event_id
      FROM entity_note_status_events
      WHERE note_id = NEW.note_id
      ORDER BY sequence DESC
      LIMIT 1
    ),
    NEW.note_id
  );

  SELECT RAISE(ABORT, 'entity note state is already current')
  WHERE NEW.state = COALESCE(
    (
      SELECT state
      FROM entity_note_status_events
      WHERE note_id = NEW.note_id
      ORDER BY sequence DESC
      LIMIT 1
    ),
    'active'
  );
END;

CREATE TRIGGER entity_note_status_events_are_immutable_update
BEFORE UPDATE ON entity_note_status_events
BEGIN
  SELECT RAISE(ABORT, 'entity note status events are immutable');
END;

CREATE TRIGGER entity_note_status_events_are_immutable_delete
BEFORE DELETE ON entity_note_status_events
BEGIN
  SELECT RAISE(ABORT, 'entity note status events are immutable');
END;

INSERT INTO schema_migrations(version) VALUES (3);
