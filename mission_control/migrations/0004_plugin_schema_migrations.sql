CREATE TABLE plugin_schema_migrations (
  plugin_id TEXT NOT NULL,
  migration_set TEXT NOT NULL,
  version INTEGER NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (plugin_id, migration_set, version)
) STRICT;

INSERT INTO schema_migrations(version) VALUES (4);
