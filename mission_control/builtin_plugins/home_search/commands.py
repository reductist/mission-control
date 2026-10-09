"""Revision-checked imports and review decisions for home search."""

from __future__ import annotations

from mission_control.agenda import SourceRef
from mission_control.builtin_plugins.home_search.capabilities import (
    ANNOTATE,
    IMPORT_SNAPSHOT,
    SET_REVIEW_STATUS,
)
from mission_control.builtin_plugins.home_search.domain import (
    HomeSearchSnapshotError,
    ReviewStatus,
    parse_snapshot,
)
from mission_control.builtin_plugins.home_search.repository import (
    PLUGIN_ID,
    SEARCH_ID,
    SQLiteHomeSearchRepository,
    SnapshotRevisionConflictError,
    SnapshotFreshnessRegressionError,
    StaleHomeSearchRevisionError,
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
    thaw_json_object,
)


class HomeSearchCommandOwner:
    def __init__(self, repository: SQLiteHomeSearchRepository) -> None:
        self.repository = repository

    def command_state(self, target: SourceRef) -> CommandTargetState | None:
        if target.plugin_id != PLUGIN_ID:
            return None
        if target.entity_type == "search" and target.entity_id == SEARCH_ID:
            state = self.repository.get_state()
            return CommandTargetState(state.revision, (IMPORT_SNAPSHOT,))
        if target.entity_type != "candidate":
            return None
        try:
            candidate = self.repository.get_candidate(target.entity_id)
        except KeyError:
            return None
        affordances = (ANNOTATE, SET_REVIEW_STATUS) if candidate.current else (ANNOTATE,)
        return CommandTargetState(candidate.revision, affordances)

    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome:
        del context
        if command.target.entity_type == "search":
            return self._import(command)
        if command.target.entity_type == "candidate":
            return self._review(command)
        return self._rejected(command, "unknown-target", "Home-search target not found.")

    def _import(self, command: CommandEnvelope) -> CommandOutcome:
        if command.command != "import-snapshot":
            return self._rejected(
                command, "unknown-command", "Search supports snapshot imports only."
            )
        arguments = thaw_json_object(command.arguments)
        if not isinstance(arguments, dict) or set(arguments) != {"snapshot"}:
            return self._rejected(
                command,
                "invalid-arguments",
                "import-snapshot requires exactly one snapshot object.",
            )
        try:
            snapshot = parse_snapshot(arguments["snapshot"])
            state, changed = self.repository.import_snapshot(
                snapshot, expected_revision=command.expected_revision
            )
        except HomeSearchSnapshotError as error:
            return self._rejected(command, "invalid-snapshot", str(error))
        except SnapshotRevisionConflictError as error:
            return self._rejected(command, "snapshot-revision-conflict", str(error))
        except SnapshotFreshnessRegressionError as error:
            return self._rejected(command, "snapshot-freshness-regression", str(error))
        except StaleHomeSearchRevisionError as error:
            return self._stale(command, error.current_revision)
        return Accepted(
            command.command_id,
            command.target,
            state.revision,
            freeze_json_object(
                {
                    "imported": changed,
                    "source_revision": snapshot.revision,
                    "candidate_count": len(snapshot.candidates),
                }
            ),
        )

    def _review(self, command: CommandEnvelope) -> CommandOutcome:
        if command.command != "set-review-status":
            return self._rejected(
                command,
                "unknown-command",
                "Candidates support review-status updates only.",
            )
        arguments = thaw_json_object(command.arguments)
        if not isinstance(arguments, dict) or set(arguments) != {"status"}:
            return self._rejected(
                command,
                "invalid-arguments",
                "set-review-status requires exactly one status.",
            )
        try:
            status = ReviewStatus(arguments["status"])
        except (TypeError, ValueError):
            return self._rejected(
                command,
                "invalid-review-status",
                "Review status must be unreviewed, shortlisted, or rejected.",
            )
        try:
            updated = self.repository.set_review_status(
                command.target.entity_id,
                status,
                expected_revision=command.expected_revision,
            )
        except KeyError:
            return self._rejected(
                command, "candidate-not-found", "Home candidate not found."
            )
        except StaleHomeSearchRevisionError as error:
            return self._stale(command, error.current_revision)
        return Accepted(
            command.command_id,
            command.target,
            updated.revision,
            freeze_json_object({"review_status": updated.review_status.value}),
        )

    @staticmethod
    def _rejected(command: CommandEnvelope, code: str, detail: str) -> Rejected:
        return Rejected(command.command_id, command.target, CommandError(code, detail))

    @staticmethod
    def _stale(command: CommandEnvelope, revision: str) -> Stale:
        return Stale(
            command.command_id,
            command.target,
            revision,
            CommandError(
                "stale-revision",
                "Home-search data changed after this view loaded; refresh before retrying.",
            ),
        )
