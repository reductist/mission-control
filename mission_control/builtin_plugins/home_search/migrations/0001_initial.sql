PRAGMA foreign_keys = ON;

CREATE TABLE plugin__11__home_search__state (
  singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
  version INTEGER NOT NULL CHECK (version > 0),
  source_revision TEXT,
  snapshot_json TEXT CHECK (snapshot_json IS NULL OR json_valid(snapshot_json)),
  last_checked_at TEXT,
  imported_at TEXT
) STRICT;

INSERT INTO plugin__11__home_search__state(singleton_id, version)
VALUES (1, 1);

CREATE TABLE plugin__11__home_search__candidates (
  candidate_id TEXT PRIMARY KEY,
  document_json TEXT NOT NULL CHECK (json_valid(document_json)),
  review_status TEXT NOT NULL
    CHECK (review_status IN ('unreviewed', 'shortlisted', 'rejected')),
  current INTEGER NOT NULL CHECK (current IN (0, 1)),
  last_seen_checked_at TEXT NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  first_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE plugin__11__home_search__imports (
  source_revision TEXT PRIMARY KEY,
  snapshot_hash TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  imported_at TEXT NOT NULL
) STRICT;

CREATE TABLE plugin__11__home_search__events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('search', 'candidate')),
  entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  occurred_at TEXT NOT NULL
) STRICT;

CREATE INDEX plugin__11__home_search__events_entity_idx
ON plugin__11__home_search__events(entity_type, entity_id, sequence);

CREATE TRIGGER plugin__11__home_search__events_immutable_update
BEFORE UPDATE ON plugin__11__home_search__events
BEGIN
  SELECT RAISE(ABORT, 'home-search events are immutable');
END;

CREATE TRIGGER plugin__11__home_search__events_immutable_delete
BEFORE DELETE ON plugin__11__home_search__events
BEGIN
  SELECT RAISE(ABORT, 'home-search events are immutable');
END;
