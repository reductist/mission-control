PRAGMA foreign_keys = ON;

CREATE TABLE plugin__14__family_rewards__state (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1), revision INTEGER NOT NULL CHECK (revision > 0),
  timezone TEXT NOT NULL, school_day_cap_minutes INTEGER NOT NULL CHECK (school_day_cap_minutes BETWEEN 0 AND 1440),
  non_school_day_cap_minutes INTEGER NOT NULL CHECK (non_school_day_cap_minutes BETWEEN 0 AND 1440),
  tasks_json TEXT NOT NULL CHECK (json_valid(tasks_json)), windows_json TEXT NOT NULL CHECK (json_valid(windows_json)),
  updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE plugin__14__family_rewards__overrides (
  local_date TEXT PRIMARY KEY, school_day INTEGER CHECK (school_day IN (0, 1)),
  eligible INTEGER NOT NULL CHECK (eligible IN (0, 1)), starts_at TEXT, ends_at TEXT, note TEXT NOT NULL DEFAULT '',
  CHECK ((eligible = 0 AND starts_at IS NULL AND ends_at IS NULL) OR (eligible = 1 AND starts_at IS NOT NULL AND ends_at IS NOT NULL))
) STRICT;

CREATE TABLE plugin__14__family_rewards__ledger (
  entry_id TEXT PRIMARY KEY, command_id TEXT NOT NULL UNIQUE, local_date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('earn', 'spend', 'reversal', 'refund')),
  amount_minutes INTEGER NOT NULL CHECK (amount_minutes != 0), task_id TEXT,
  reverses_entry_id TEXT UNIQUE REFERENCES plugin__14__family_rewards__ledger(entry_id),
  note TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL, occurred_at TEXT NOT NULL,
  CHECK ((kind = 'earn' AND amount_minutes > 0 AND task_id IS NOT NULL AND reverses_entry_id IS NULL)
    OR (kind = 'spend' AND amount_minutes < 0 AND task_id IS NULL AND reverses_entry_id IS NULL)
    OR (kind IN ('reversal', 'refund') AND task_id IS NULL AND reverses_entry_id IS NOT NULL))
) STRICT;

CREATE TABLE plugin__14__family_rewards__completions (
  local_date TEXT NOT NULL, task_id TEXT NOT NULL,
  active_award_entry_id TEXT REFERENCES plugin__14__family_rewards__ledger(entry_id),
  PRIMARY KEY (local_date, task_id)
) STRICT;

CREATE TABLE plugin__14__family_rewards__command_receipts (
  command_id TEXT PRIMARY KEY, command_fingerprint TEXT NOT NULL,
  result_json TEXT NOT NULL CHECK (json_valid(result_json)), created_at TEXT NOT NULL
) STRICT;

CREATE INDEX plugin__14__family_rewards__ledger_date_idx ON plugin__14__family_rewards__ledger(local_date, occurred_at);

CREATE TRIGGER plugin__14__family_rewards__ledger_immutable_update BEFORE UPDATE ON plugin__14__family_rewards__ledger
BEGIN SELECT RAISE(ABORT, 'family rewards ledger is immutable'); END;
CREATE TRIGGER plugin__14__family_rewards__ledger_immutable_delete BEFORE DELETE ON plugin__14__family_rewards__ledger
BEGIN SELECT RAISE(ABORT, 'family rewards ledger is immutable'); END;
