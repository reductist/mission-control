PRAGMA foreign_keys = ON;

CREATE TABLE plugin__9__landscape__schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE plugin__9__landscape__initiatives (
  initiative_id TEXT PRIMARY KEY,
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  state TEXT NOT NULL
    CHECK (state IN ('open', 'blocked', 'waiting', 'completed')),
  context TEXT,
  detail TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE plugin__9__landscape__actions (
  action_id TEXT PRIMARY KEY,
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  state TEXT NOT NULL
    CHECK (state IN ('ready', 'blocked', 'waiting', 'done')),
  timing_kind TEXT NOT NULL
    CHECK (timing_kind IN ('anytime', 'due-on', 'due-at', 'window')),
  due_on TEXT,
  due_at TEXT,
  starts_at TEXT,
  ends_at TEXT,
  context TEXT,
  detail TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (
    (timing_kind = 'anytime' AND due_on IS NULL AND due_at IS NULL AND starts_at IS NULL AND ends_at IS NULL)
    OR (timing_kind = 'due-on' AND due_on IS NOT NULL AND due_at IS NULL AND starts_at IS NULL AND ends_at IS NULL)
    OR (timing_kind = 'due-at' AND due_on IS NULL AND due_at IS NOT NULL AND starts_at IS NULL AND ends_at IS NULL)
    OR (timing_kind = 'window' AND due_on IS NULL AND due_at IS NULL AND starts_at IS NOT NULL AND ends_at IS NOT NULL)
  )
) STRICT;

CREATE TABLE plugin__9__landscape__events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('initiative', 'action')),
  entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  occurred_at TEXT NOT NULL
) STRICT;

CREATE INDEX plugin__9__landscape__events_entity_sequence_idx
  ON plugin__9__landscape__events(entity_kind, entity_id, sequence);

CREATE TABLE plugin__9__landscape__seed_imports (
  import_id TEXT PRIMARY KEY,
  source_revision TEXT NOT NULL,
  imported_at TEXT NOT NULL
) STRICT;

CREATE TRIGGER plugin__9__landscape__events_are_immutable_update
BEFORE UPDATE ON plugin__9__landscape__events
BEGIN
  SELECT RAISE(ABORT, 'landscape events are immutable');
END;

CREATE TRIGGER plugin__9__landscape__events_are_immutable_delete
BEFORE DELETE ON plugin__9__landscape__events
BEGIN
  SELECT RAISE(ABORT, 'landscape events are immutable');
END;

INSERT INTO plugin__9__landscape__schema_migrations(version) VALUES (1);
