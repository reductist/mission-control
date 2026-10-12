ALTER TABLE tasks ADD COLUMN deadline_json TEXT;
ALTER TABLE tasks ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]';
INSERT INTO schema_migrations(version) VALUES (5);
