PRAGMA foreign_keys = ON;

CREATE TABLE plugin__15__google_calendar__schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE plugin__15__google_calendar__collections (
  collection_key TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('calendar', 'task-list')),
  external_id TEXT NOT NULL,
  label TEXT NOT NULL CHECK (length(trim(label)) > 0),
  access_role TEXT,
  last_attempt_at TEXT,
  last_success_at TEXT,
  error_code TEXT,
  error_detail TEXT,
  UNIQUE(kind, external_id)
) STRICT;

CREATE TABLE plugin__15__google_calendar__entries (
  entity_id TEXT PRIMARY KEY,
  collection_key TEXT NOT NULL REFERENCES plugin__15__google_calendar__collections(collection_key) ON DELETE CASCADE,
  remote_id TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('calendar-event', 'task')),
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  context TEXT NOT NULL CHECK (length(trim(context)) > 0),
  detail TEXT,
  timing_kind TEXT NOT NULL CHECK (timing_kind IN ('all-day', 'timed', 'due-on', 'anytime')),
  occurs_on TEXT,
  ends_before TEXT,
  starts_at TEXT,
  ends_at TEXT,
  due_on TEXT,
  status TEXT NOT NULL,
  location TEXT,
  source_url TEXT,
  revision TEXT NOT NULL CHECK (length(trim(revision)) > 0),
  updated_at TEXT NOT NULL,
  UNIQUE(collection_key, remote_id),
  CHECK (
    (timing_kind = 'all-day' AND occurs_on IS NOT NULL AND starts_at IS NULL AND ends_at IS NULL AND due_on IS NULL)
    OR (timing_kind = 'timed' AND occurs_on IS NULL AND starts_at IS NOT NULL AND ends_at IS NOT NULL AND due_on IS NULL)
    OR (timing_kind = 'due-on' AND occurs_on IS NULL AND starts_at IS NULL AND ends_at IS NULL AND due_on IS NOT NULL)
    OR (timing_kind = 'anytime' AND occurs_on IS NULL AND starts_at IS NULL AND ends_at IS NULL AND due_on IS NULL)
  )
) STRICT;

CREATE INDEX plugin__15__google_calendar__entries_collection_idx
  ON plugin__15__google_calendar__entries(collection_key, entity_type, entity_id);

CREATE TABLE plugin__15__google_calendar__sync_status (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  last_attempt_at TEXT,
  last_success_at TEXT,
  error_code TEXT,
  error_detail TEXT
) STRICT;

INSERT INTO plugin__15__google_calendar__sync_status(singleton) VALUES (1);
INSERT INTO plugin__15__google_calendar__schema_migrations(version) VALUES (1);
