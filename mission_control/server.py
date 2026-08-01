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
from urllib.parse import urlsplit

from . import __version__
from .agenda import (
    AgendaContribution,
    agenda_to_list,
    aggregate_agenda,
    project_core_tasks,
)
from .builtin_plugins import (
    BUILTIN_AGENDA_PLUGIN_IDS,
    BuiltinPluginError,
    PreparedBuiltinAgendaPlugin,
    activate_builtin_agenda_plugins,
    prepare_builtin_agenda_plugins,
)
from .commands import (
    CommandContext,
    CommandContractError,
    CommandRouter,
    CommandStatus,
    CoreTaskCommandOwner,
    outcome_to_dict,
    parse_command,
)
from .database import Database
from .migrations import MigrationRunner
from .tasks import TASK_STATES, Task, TaskRepository

MAX_REQUEST_BYTES = 64 * 1024
_TASK_PATH = re.compile(r"^/api/tasks/([^/]+)$")
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
        builtin_plugins: Iterable[PreparedBuiltinAgendaPlugin] = (),
    ) -> None:
        MigrationRunner(database).apply()
        self.repository = TaskRepository(database)
        self.command_router = CommandRouter(
            {"core": CoreTaskCommandOwner(self.repository)}
        )
        self.demo = demo
        self.write_token = write_token or secrets.token_urlsafe(24)
        self.agenda_contributions = tuple(agenda_contributions)
        self.agenda_providers = activate_builtin_agenda_plugins(
            database, tuple(builtin_plugins)
        )
        self._demo_fixture = _load_demo_fixture() if demo else None
        if demo:
            _seed_demo_tasks(self.repository)

    def dashboard(self) -> dict[str, object]:
        tasks = self.repository.list()
        active = [task for task in tasks if task.state != "done"]
        generated_at = datetime.now(UTC)
        agenda = aggregate_agenda(
            (
                project_core_tasks(tasks, generated_at=generated_at),
                *self.agenda_contributions,
                *(
                    provider.contribution(generated_at=generated_at)
                    for provider in self.agenda_providers
                ),
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
                "completed": sum(task.state == "done" for task in tasks),
            },
            "tasks": [_task_to_dict(task) for task in _sort_tasks(tasks)],
            "agenda": agenda_to_list(agenda),
            "demo": self._demo_fixture,
        }

    def create_task(self, document: object) -> dict[str, object]:
        payload = _object_payload(document, allowed={"title", "description"})
        title = payload.get("title")
        description = payload.get("description", "")
        if not isinstance(title, str):
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid-title", "title must be a string")
        if not isinstance(description, str):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid-description",
                "description must be a string",
            )
        try:
            return _task_to_dict(self.repository.create(title, description))
        except (TypeError, ValueError) as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid-task", str(error)) from error

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
            raise ApiError(HTTPStatus.NOT_FOUND, "task-not-found", "task not found") from error
        except (TypeError, ValueError) as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid-task", str(error)) from error

    def execute_command(
        self, document: object, *, authorized: bool
    ) -> tuple[HTTPStatus, dict[str, object]]:
        try:
            command = parse_command(document)
        except CommandContractError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid-command", str(error)) from error

        context = CommandContext(actor="local-write-token") if authorized else None
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
                    {"status": "ok", "version": __version__},
                )
                return
            if path == "/api/dashboard":
                self._send_json(HTTPStatus.OK, application.dashboard())
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
                self._send_error(ApiError(HTTPStatus.NOT_FOUND, "not-found", "not found"))
                return
            self._handle_mutation(lambda payload: application.create_task(payload))

        def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler interface
            match = _TASK_PATH.fullmatch(urlsplit(self.path).path)
            if match is None:
                self._send_error(ApiError(HTTPStatus.NOT_FOUND, "not-found", "not found"))
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
                raise ApiError(HTTPStatus.BAD_REQUEST, "empty-body", "JSON body is required")
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
        choices=BUILTIN_AGENDA_PLUGIN_IDS,
        default=[],
        help="load a bundled read-only agenda provider; may be repeated",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        builtin_plugins = prepare_builtin_agenda_plugins(args.plugin)
    except BuiltinPluginError as error:
        parser.error(str(error))
    try:
        application = MissionControlApplication(
            Database(Path(args.database)),
            demo=args.demo,
            builtin_plugins=builtin_plugins,
        )
    except BuiltinPluginError as error:
        parser.error(str(error))
    server = build_server(application, args.host, args.port)
    host, port = server.server_address[:2]
    mode = "demo" if args.demo else "live"
    print(f"Mission Control {__version__} ({mode}) listening on http://{host}:{port}")
    if host not in {"127.0.0.1", "::1", "localhost"}:
        print("warning: the MVP server has no user authentication; expose it only on a trusted network")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
