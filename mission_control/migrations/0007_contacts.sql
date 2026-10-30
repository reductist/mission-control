CREATE TABLE contacts (
  id TEXT PRIMARY KEY,
  record_json TEXT NOT NULL CHECK (json_valid(record_json)),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;

CREATE INDEX contacts_updated_idx ON contacts(updated_at DESC, id);

INSERT INTO schema_migrations(version) VALUES (7);
