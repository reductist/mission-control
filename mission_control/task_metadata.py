"""Core task metadata independent of provider-owned agenda contracts."""

from datetime import date, datetime
from functools import lru_cache
from importlib.resources import files
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator


TASK_TAG_CATALOG = (
    {"id": "maintenance", "label": "Maintenance", "view": "maintenance", "plugin_ids": ["household"]},
    {"id": "house-search", "label": "House search", "view": "house", "plugin_ids": ["home-search"]},
    {"id": "personal-social", "label": "Personal/social", "plugin_ids": []},
    {"id": "yard", "label": "Yard", "view": "yard", "plugin_ids": ["landscape"]},
)


@lru_cache(maxsize=2)
def task_request_validator(operation: str) -> Draft202012Validator:
    schema = json.loads(files("mission_control").joinpath("schemas", "core-task-request.schema.json").read_text())
    # Catalog owns the taxonomy; the schema exposes the same stable IDs to clients.
    schema["$defs"]["tags"]["items"]["enum"] = [tag["id"] for tag in TASK_TAG_CATALOG]
    schema["$ref"] = f"#/$defs/{operation}"
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_task_request(document: object, operation: str) -> None:
    error = next(task_request_validator(operation).iter_errors(document), None)
    if error is not None:
        raise ValueError(f"invalid task {operation} request: {error.message}")


def normalize_tags(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
        raise TypeError("task tags must be a list of stable tag IDs")
    allowed = {tag["id"] for tag in TASK_TAG_CATALOG}
    if any(tag not in allowed for tag in value):
        raise ValueError("unsupported task tag")
    if len(value) != len(set(value)):
        raise ValueError("task tags must be unique")
    return list(value)


def normalize_deadline(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("task deadline must be an object or null")
    kind = value.get("kind")
    field = "due_on" if kind == "due-on" else "due_at" if kind == "due-at" else None
    if field is None or set(value) != {"kind", field, "time_zone"}:
        raise ValueError("deadline requires kind, matching due field, and time_zone")
    if any(not isinstance(item, str) for item in value.values()):
        raise TypeError("deadline fields must be strings")
    try:
        zone = ZoneInfo(value["time_zone"])
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("deadline time_zone must be an IANA timezone") from error
    try:
        if field == "due_on":
            parsed_date = date.fromisoformat(value[field])
            if parsed_date.isoformat() != value[field]:
                raise ValueError("date must use YYYY-MM-DD")
        else:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value[field]) is None:
                raise ValueError("timed deadline requires an ISO timestamp with seconds and explicit offset")
            parsed = datetime.fromisoformat(value[field])
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timed deadline requires an explicit UTC offset")
            local = parsed.astimezone(zone)
            if local.utcoffset() != parsed.utcoffset() or local.replace(tzinfo=None) != parsed.replace(tzinfo=None):
                raise ValueError("deadline offset/local time does not match time_zone (including DST)")
    except ValueError as error:
        raise ValueError(f"invalid deadline: {error}") from error
    return dict(value)
