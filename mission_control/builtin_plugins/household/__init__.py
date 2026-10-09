"""Configuration-backed household maintenance and reference plugin."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

from mission_control.builtin_plugins.household.config import (
    HouseholdAppointment,
    HouseholdCase,
    HouseholdConfig,
)
from mission_control.plugin_api import CapabilityRouter, PluginContext

PLUGIN_ID = "household"


def activate(context: PluginContext) -> CapabilityRouter:
    """Expose household cases through the public agenda and detail contracts."""

    if context.credentials:
        raise ValueError("Household does not accept credentials")
    if context.agenda_seed is not None:
        raise ValueError("Household does not declare an agenda seed")
    config = HouseholdConfig.from_runtime(context.configuration)
    cases = {item.case_id: item for item in config.cases}
    appointments = {
        _appointment_entity_id(case.case_id, appointment.appointment_id): (
            case,
            appointment,
        )
        for case in config.cases
        for appointment in case.appointments
    }

    def agenda_snapshot(inputs: Mapping[str, object]) -> object:
        generated_at = datetime.fromisoformat(cast(str, inputs["generated_at"]))
        return _agenda(config, generated_at)

    def entity_details(inputs: Mapping[str, object]) -> object:
        target = cast(Mapping[str, str], inputs["target"])
        if target["plugin_id"] != PLUGIN_ID:
            return None
        if target["entity_type"] == "case":
            case = cases.get(target["entity_id"])
            return _case_detail(case) if case is not None else None
        if target["entity_type"] == "appointment":
            match = appointments.get(target["entity_id"])
            return _appointment_detail(*match) if match is not None else None
        return None

    return CapabilityRouter(
        context.plugin_id,
        {
            "agenda.snapshot": agenda_snapshot,
            "entity-details.get": entity_details,
        },
    )


def _revision(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _case_document(case: HouseholdCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "title": case.title,
        "state": case.state,
        "summary": case.summary,
        "area": case.area,
        "contacts": [
            {
                "name": item.name,
                "role": item.role,
                "company": item.company,
                "phone": item.phone,
                "email": item.email,
                "website": item.website,
            }
            for item in case.contacts
        ],
        "links": [
            {"label": item.label, "kind": item.kind, "url": item.url}
            for item in case.links
        ],
        "related_task_ids": list(case.related_task_ids),
        "appointments": [
            {
                "appointment_id": item.appointment_id,
                "title": item.title,
                "kind": item.kind,
                "starts_at": item.starts_at.isoformat(),
                "ends_at": item.ends_at.isoformat(),
                "detail": item.detail,
            }
            for item in case.appointments
        ],
    }


def _case_revision(case: HouseholdCase) -> str:
    return _revision(_case_document(case))


def _appointment_revision(case: HouseholdCase, appointment: HouseholdAppointment) -> str:
    return _revision(
        {
            "case_revision": _case_revision(case),
            "appointment_id": appointment.appointment_id,
        }
    )


def _appointment_entity_id(case_id: str, appointment_id: str) -> str:
    return f"{case_id}:{appointment_id}"


def _annotate_affordance() -> list[dict[str, str]]:
    return [{"capability": "entity.annotate", "command": "add-note"}]


def _agenda(config: HouseholdConfig, generated_at: datetime) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for case in config.cases:
        revision = _case_revision(case)
        entries.append(
            {
                "id": case.case_id,
                "source": {
                    "plugin_id": PLUGIN_ID,
                    "entity_type": "case",
                    "entity_id": case.case_id,
                },
                "title": case.title,
                "attribution": {"principal_ids": []},
                "context": case.area or "Household",
                "detail": case.summary,
                "kind": "initiative",
                "state": case.state,
                "revision": revision,
                "affordances": _annotate_affordance(),
            }
        )
        for appointment in case.appointments:
            entity_id = _appointment_entity_id(
                case.case_id, appointment.appointment_id
            )
            entries.append(
                {
                    "id": entity_id,
                    "source": {
                        "plugin_id": PLUGIN_ID,
                        "entity_type": "appointment",
                        "entity_id": entity_id,
                    },
                    "title": appointment.title,
                    "attribution": {"principal_ids": []},
                    "context": case.title,
                    "detail": appointment.detail,
                    "kind": "event",
                    "timing": {
                        "kind": "timed",
                        "starts_at": appointment.starts_at.isoformat(),
                        "ends_at": appointment.ends_at.isoformat(),
                    },
                    "revision": _appointment_revision(case, appointment),
                    "affordances": _annotate_affordance(),
                }
            )
    return {
        "schema_version": "mission-control.agenda/v2",
        "provider": {"plugin_id": PLUGIN_ID},
        "revision": _revision([_case_document(case) for case in config.cases]),
        "generated_at": generated_at.isoformat(),
        "entries": entries,
    }


def _attribute(key: str, label: str, value: str) -> dict[str, str]:
    return {"key": key, "label": label, "value": value}


def _case_attributes(case: HouseholdCase) -> list[dict[str, str]]:
    attributes: list[dict[str, str]] = []
    if case.area is not None:
        attributes.append(_attribute("area", "Area", case.area))
    for index, contact in enumerate(case.contacts):
        heading = contact.role or "Contact"
        identity = " — ".join(
            item for item in (contact.name, contact.company) if item is not None
        )
        attributes.append(_attribute(f"contact:{index}:name", heading, identity))
        if contact.phone is not None:
            attributes.append(
                _attribute(
                    f"contact:{index}:phone",
                    f"{contact.name} phone",
                    f"tel:{contact.phone}",
                )
            )
        if contact.email is not None:
            attributes.append(
                _attribute(
                    f"contact:{index}:email",
                    f"{contact.name} email",
                    f"mailto:{contact.email}",
                )
            )
        if contact.website is not None:
            attributes.append(
                _attribute(
                    f"contact:{index}:website",
                    f"{contact.name} website",
                    contact.website,
                )
            )
    for index, link in enumerate(case.links):
        attributes.append(
            _attribute(f"link:{index}", f"{link.kind.title()}: {link.label}", link.url)
        )
    for index, task_id in enumerate(case.related_task_ids):
        attributes.append(
            _attribute(f"related-task:{index}", "Related task", task_id)
        )
    return attributes


def _case_detail(case: HouseholdCase) -> dict[str, object]:
    return {
        "schema_version": "mission-control.entity-detail/v1",
        "source": {
            "plugin_id": PLUGIN_ID,
            "entity_type": "case",
            "entity_id": case.case_id,
        },
        "title": case.title,
        "description": case.summary,
        "state": case.state,
        "revision": _case_revision(case),
        "attributes": _case_attributes(case),
        "affordances": _annotate_affordance(),
        "activity": [],
    }


def _appointment_detail(
    case: HouseholdCase, appointment: HouseholdAppointment
) -> dict[str, object]:
    entity_id = _appointment_entity_id(case.case_id, appointment.appointment_id)
    return {
        "schema_version": "mission-control.entity-detail/v1",
        "source": {
            "plugin_id": PLUGIN_ID,
            "entity_type": "appointment",
            "entity_id": entity_id,
        },
        "title": appointment.title,
        "description": appointment.detail or f"Scheduled {appointment.kind} visit.",
        "state": "scheduled",
        "revision": _appointment_revision(case, appointment),
        "attributes": [
            _attribute("case", "Maintenance case", case.title),
            _attribute("kind", "Visit type", appointment.kind.replace("-", " ").title()),
            _attribute(
                "scheduled",
                "Scheduled",
                f"{appointment.starts_at.isoformat()} to {appointment.ends_at.isoformat()}",
            ),
        ],
        "affordances": _annotate_affordance(),
        "activity": [],
    }
