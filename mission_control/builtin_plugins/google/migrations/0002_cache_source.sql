ALTER TABLE plugin__15__google_calendar__sync_status
  ADD COLUMN source_mode TEXT CHECK (source_mode IN ('demo', 'live'));

ALTER TABLE plugin__15__google_calendar__sync_status
  ADD COLUMN source_fingerprint TEXT;

INSERT INTO plugin__15__google_calendar__schema_migrations(version) VALUES (2);
