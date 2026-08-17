CREATE TRIGGER plugin__9__landscape__initiatives_validate_insert
BEFORE INSERT ON plugin__9__landscape__initiatives
WHEN NOT (
  length(NEW.initiative_id) BETWEEN 1 AND 128
  AND NEW.initiative_id GLOB '[A-Za-z0-9]*'
  AND NEW.initiative_id NOT GLOB '*[^A-Za-z0-9._:-]*'
  AND length(trim(NEW.title)) > 0
  AND length(NEW.title) <= 256
  AND (
    NEW.context IS NULL
    OR (length(trim(NEW.context)) > 0 AND length(NEW.context) <= 128)
  )
  AND (
    NEW.detail IS NULL
    OR (length(trim(NEW.detail)) > 0 AND length(NEW.detail) <= 4096)
  )
)
BEGIN
  SELECT RAISE(ABORT, 'invalid Landscape initiative text');
END;

CREATE TRIGGER plugin__9__landscape__initiatives_validate_update
BEFORE UPDATE ON plugin__9__landscape__initiatives
WHEN NOT (
  length(NEW.initiative_id) BETWEEN 1 AND 128
  AND NEW.initiative_id GLOB '[A-Za-z0-9]*'
  AND NEW.initiative_id NOT GLOB '*[^A-Za-z0-9._:-]*'
  AND length(trim(NEW.title)) > 0
  AND length(NEW.title) <= 256
  AND (
    NEW.context IS NULL
    OR (length(trim(NEW.context)) > 0 AND length(NEW.context) <= 128)
  )
  AND (
    NEW.detail IS NULL
    OR (length(trim(NEW.detail)) > 0 AND length(NEW.detail) <= 4096)
  )
)
BEGIN
  SELECT RAISE(ABORT, 'invalid Landscape initiative text');
END;

CREATE TRIGGER plugin__9__landscape__actions_validate_insert
BEFORE INSERT ON plugin__9__landscape__actions
WHEN NOT (
  length(NEW.action_id) BETWEEN 1 AND 128
  AND NEW.action_id GLOB '[A-Za-z0-9]*'
  AND NEW.action_id NOT GLOB '*[^A-Za-z0-9._:-]*'
  AND length(trim(NEW.title)) > 0
  AND length(NEW.title) <= 256
  AND (
    NEW.context IS NULL
    OR (length(trim(NEW.context)) > 0 AND length(NEW.context) <= 128)
  )
  AND (
    NEW.detail IS NULL
    OR (length(trim(NEW.detail)) > 0 AND length(NEW.detail) <= 4096)
  )
)
BEGIN
  SELECT RAISE(ABORT, 'invalid Landscape action text');
END;

CREATE TRIGGER plugin__9__landscape__actions_validate_update
BEFORE UPDATE ON plugin__9__landscape__actions
WHEN NOT (
  length(NEW.action_id) BETWEEN 1 AND 128
  AND NEW.action_id GLOB '[A-Za-z0-9]*'
  AND NEW.action_id NOT GLOB '*[^A-Za-z0-9._:-]*'
  AND length(trim(NEW.title)) > 0
  AND length(NEW.title) <= 256
  AND (
    NEW.context IS NULL
    OR (length(trim(NEW.context)) > 0 AND length(NEW.context) <= 128)
  )
  AND (
    NEW.detail IS NULL
    OR (length(trim(NEW.detail)) > 0 AND length(NEW.detail) <= 4096)
  )
)
BEGIN
  SELECT RAISE(ABORT, 'invalid Landscape action text');
END;

-- Force the new validation triggers across data created by older versions. These
-- assignments preserve values while making migration failure atomic and explicit.
UPDATE plugin__9__landscape__initiatives SET initiative_id = initiative_id;
UPDATE plugin__9__landscape__actions SET action_id = action_id;

INSERT INTO plugin__9__landscape__schema_migrations(version) VALUES (2);
