"""Landscape-owned command interpretation and state transitions."""

from __future__ import annotations

from enum import StrEnum

from mission_control.commands import (
    Accepted,
    CommandContext,
    CommandEnvelope,
    CommandError,
    CommandOutcome,
    Rejected,
    Stale,
    freeze_json_object,
)
from mission_control.builtin_plugins.landscape.domain import LandscapeActionState
from mission_control.builtin_plugins.landscape.repository import (
    LandscapeRepository,
    StaleLandscapeActionRevisionError,
)


class LandscapeActionCommand(StrEnum):
    COMPLETE = "complete"
    REOPEN = "reopen"


class LandscapeCommandOwner:
    """Authoritative interpreter for Landscape mutation commands."""

    def __init__(self, repository: LandscapeRepository) -> None:
        self.repository = repository

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

        if operation is LandscapeActionCommand.COMPLETE:
            if current.state is LandscapeActionState.DONE:
                return self._rejected(
                    command,
                    "invalid-transition",
                    "A completed Landscape action cannot be completed again.",
                )
            next_state = LandscapeActionState.DONE
        else:
            if current.state is not LandscapeActionState.DONE:
                return self._rejected(
                    command,
                    "invalid-transition",
                    "Only a completed Landscape action can be reopened.",
                )
            next_state = LandscapeActionState.READY

        try:
            updated = self.repository.set_action_state(
                current.action_id,
                next_state,
                expected_revision=command.expected_revision,
            )
        except StaleLandscapeActionRevisionError as error:
            return self._stale(command, error.current_revision)

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
    def _rejected(
        command: CommandEnvelope, code: str, detail: str
    ) -> Rejected:
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
