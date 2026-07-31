"""Read-only first slice of the bundled Landscape/Yard plugin."""

from __future__ import annotations

import json
from importlib.resources import files

from ...agenda import AgendaContribution, parse_agenda_contribution
from ...plugins import Capability, parse_plugin_registration


def _document(name: str) -> object:
    resource = files(__package__).joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_agenda_contribution() -> AgendaContribution:
    """Validate registration and return the plugin-owned agenda snapshot."""

    registration = parse_plugin_registration(_document("registration.json"))
    contribution = parse_agenda_contribution(_document("agenda.json"))
    if Capability.AGENDA not in registration.capabilities:
        raise ValueError("landscape registration must declare the agenda capability")
    if registration.plugin_id != contribution.provider.plugin_id:
        raise ValueError("landscape registration and agenda provider ids must match")
    return contribution
