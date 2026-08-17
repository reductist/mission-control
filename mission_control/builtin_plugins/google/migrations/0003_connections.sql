CREATE TABLE plugin__15__google_calendar__connections_v3 (
  connection_id TEXT PRIMARY KEY,
  label TEXT NOT NULL CHECK (length(trim(label)) > 0),
  source_mode TEXT NOT NULL CHECK (source_mode IN ('demo', 'live')),
  source_fingerprint TEXT NOT NULL,
  last_attempt_at TEXT,
  last_success_at TEXT,
  error_code TEXT,
  error_detail TEXT
) STRICT;

INSERT INTO plugin__15__google_calendar__connections_v3(
  connection_id, label, source_mode, source_fingerprint,
  last_attempt_at, last_success_at, error_code, error_detail
)
SELECT
  'default', 'Google Calendar', COALESCE(source_mode, 'demo'),
  COALESCE(source_fingerprint, 'legacy-v2'), last_attempt_at,
  last_success_at, error_code, error_detail
FROM plugin__15__google_calendar__sync_status
WHERE singleton = 1;

CREATE TABLE plugin__15__google_calendar__collections_v3 (
  collection_key TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES plugin__15__google_calendar__connections_v3(connection_id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('calendar', 'task-list')),
  external_id TEXT NOT NULL,
  label TEXT NOT NULL CHECK (length(trim(label)) > 0),
  principal_ids_json TEXT NOT NULL DEFAULT '[]',
  access_role TEXT,
  last_attempt_at TEXT,
  last_success_at TEXT,
  error_code TEXT,
  error_detail TEXT,
  UNIQUE(connection_id, kind, external_id)
) STRICT;

INSERT INTO plugin__15__google_calendar__collections_v3(
  collection_key, connection_id, kind, external_id, label, access_role,
  last_attempt_at, last_success_at, error_code, error_detail
)
SELECT
  collection_key, 'default', kind, external_id, label, access_role,
  last_attempt_at, last_success_at, error_code, error_detail
FROM plugin__15__google_calendar__collections;

CREATE TABLE plugin__15__google_calendar__entries_v3 (
  entity_id TEXT PRIMARY KEY,
  collection_key TEXT NOT NULL REFERENCES plugin__15__google_calendar__collections_v3(collection_key) ON DELETE CASCADE,
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

INSERT INTO plugin__15__google_calendar__entries_v3
SELECT * FROM plugin__15__google_calendar__entries;

DROP TABLE plugin__15__google_calendar__entries;
DROP TABLE plugin__15__google_calendar__collections;
DROP TABLE plugin__15__google_calendar__sync_status;

CREATE TABLE plugin__15__google_calendar__connections (
  connection_id TEXT PRIMARY KEY,
  label TEXT NOT NULL CHECK (length(trim(label)) > 0),
  source_mode TEXT NOT NULL CHECK (source_mode IN ('demo', 'live')),
  source_fingerprint TEXT NOT NULL,
  last_attempt_at TEXT,
  last_success_at TEXT,
  error_code TEXT,
  error_detail TEXT
) STRICT;

INSERT INTO plugin__15__google_calendar__connections
SELECT * FROM plugin__15__google_calendar__connections_v3;

CREATE TABLE plugin__15__google_calendar__collections (
  collection_key TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES plugin__15__google_calendar__connections(connection_id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('calendar', 'task-list')),
  external_id TEXT NOT NULL,
  label TEXT NOT NULL CHECK (length(trim(label)) > 0),
  principal_ids_json TEXT NOT NULL DEFAULT '[]',
  access_role TEXT,
  last_attempt_at TEXT,
  last_success_at TEXT,
  error_code TEXT,
  error_detail TEXT,
  UNIQUE(connection_id, kind, external_id)
) STRICT;

INSERT INTO plugin__15__google_calendar__collections
SELECT * FROM plugin__15__google_calendar__collections_v3;

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

INSERT INTO plugin__15__google_calendar__entries
SELECT * FROM plugin__15__google_calendar__entries_v3;

DROP TABLE plugin__15__google_calendar__entries_v3;
DROP TABLE plugin__15__google_calendar__collections_v3;
DROP TABLE plugin__15__google_calendar__connections_v3;

CREATE INDEX plugin__15__google_calendar__collections_connection_idx
  ON plugin__15__google_calendar__collections(connection_id, kind, collection_key);
CREATE INDEX plugin__15__google_calendar__entries_collection_idx
  ON plugin__15__google_calendar__entries(collection_key, entity_type, entity_id);

INSERT INTO plugin__15__google_calendar__schema_migrations(version) VALUES (3);
