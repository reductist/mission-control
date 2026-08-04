PRAGMA foreign_keys = ON;

CREATE TABLE entity_notes (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id TEXT NOT NULL UNIQUE,
  plugin_id TEXT NOT NULL CHECK (
    length(plugin_id) > 0
    AND plugin_id = lower(plugin_id)
  ),
  entity_type TEXT NOT NULL CHECK (length(entity_type) > 0),
  entity_id TEXT NOT NULL CHECK (length(entity_id) > 0),
  body TEXT NOT NULL CHECK (
    length(trim(body)) > 0
    AND length(body) <= 16384
  ),
  actor TEXT NOT NULL CHECK (
    length(trim(actor)) > 0
    AND length(actor) <= 256
  ),
  occurred_at TEXT NOT NULL
) STRICT;

CREATE INDEX entity_notes_target_sequence_idx
  ON entity_notes(plugin_id, entity_type, entity_id, sequence);

CREATE TRIGGER entity_notes_are_immutable_update
BEFORE UPDATE ON entity_notes
BEGIN
  SELECT RAISE(ABORT, 'entity notes are immutable');
END;

CREATE TRIGGER entity_notes_are_immutable_delete
BEFORE DELETE ON entity_notes
BEGIN
  SELECT RAISE(ABORT, 'entity notes are immutable');
END;

INSERT INTO schema_migrations(version) VALUES (2);
