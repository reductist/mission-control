ALTER TABLE google_calendar_sync_status
  ADD COLUMN source_mode TEXT CHECK (source_mode IN ('demo', 'live'));

ALTER TABLE google_calendar_sync_status
  ADD COLUMN source_fingerprint TEXT;

INSERT INTO google_calendar_schema_migrations(version) VALUES (2);
