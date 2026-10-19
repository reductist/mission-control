PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

DROP INDEX task_events_task_sequence_idx;
DROP TRIGGER task_events_are_immutable_update;
DROP TRIGGER task_events_are_immutable_delete;

ALTER TABLE task_events RENAME TO task_events_before_hierarchy;
ALTER TABLE tasks RENAME TO tasks_before_hierarchy;

CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  description TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'backlog'
    CHECK (state IN ('backlog', 'ready', 'in-progress', 'done', 'canceled')),
  blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
  waiting_on TEXT,
  review_after TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deadline_json TEXT CHECK (deadline_json IS NULL OR json_valid(deadline_json)),
  tags_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags_json)),
  parent_id TEXT REFERENCES tasks(id) ON DELETE RESTRICT,
  sibling_order INTEGER NOT NULL DEFAULT 0 CHECK (sibling_order >= 0),
  CHECK (parent_id IS NULL OR parent_id <> id)
) STRICT;

INSERT INTO tasks(
  id, title, description, state, blocked, waiting_on, review_after,
  created_at, updated_at, deadline_json, tags_json, parent_id, sibling_order
)
SELECT
  id, title, description, state, blocked, waiting_on, review_after,
  created_at, updated_at, deadline_json, tags_json, NULL,
  row_number() OVER (ORDER BY created_at, id) - 1
FROM tasks_before_hierarchy;

CREATE INDEX tasks_parent_order_idx
  ON tasks(parent_id, sibling_order, created_at, id);

CREATE TABLE task_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  occurred_at TEXT NOT NULL
) STRICT;

INSERT INTO task_events(sequence, event_id, task_id, event_type, payload_json, occurred_at)
SELECT sequence, event_id, task_id, event_type, payload_json, occurred_at
FROM task_events_before_hierarchy;

CREATE INDEX task_events_task_sequence_idx
  ON task_events(task_id, sequence);

CREATE TRIGGER task_events_are_immutable_update
BEFORE UPDATE ON task_events
BEGIN
  SELECT RAISE(ABORT, 'task events are immutable');
END;

CREATE TRIGGER task_events_are_immutable_delete
BEFORE DELETE ON task_events
BEGIN
  SELECT RAISE(ABORT, 'task events are immutable');
END;

DROP TABLE task_events_before_hierarchy;
DROP TABLE tasks_before_hierarchy;

INSERT INTO schema_migrations(version) VALUES (6);

COMMIT;
PRAGMA foreign_keys = ON;
