"""Minimal HTTP server and browser shell for Mission Control."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from mission_control import __version__
from mission_control.agenda import (
    AgendaContribution,
    SourceRef,
    agenda_to_list,
    aggregate_agenda,
    project_core_tasks,
    validate_agenda_capabilities,
)
from mission_control.annotations import (
    AnnotationCommandHandler,
    AnnotationLifecycleCommandHandler,
    AnnotationRepository,
)
from mission_control.commands import (
    CommandContext,
    CommandContractError,
    CommandRouter,
    CommandStatus,
    CoreTaskCommandOwner,
    EntityTypeCommandOwner,
    outcome_to_dict,
    parse_command,
)
from mission_control.closed_items import (
    ClosedItemsContribution,
    aggregate_closed_items,
    closed_items_to_list,
    project_core_closed_items,
    validate_closed_items_capabilities,
)
from mission_control.database import Database
from mission_control.entity_details import (
    compose_entity_detail,
    entity_detail_to_dict,
    validate_entity_detail_capabilities,
)
from mission_control.migrations import MigrationRunner
from mission_control.plugin_runtime import PluginJobSupervisor
from mission_control.plugin_lifecycle import (
    PluginLifecycleError,
    PreparedAgendaPlugin,
    activate_agenda_plugins_isolated,
    prepare_agenda_plugins,
)
from mission_control.plugins import (
    EntityCapability,
    PluginId,
    StandardEntityCapability,
    entity_type_registration,
)
from mission_control.tasks import TASK_STATES, Task, TaskRepository

MAX_REQUEST_BYTES = 64 * 1024
_TASK_PATH = re.compile(r"^/api/tasks/([^/]+)$")
_ENTITY_PATH = re.compile(r"^/api/entities/([^/]+)/([^/]+)/([^/]+)$")
_STATIC_ASSETS = {
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
_DEMO_TASKS = (
    (
        "Compare two home purchase scenarios",
        "Capture the trade-offs that matter before discussing individual listings.",
        "in-progress",
    ),
)


class ApiError(Exception):
    """An expected client-facing HTTP error."""

    def __init__(self, status: HTTPStatus, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


class MissionControlApplication:
    """Application shell shared by the HTTP adapter and tests."""

    def __init__(
        self,
        database: Database,
        *,
        demo: bool = False,
        write_token: str | None = None,
        agenda_contributions: Iterable[AgendaContribution] = (),
        builtin_plugins: Iterable[PreparedAgendaPlugin] = (),
        plugin_failures: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        MigrationRunner(database).apply()
        self.repository = TaskRepository(database)
        self.annotation_repository = AnnotationRepository(database)
        self.demo = demo
        self.write_token = write_token or secrets.token_urlsafe(24)
        self.agenda_contributions = tuple(agenda_contributions)
        self.builtin_plugins = tuple(builtin_plugins)
        self.plugin_activations = activate_agenda_plugins_isolated(
            database, self.builtin_plugins
        )
        self.active_plugins = tuple(
            (activation.plugin, activation.provider)
            for activation in self.plugin_activations
            if activation.provider is not None
        )
        self.failed_plugin_activations = {
            activation.plugin.registration.plugin_id.value: activation.failure
            for activation in self.plugin_activations
            if activation.failure is not None
        }
        self.initial_plugin_failures = dict(plugin_failures or {})
        self.agenda_providers = tuple(provider for _, provider in self.active_plugins)
        self.registrations = {
            plugin.registration.plugin_id.value: plugin.registration
            for plugin in self.builtin_plugins
        }
        self.entity_detail_providers = {
            provider.plugin_id.value: provider
            for provider in self.agenda_providers
            if callable(getattr(provider, "entity_detail", None))
        }
        command_owners = {
            "core": EntityTypeCommandOwner(
                {
                    "task": CoreTaskCommandOwner(self.repository),
                    "annotation": AnnotationLifecycleCommandHandler(
                        self.annotation_repository
                    ),
                }
            )
        }
        command_owners.update(
            {
                provider.plugin_id.value: provider.command_owner
                for provider in self.agenda_providers
                if provider.command_owner is not None
            }
        )
        self.command_router = CommandRouter(
            command_owners,
            registrations=self.registrations,
            capability_handlers={
                "entity.annotate": AnnotationCommandHandler(self.annotation_repository)
            },
            entity_type_capabilities={
                ("core", "annotation"): (
                    EntityCapability(StandardEntityCapability.LIFECYCLE_DISMISS.value),
                    EntityCapability(StandardEntityCapability.LIFECYCLE_REOPEN.value),
                )
            },
        )
        self.job_supervisor = PluginJobSupervisor(
            job
            for provider in self.agenda_providers
            for job in (
                provider.jobs() if callable(getattr(provider, "jobs", None)) else ()
            )
        )
        self._last_agenda_contributions: dict[str, AgendaContribution] = {}
        self._last_closed_contributions: dict[str, ClosedItemsContribution] = {}
        self._provider_runtime_failures: dict[str, tuple[str, str]] = {}
        self._demo_fixture = _load_demo_fixture() if demo else None
        if demo:
            _seed_demo_tasks(self.repository)

    def start(self) -> None:
        """Start provider jobs only after every plugin has initialized."""

        self.job_supervisor.start()

    def stop(self) -> None:
        """Stop provider jobs before the application is discarded."""

        self.job_supervisor.stop()
        for provider in reversed(self.agenda_providers):
            stop = getattr(provider, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    # Shutdown is best-effort and must continue for other providers.
                    continue

    def health(self) -> dict[str, object]:
        plugins = self._plugin_health()
        degraded = any(item["state"] in {"degraded", "failed"} for item in plugins)
        return {
            "status": "degraded" if degraded else "ok",
            "version": __version__,
            "plugins": plugins,
        }

    def dashboard(self) -> dict[str, object]:
        tasks = self.repository.list()
        active = [task for task in tasks if task.state != "done"]
        generated_at = datetime.now(UTC)
        builtin_contributions = self._agenda_contributions(generated_at)

        closed_contributions = [
            project_core_closed_items(tasks, generated_at=generated_at)
        ]
        for plugin, provider in self.active_plugins:
            project_closed = getattr(provider, "closed_items", None)
            if not callable(project_closed):
                continue
            plugin_id = plugin.registration.plugin_id.value
            try:
                contribution = project_closed(generated_at=generated_at)
                validate_closed_items_capabilities(plugin.registration, contribution)
            except Exception:
                self._provider_runtime_failures[plugin_id] = (
                    "closed-items-read-failed",
                    "Provider history failed; the last available view was retained.",
                )
                if plugin_id in self._last_closed_contributions:
                    closed_contributions.append(
                        self._last_closed_contributions[plugin_id]
                    )
            else:
                self._last_closed_contributions[plugin_id] = contribution
                closed_contributions.append(contribution)
        closed_items = aggregate_closed_items(closed_contributions)

        agenda = aggregate_agenda(
            (
                project_core_tasks(tasks, generated_at=generated_at),
                *self.agenda_contributions,
                *builtin_contributions,
            )
        )
        return {
            "version": __version__,
            "generated_at": generated_at.isoformat(),
            "mode": "demo" if self.demo else "live",
            "summary": {
                "open": len(active),
                "in_progress": sum(task.state == "in-progress" for task in tasks),
                "blocked": sum(task.blocked for task in active),
                "completed": len(closed_items.items),
            },
            "tasks": [_task_to_dict(task) for task in _sort_tasks(tasks)],
            "agenda": agenda_to_list(agenda),
            "closed_items": closed_items_to_list(closed_items),
            "providers": self._provider_documents(),
            "demo": self._demo_fixture,
        }

    def _agenda_contributions(
        self, generated_at: datetime
    ) -> tuple[AgendaContribution, ...]:
        contributions: list[AgendaContribution] = []
        for plugin, provider in self.active_plugins:
            plugin_id = plugin.registration.plugin_id.value
            try:
                contribution = provider.contribution(generated_at=generated_at)
                validate_agenda_capabilities(plugin.registration, contribution)
            except Exception:
                self._provider_runtime_failures[plugin_id] = (
                    "agenda-read-failed",
                    "Provider agenda failed; the last available view was retained.",
                )
                if plugin_id in self._last_agenda_contributions:
                    contributions.append(self._last_agenda_contributions[plugin_id])
            else:
                self._last_agenda_contributions[plugin_id] = contribution
                self._provider_runtime_failures.pop(plugin_id, None)
                contributions.append(contribution)
        return tuple(contributions)

    def _plugin_health(self) -> list[dict[str, object]]:
        documents: list[dict[str, object]] = [
            self._failed_plugin_health(plugin_id, code, detail)
            for plugin_id, (code, detail) in sorted(
                self.initial_plugin_failures.items()
            )
        ] + [
            self._failed_plugin_health(
                plugin_id,
                failure.code,
                failure.detail,
            )
            for plugin_id, failure in sorted(self.failed_plugin_activations.items())
        ]
        for plugin, provider in self.active_plugins:
            plugin_id = plugin.registration.plugin_id.value
            if plugin_id in self._provider_runtime_failures:
                code, detail = self._provider_runtime_failures[plugin_id]
                documents.append(self._failed_plugin_health(plugin_id, code, detail))
                continue
            health = getattr(provider, "health", None)
            if not callable(health):
                continue
            try:
                document = health().to_dict()
                if document.get("plugin_id") != plugin_id:
                    raise ValueError(
                        "provider health identity does not match registration"
                    )
            except Exception:
                document = self._failed_plugin_health(
                    plugin_id,
                    "health-read-failed",
                    "Provider health could not be read safely.",
                )
            documents.append(document)
        return documents

    @staticmethod
    def _failed_plugin_health(
        plugin_id: str, code: str, detail: str
    ) -> dict[str, object]:
        return {
            "plugin_id": plugin_id,
            "state": "failed",
            "code": code,
            "detail": detail,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def _provider_documents(self) -> list[dict[str, object]]:
        health = {item["plugin_id"]: item for item in self._plugin_health()}
        documents = [
            {
                "id": registration.plugin_id.value,
                "name": registration.name,
                "capabilities": [item.value for item in registration.capabilities],
                **(
                    {"health": health[registration.plugin_id.value]}
                    if registration.plugin_id.value in health
                    else {}
                ),
            }
            for registration in sorted(
                self.registrations.values(), key=lambda item: item.plugin_id.value
            )
        ]
        registered = set(self.registrations)
        documents.extend(
            {
                "id": plugin_id,
                "name": plugin_id,
                "capabilities": [],
                "health": health[plugin_id],
            }
            for plugin_id in sorted(set(health) - registered)
        )
        return documents

    def create_task(self, document: object) -> dict[str, object]:
        payload = _object_payload(document, allowed={"title", "description"})
        title = payload.get("title")
        description = payload.get("description", "")
        if not isinstance(title, str):
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid-title", "title must be a string"
            )
        if not isinstance(description, str):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid-description",
                "description must be a string",
            )
        try:
            return _task_to_dict(self.repository.create(title, description))
        except (TypeError, ValueError) as error:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid-task", str(error)
            ) from error

    def update_task(self, task_id: str, document: object) -> dict[str, object]:
        payload = _object_payload(
            document,
            allowed={"state", "blocked", "waiting_on", "review_after"},
        )
        if not payload:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "empty-update",
                "at least one supported field is required",
            )
        state = payload.get("state")
        if state is not None and state not in TASK_STATES:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid-state",
                f"state must be one of: {', '.join(TASK_STATES)}",
            )
        try:
            return _task_to_dict(self.repository.update(task_id, **payload))
        except KeyError as error:
            raise ApiError(
                HTTPStatus.NOT_FOUND, "task-not-found", "task not found"
            ) from error
        except (TypeError, ValueError) as error:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid-task", str(error)
            ) from error

    def execute_command(
        self, document: object, *, authorized: bool
    ) -> tuple[HTTPStatus, dict[str, object]]:
        try:
            command = parse_command(document)
        except CommandContractError as error:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid-command", str(error)
            ) from error

        context = CommandContext(actor="local-operator") if authorized else None
        outcome = self.command_router.dispatch(command, context=context)
        status = {
            CommandStatus.ACCEPTED: HTTPStatus.OK,
            CommandStatus.REJECTED: HTTPStatus.BAD_REQUEST,
            CommandStatus.CONFLICTED: HTTPStatus.CONFLICT,
            CommandStatus.STALE: HTTPStatus.CONFLICT,
            CommandStatus.UNAUTHORIZED: HTTPStatus.FORBIDDEN,
            CommandStatus.FAILED: HTTPStatus.INTERNAL_SERVER_ERROR,
        }[outcome.status]
        return status, outcome_to_dict(outcome)

    def entity_detail(
        self, plugin_id: str, entity_type: str, entity_id: str
    ) -> dict[str, object]:
        target = SourceRef(PluginId(plugin_id), entity_type, entity_id)
        provider = self.entity_detail_providers.get(plugin_id)
        registration = self.registrations.get(plugin_id)
        if provider is None or registration is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "entity-not-found",
                "entity detail is not available",
            )
        project = getattr(provider, "entity_detail")
        detail = project(target)
        if detail is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "entity-not-found",
                "entity detail is not available",
            )
        validate_entity_detail_capabilities(
            registration, detail, expected_source=target
        )
        declared = entity_type_registration(registration, entity_type)
        assert declared is not None
        can_read_activity = any(
            capability.value == StandardEntityCapability.ACTIVITY_READ.value
            for capability in declared.capabilities
        )
        composed = compose_entity_detail(
            detail,
            self.annotation_repository.list(target) if can_read_activity else (),
            self.annotation_repository.status_history(target)
            if can_read_activity
            else (),
        )
        validate_entity_detail_capabilities(
            registration,
            composed,
            allow_core_notes=True,
            expected_source=target,
        )
        return entity_detail_to_dict(composed)

    def index_document(self) -> bytes:
        source = _web_resource("index.html").read_text(encoding="utf-8")
        rendered = source.replace(
            "__MC_WRITE_TOKEN__",
            html.escape(self.write_token, quote=True),
        ).replace("__MC_MODE__", "demo" if self.demo else "live")
        return rendered.encode("utf-8")


class MissionControlHTTPServer(ThreadingHTTPServer):
    """Threaded development server with prompt shutdown behavior."""

    daemon_threads = True
    allow_reuse_address = True


def build_server(
    application: MissionControlApplication,
    host: str,
    port: int,
) -> MissionControlHTTPServer:
    """Bind the HTTP adapter for one application instance."""

    handler = _handler_for(application)
    return MissionControlHTTPServer((host, port), handler)


def _handler_for(application: MissionControlApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"MissionControl/{__version__}"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler interface
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                self._send_bytes(
                    HTTPStatus.OK,
                    application.index_document(),
                    "text/html; charset=utf-8",
                )
                return
            if path == "/api/health":
                self._send_json(
                    HTTPStatus.OK,
                    application.health(),
                )
                return
            if path == "/api/dashboard":
                self._send_json(HTTPStatus.OK, application.dashboard())
                return
            entity_match = _ENTITY_PATH.fullmatch(path)
            if entity_match is not None:
                try:
                    segments = tuple(unquote(part) for part in entity_match.groups())
                    if any(not part or "/" in part for part in segments):
                        raise ApiError(
                            HTTPStatus.BAD_REQUEST,
                            "invalid-entity-reference",
                            "entity reference contains unsupported characters",
                        )
                    self._send_json(
                        HTTPStatus.OK,
                        application.entity_detail(*segments),
                    )
                except ApiError as error:
                    self._send_error(error)
                return
            asset = _STATIC_ASSETS.get(path)
            if asset is not None:
                name, content_type = asset
                self._send_bytes(
                    HTTPStatus.OK,
                    _web_resource(name).read_bytes(),
                    content_type,
                )
                return
            self._send_error(ApiError(HTTPStatus.NOT_FOUND, "not-found", "not found"))

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler interface
            path = urlsplit(self.path).path
            if path == "/api/commands":
                self._handle_command()
                return
            if path != "/api/tasks":
                self._send_error(
                    ApiError(HTTPStatus.NOT_FOUND, "not-found", "not found")
                )
                return
            self._handle_mutation(lambda payload: application.create_task(payload))

        def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler interface
            match = _TASK_PATH.fullmatch(urlsplit(self.path).path)
            if match is None:
                self._send_error(
                    ApiError(HTTPStatus.NOT_FOUND, "not-found", "not found")
                )
                return
            task_id = match.group(1)
            self._handle_mutation(
                lambda payload: application.update_task(task_id, payload)
            )

        def _handle_mutation(self, operation) -> None:
            try:
                self._require_write_token(application.write_token)
                payload = self._read_json()
                result = operation(payload)
            except ApiError as error:
                self._send_error(error)
                return
            self._send_json(HTTPStatus.OK, result)

        def _handle_command(self) -> None:
            try:
                payload = self._read_json()
                supplied = self.headers.get("X-Mission-Control-Token", "")
                authorized = secrets.compare_digest(supplied, application.write_token)
                status, result = application.execute_command(
                    payload, authorized=authorized
                )
            except ApiError as error:
                self._send_error(error)
                return
            self._send_json(status, result)

        def _require_write_token(self, expected: str) -> None:
            supplied = self.headers.get("X-Mission-Control-Token", "")
            if not secrets.compare_digest(supplied, expected):
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "write-token-required",
                    "a valid same-origin write token is required",
                )

        def _read_json(self) -> object:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("application/json"):
                raise ApiError(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    "json-required",
                    "Content-Type must be application/json",
                )
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "0")
            except ValueError as error:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "invalid-content-length",
                    "invalid Content-Length header",
                ) from error
            if length <= 0:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST, "empty-body", "JSON body is required"
                )
            if length > MAX_REQUEST_BYTES:
                raise ApiError(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "request-too-large",
                    "request body is too large",
                )
            try:
                return json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "invalid-json",
                    "request body must contain valid JSON",
                ) from error

        def _send_error(self, error: ApiError) -> None:
            self._send_json(
                error.status,
                {"error": {"code": error.code, "detail": error.detail}},
            )

        def _send_json(self, status: HTTPStatus, document: object) -> None:
            body = json.dumps(document, sort_keys=True).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8")

        def _send_bytes(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            # Keep stdlib request logging, but attach the product name consistently.
            super().log_message(f"mission-control: {format}", *args)

    return Handler


def _object_payload(document: object, *, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "object-required",
            "request body must be a JSON object",
        )
    unknown = sorted(key for key in document if key not in allowed)
    if unknown:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "unknown-fields",
            f"unsupported fields: {', '.join(unknown)}",
        )
    return dict(document)


def _task_to_dict(task: Task) -> dict[str, object]:
    return asdict(task)


def _sort_tasks(tasks: list[Task]) -> list[Task]:
    state_order = {"in-progress": 0, "ready": 1, "backlog": 2, "done": 3}
    return sorted(
        tasks,
        key=lambda task: (
            state_order[task.state],
            not task.blocked,
            task.title.casefold(),
            task.id,
        ),
    )


def _seed_demo_tasks(repository: TaskRepository) -> None:
    existing = {task.title: task for task in repository.list()}
    for title, description, state in _DEMO_TASKS:
        task = existing.get(title)
        if task is None:
            task = repository.create(title, description)
        changes: dict[str, object] = {}
        if task.description != description:
            changes["description"] = description
        if task.state != state:
            changes["state"] = state
        if changes:
            repository.update(task.id, **changes)


def _load_demo_fixture() -> dict[str, object]:
    document = json.loads(_web_resource("demo.json").read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("packaged demo fixture must be a JSON object")
    return document


def _web_resource(name: str):
    return files("mission_control.web").joinpath(name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mctrld")
    parser.add_argument(
        "--database",
        default=os.environ.get("MC_DATABASE", "mission-control.db"),
        help="SQLite database path (default: %(default)s)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MC_HOST", "127.0.0.1"),
        help="listen address (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MC_PORT", "8000")),
        help="listen port (default: %(default)s)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="load the synthetic House fixture and seed its example task",
    )
    parser.add_argument(
        "--plugin",
        action="append",
        default=[],
        metavar="PLUGIN_ID",
        help="load a bundled provider by its manifest ID; may be repeated",
    )
    parser.add_argument(
        "--plugin-root",
        action="append",
        default=[],
        metavar="PATH",
        help="discover additional plugin manifests/resources below PATH; may be repeated",
    )
    parser.add_argument(
        "--plugin-settings",
        action="append",
        default=[],
        metavar="PLUGIN_ID=PATH",
        help="read one plugin's non-secret JSON settings; may be repeated",
    )
    parser.add_argument(
        "--plugin-credential",
        action="append",
        default=[],
        metavar="PLUGIN_ID.NAME=PATH",
        help="provide one named credential file to a plugin; may be repeated",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        configurations = _plugin_settings(args.plugin_settings)
        credentials = _plugin_credentials(args.plugin_credential)
        selected = set(args.plugin)
        unexpected = sorted((set(configurations) | set(credentials)) - selected)
        if unexpected:
            raise ValueError(
                "configuration supplied for unselected plugins: "
                + ", ".join(unexpected)
            )
        if len(selected) != len(args.plugin):
            raise ValueError("plugin selected more than once")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    builtin_plugins: list[PreparedAgendaPlugin] = []
    plugin_failures: dict[str, tuple[str, str]] = {}
    for plugin_id in args.plugin:
        try:
            builtin_plugins.extend(
                prepare_agenda_plugins(
                    (plugin_id,),
                    roots=args.plugin_root,
                    configurations=configurations,
                    credentials=credentials,
                )
            )
        except (PluginLifecycleError, OSError, ValueError):
            plugin_failures[plugin_id] = (
                "preparation-failed",
                "Plugin validation failed; its contributions are unavailable.",
            )
    application = MissionControlApplication(
        Database(Path(args.database)),
        demo=args.demo,
        builtin_plugins=builtin_plugins,
        plugin_failures=plugin_failures,
    )
    server = build_server(application, args.host, args.port)
    host, port = server.server_address[:2]
    showcase = "house showcase enabled" if args.demo else "operational workspace"
    print(
        f"Mission Control {__version__} ({showcase}) listening on http://{host}:{port}"
    )
    if host not in {"127.0.0.1", "::1", "localhost"}:
        print(
            "warning: the MVP server has no user authentication; expose it only on a trusted network"
        )
    try:
        application.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.stop()
    return 0


def _plugin_settings(values: Iterable[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for value in values:
        plugin_id, path = _assignment(value, "--plugin-settings")
        if plugin_id in result:
            raise ValueError(f"plugin settings supplied more than once: {plugin_id}")
        try:
            result[plugin_id] = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{plugin_id}: invalid settings JSON at line {error.lineno}, "
                f"column {error.colno}"
            ) from error
    return result


def _plugin_credentials(values: Iterable[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for value in values:
        identity, path = _assignment(value, "--plugin-credential")
        if "." not in identity:
            raise ValueError("--plugin-credential identity must use PLUGIN_ID.NAME")
        plugin_id, name = identity.split(".", 1)
        if not plugin_id or not name:
            raise ValueError("--plugin-credential identity must use PLUGIN_ID.NAME")
        plugin_credentials = result.setdefault(plugin_id, {})
        if name in plugin_credentials:
            raise ValueError(
                f"plugin credential supplied more than once: {plugin_id}.{name}"
            )
        plugin_credentials[name] = path
    return result


def _assignment(value: str, option: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"{option} must use NAME=PATH")
    name, path = value.split("=", 1)
    if not name or not path:
        raise ValueError(f"{option} must use NAME=PATH")
    return name, path


if __name__ == "__main__":
    raise SystemExit(main())
