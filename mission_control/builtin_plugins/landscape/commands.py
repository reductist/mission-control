"""Landscape-owned command interpretation and state transitions."""

from __future__ import annotations

from enum import StrEnum

from mission_control.agenda import SourceRef
from mission_control.builtin_plugins.landscape.capabilities import action_affordances
from mission_control.builtin_plugins.landscape.domain import LandscapeInvariantError
from mission_control.builtin_plugins.landscape.repository import (
    PLUGIN_ID,
    LandscapeRepository,
    StaleLandscapeActionRevisionError,
)
from mission_control.commands import (
    Accepted,
    CommandContext,
    CommandEnvelope,
    CommandError,
    CommandOutcome,
    CommandTargetState,
    Rejected,
    Stale,
    freeze_json_object,
)


class LandscapeActionCommand(StrEnum):
    COMPLETE = "complete"
    REOPEN = "reopen"


class LandscapeCommandOwner:
    """Authoritative interpreter for Landscape mutation commands."""

    def __init__(self, repository: LandscapeRepository) -> None:
        self.repository = repository

    def command_state(self, target: SourceRef) -> CommandTargetState | None:
        """Resolve current state for core's capability and revision checks."""

        if target.plugin_id != PLUGIN_ID or target.entity_type != "action":
            return None
        try:
            action = self.repository.get_action(target.entity_id)
        except KeyError:
            return None
        return CommandTargetState(action.revision, action_affordances(action))

    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome:
        del context  # Actor-aware event attribution remains tracked in issue #4.
        if command.target.entity_type != "action":
            return self._rejected(
                command,
                "unknown-target",
                "Landscape commands support action targets only.",
            )
        try:
            operation = LandscapeActionCommand(command.command)
        except ValueError:
            return self._rejected(
                command,
                "unknown-command",
                f"Landscape actions do not support command {command.command!r}.",
            )
        if command.arguments.values:
            return self._rejected(
                command,
                "invalid-arguments",
                f"{operation.value} does not accept arguments.",
            )

        try:
            current = self.repository.get_action(command.target.entity_id)
        except KeyError:
            return self._rejected(
                command, "action-not-found", "Landscape action not found."
            )

        if command.expected_revision != current.revision:
            return self._stale(command, current.revision)

        try:
            if operation is LandscapeActionCommand.COMPLETE:
                updated = self.repository.complete_action(
                    current.action_id,
                    expected_revision=command.expected_revision,
                )
            else:
                updated = self.repository.reopen_action(
                    current.action_id,
                    expected_revision=command.expected_revision,
                )
        except StaleLandscapeActionRevisionError as error:
            return self._stale(command, error.current_revision)
        except LandscapeInvariantError as error:
            detail = f"{error.detail[:1].upper()}{error.detail[1:]}."
            return self._rejected(command, error.code, detail)

        return Accepted(
            command.command_id,
            command.target,
            updated.revision,
            freeze_json_object(
                {
                    "action": {
                        "id": updated.action_id,
                        "state": updated.state.value,
                        "revision": updated.revision,
                    }
                }
            ),
        )

    @staticmethod
    def _rejected(command: CommandEnvelope, code: str, detail: str) -> Rejected:
        return Rejected(
            command.command_id,
            command.target,
            CommandError(code, detail),
        )

    @staticmethod
    def _stale(command: CommandEnvelope, current_revision: str) -> Stale:
        return Stale(
            command.command_id,
            command.target,
            current_revision,
            CommandError(
                "stale-revision",
                "The Landscape action changed after this view was loaded; "
                "refresh before retrying.",
            ),
        )
