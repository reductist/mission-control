from __future__ import annotations

from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.commands import CommandStatus
from mission_control.database import Database
from mission_control.server import MissionControlApplication


def command_document(
    revision: str,
    *,
    operation: str = "complete",
    entity_type: str = "action",
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "mission-control.command/v1",
        "command_id": f"landscape-{operation}-1",
        "target": {
            "plugin_id": "landscape",
            "entity_type": entity_type,
            "entity_id": "measure-access-route",
        },
        "expected_revision": revision,
        "command": operation,
        "arguments": arguments or {},
    }


def application(tmp_path) -> MissionControlApplication:
    return MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        write_token="known-token",
        builtin_plugins=prepare_builtin_agenda_plugins(("landscape",)),
    )


def test_landscape_owner_is_registered_only_when_plugin_is_active(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    enabled = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=prepare_builtin_agenda_plugins(("landscape",)),
    )
    status, accepted = enabled.execute_command(
        command_document("1"), authorized=True
    )
    assert status.value == 200
    assert accepted["status"] == CommandStatus.ACCEPTED.value

    disabled = MissionControlApplication(database, write_token="known-token")
    status, rejected = disabled.execute_command(
        command_document("2", operation="reopen"), authorized=True
    )
    assert status.value == 400
    assert rejected["status"] == CommandStatus.REJECTED.value
    assert rejected["error"]["code"] == "unknown-owner"


def test_landscape_owner_returns_stale_and_legal_transition_outcomes(tmp_path) -> None:
    app = application(tmp_path)
    _, completed = app.execute_command(command_document("1"), authorized=True)

    status, stale = app.execute_command(command_document("1"), authorized=True)
    assert status.value == 409
    assert stale["status"] == CommandStatus.STALE.value
    assert stale["current_revision"] == completed["revision"] == "2"

    _, reopened = app.execute_command(
        command_document("2", operation="reopen"), authorized=True
    )
    assert reopened["revision"] == "3"

    status, invalid = app.execute_command(
        command_document("3", operation="reopen"), authorized=True
    )
    assert status.value == 400
    assert invalid["error"]["code"] == "unavailable-command"


def test_landscape_owner_rejects_foreign_targets_arguments_and_commands(tmp_path) -> None:
    app = application(tmp_path)
    cases = (
        (command_document("1", entity_type="initiative"), "unknown-target"),
        (command_document("1", operation="archive"), "unavailable-command"),
        (command_document("1", arguments={"force": True}), "invalid-arguments"),
    )

    for command, expected_code in cases:
        status, result = app.execute_command(command, authorized=True)
        assert status.value == 400
        assert result["error"]["code"] == expected_code
