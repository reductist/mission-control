from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mission_control.commands import (
    Accepted,
    CommandContext,
    CommandContractError,
    CommandError,
    CommandRouter,
    CommandStatus,
    CommandTargetState,
    CoreTaskCommandOwner,
    Failed,
    JsonObject,
    Rejected,
    Stale,
    Unauthorized,
    outcome_to_dict,
    parse_command,
)
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    parse_plugin_registration,
)
from mission_control.tasks import TaskRepository


def command_document(
    task_id: str = "task-1",
    *,
    revision: str = "revision-1",
    plugin_id: str = "core",
) -> dict[str, object]:
    return {
        "schema_version": "mission-control.command/v1",
        "command_id": "command-1",
        "target": {
            "plugin_id": plugin_id,
            "entity_type": "task",
            "entity_id": task_id,
        },
        "expected_revision": revision,
        "command": "set-state",
        "arguments": {"state": "done", "evidence": ["checked", {"safe": True}]},
    }


def repository(tmp_path) -> TaskRepository:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    return TaskRepository(database)


def test_command_parser_freezes_nested_json_and_rejects_unknown_metadata():
    command = parse_command(command_document())

    assert isinstance(command.arguments, JsonObject)
    with pytest.raises(FrozenInstanceError):
        command.command = "changed"  # type: ignore[misc]

    document = command_document()
    document["callback"] = "/api/tasks"
    with pytest.raises(CommandContractError, match="Additional properties"):
        parse_command(document)


def test_router_requires_authorization_and_exactly_one_known_owner(tmp_path):
    repo = repository(tmp_path)
    task = repo.create("Route this command")
    command = parse_command(
        command_document(task.id, revision=task.updated_at, plugin_id="missing")
    )
    router = CommandRouter({"core": CoreTaskCommandOwner(repo)})

    unauthorized = router.dispatch(command, context=None)
    assert isinstance(unauthorized, Unauthorized)
    assert unauthorized.status is CommandStatus.UNAUTHORIZED

    rejected = router.dispatch(command, context=CommandContext("test"))
    assert isinstance(rejected, Rejected)
    assert rejected.error.code == "unknown-owner"


def test_core_task_command_accepts_current_revision_and_rejects_stale_view(tmp_path):
    repo = repository(tmp_path)
    task = repo.create("Complete through owner")
    router = CommandRouter({"core": CoreTaskCommandOwner(repo)})
    current = parse_command(
        {
            **command_document(task.id, revision=task.updated_at),
            "arguments": {"state": "done"},
        }
    )

    accepted = router.dispatch(current, context=CommandContext("test"))
    assert isinstance(accepted, Accepted)
    assert repo.get(task.id).state == "done"
    assert outcome_to_dict(accepted)["status"] == "accepted"

    stale = router.dispatch(current, context=CommandContext("test"))
    assert isinstance(stale, Stale)
    assert stale.current_revision == accepted.revision
    assert outcome_to_dict(stale)["status"] == "stale"


def test_owner_argument_errors_are_structured_rejections(tmp_path):
    repo = repository(tmp_path)
    task = repo.create("Reject bad command")
    router = CommandRouter({"core": CoreTaskCommandOwner(repo)})
    document = command_document(task.id, revision=task.updated_at)
    document["arguments"] = {"state": "archived"}

    outcome = router.dispatch(parse_command(document), context=CommandContext("test"))

    assert isinstance(outcome, Rejected)
    assert outcome.error.code == "invalid-state"


def test_owner_exceptions_are_normalized_without_traceback_details():
    class BrokenOwner:
        def handle(self, command, context):
            raise RuntimeError("secret backend detail")

    command = parse_command(command_document())
    outcome = CommandRouter({"core": BrokenOwner()}).dispatch(
        command, context=CommandContext("test")
    )

    assert isinstance(outcome, Failed)
    document = outcome_to_dict(outcome)
    assert document["error"]["code"] == "owner-failed"  # type: ignore[index]
    assert "secret backend detail" not in str(document)


def test_router_rejects_an_outcome_for_a_different_command():
    class MisroutingOwner:
        def handle(self, command, context):
            return Rejected(
                "different-command",
                command.target,
                CommandError("wrong", "Wrong command identity."),
            )

    command = parse_command(command_document())
    outcome = CommandRouter({"core": MisroutingOwner()}).dispatch(
        command, context=CommandContext("test")
    )

    assert isinstance(outcome, Failed)
    assert outcome.command_id == command.command_id
    assert outcome.target == command.target


def test_router_enforces_registered_and_current_plugin_capabilities():
    registration = parse_plugin_registration(
        {
            "schema_version": "mission-control.plugin/v1",
            "id": "example",
            "name": "Example",
            "version": "1",
            "plugin_api": ">=1 <2",
            "capabilities": ["commands"],
            "entity_types": {
                "action": {"capabilities": ["lifecycle.complete"]}
            },
        }
    )

    class Owner:
        state = CommandTargetState(
            "2",
            (
                EntityAffordance(
                    EntityCapability("lifecycle.complete"), "complete"
                ),
            ),
        )

        def command_state(self, target):
            return self.state

        def handle(self, command, context):
            return Accepted(command.command_id, command.target, "3")

    owner = Owner()
    router = CommandRouter(
        {"example": owner}, registrations={"example": registration}
    )

    document = command_document(plugin_id="example", revision="2")
    document["target"]["entity_type"] = "action"  # type: ignore[index]
    document["command"] = "complete"
    document["arguments"] = {}
    accepted = router.dispatch(
        parse_command(document), context=CommandContext("test")
    )
    assert isinstance(accepted, Accepted)

    stale_document = {**document, "expected_revision": "1", "command": "archive"}
    stale = router.dispatch(
        parse_command(stale_document), context=CommandContext("test")
    )
    assert isinstance(stale, Stale)

    unavailable_document = {**document, "command": "archive"}
    unavailable = router.dispatch(
        parse_command(unavailable_document), context=CommandContext("test")
    )
    assert isinstance(unavailable, Rejected)
    assert unavailable.error.code == "unavailable-command"

    undeclared_document = command_document(plugin_id="example", revision="2")
    undeclared_document["command"] = "complete"
    undeclared_document["arguments"] = {}
    undeclared = router.dispatch(
        parse_command(undeclared_document), context=CommandContext("test")
    )
    assert isinstance(undeclared, Rejected)
    assert undeclared.error.code == "undeclared-target"

    owner.state = CommandTargetState(
        "2",
        (
            EntityAffordance(
                EntityCapability("lifecycle.reopen"), "reopen"
            ),
        ),
    )
    violation = router.dispatch(
        parse_command(document), context=CommandContext("test")
    )
    assert isinstance(violation, Failed)
    assert violation.error.code == "capability-contract-violation"
