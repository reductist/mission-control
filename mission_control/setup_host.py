"""Loopback-only browser host for renderer-neutral plugin setup."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from mission_control.application_config import (
    ApplicationConfigError,
    ApplicationConfigSnapshot,
    load_application_config,
    prepare_application_plugins,
)
from mission_control.plugin_api import (
    PluginCallContractError,
    PluginCallRejected,
    validate_capability_document,
)
from mission_control.plugin_lifecycle import (
    PluginLifecycleError,
    create_plugin_setup_session,
    prepare_plugin_setup,
)
from mission_control.plugins import ValidatedPluginConfiguration
from mission_control.setup import PluginSetupError, SetupSession


MANAGED_HEADER = "# Managed by mcctl setup. Put manual changes in another fragment."
MAX_JSON_BYTES = 256 * 1024
MAX_CREDENTIAL_BYTES = 1024 * 1024


class SetupHostError(ValueError):
    """The explicit setup host cannot continue safely."""


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    path: Path
    uploaded: bool


class CredentialRegistry:
    """Server-side handle registry; paths never enter setup documents."""

    def __init__(self, temporary_root: Path) -> None:
        self.temporary_root = temporary_root
        self._records: dict[str, CredentialRecord] = {}

    def register_existing(self, path: str | Path) -> str:
        handle = _handle()
        self._records[handle] = CredentialRecord(Path(path), False)
        return handle

    def upload(self, content: bytes) -> str:
        if not content:
            raise SetupHostError("credential upload is empty")
        if len(content) > MAX_CREDENTIAL_BYTES:
            raise SetupHostError("credential upload exceeds the 1 MiB limit")
        handle = _handle()
        path = self.temporary_root / f"credential-{handle}.bin"
        _atomic_bytes(path, content, mode=0o600)
        self._records[handle] = CredentialRecord(path, True)
        return handle

    def resolve(self, handle: str) -> str:
        try:
            return str(self._records[handle].path)
        except KeyError as error:
            raise ValueError("unknown credential handle") from error

    def record(self, handle: str) -> CredentialRecord:
        try:
            return self._records[handle]
        except KeyError as error:
            raise SetupHostError("setup draft contains an unknown credential handle") from error


class SetupCommitter:
    """Validate and atomically publish one wizard-owned configuration fragment."""

    def __init__(
        self,
        *,
        plugin_id: str,
        snapshot: ApplicationConfigSnapshot,
        session: SetupSession,
        registry: CredentialRegistry,
        base_path: str | Path | None,
        fragment_dirs: Sequence[str | Path],
        managed_fragment: Path,
        credential_dir: Path,
        export_only: bool,
        persisted_plugin_roots: Sequence[str] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.snapshot = snapshot
        self.session = session
        self.registry = registry
        self.base_path = (
            _lexical_absolute(Path(base_path)) if base_path is not None else None
        )
        self.fragment_dirs = tuple(
            _lexical_absolute(Path(item)) for item in fragment_dirs
        )
        self.managed_fragment = _lexical_absolute(managed_fragment)
        self.credential_dir = _lexical_absolute(credential_dir)
        self.export_only = export_only
        self.persisted_plugin_roots = (
            tuple(persisted_plugin_roots)
            if persisted_plugin_roots is not None
            else None
        )
        self._watched = self._source_fingerprints()
        self._validate_managed_target()

    def commit(self, expected_revision: str) -> dict[str, object]:
        state = self.session.state
        if state["revision"] != expected_revision:
            raise SetupHostError("setup state changed; refresh and try again")
        if state["complete"] is not True:
            raise SetupHostError("setup is not complete")
        validated = self.session.validated_configuration
        if not isinstance(validated, ValidatedPluginConfiguration):
            raise SetupHostError("completed setup has no validated configuration")
        if self._source_fingerprints() != self._watched:
            raise SetupHostError(
                "configuration changed during setup; restart setup before committing"
            )
        commit_result = validate_capability_document(
            {
                "schema_version": "mission-control.setup-commit/v1",
                "plugin_id": self.plugin_id,
                "disposition": "exported" if self.export_only else "managed",
                "restart_required": not self.export_only,
            },
            "setup-commit.schema.json",
            "setup commit result",
        )

        draft = cast(Mapping[str, object], state["draft"])
        raw_credentials = cast(Mapping[str, object], draft["credentials"])
        credential_paths: dict[str, str] = {}
        created: list[Path] = []
        try:
            for name, reference in sorted(raw_credentials.items()):
                if not isinstance(reference, Mapping) or not isinstance(
                    reference.get("handle"), str
                ):
                    raise SetupHostError("setup draft contains an invalid credential")
                record = self.registry.record(cast(str, reference["handle"]))
                if record.uploaded:
                    if self.export_only:
                        raise SetupHostError(
                            "export-only setup cannot publish uploaded credentials; "
                            "configure an operator-managed credential reference instead"
                        )
                    destination, was_created = self._publish_credential(
                        name, record.path
                    )
                    if was_created:
                        created.append(destination)
                    credential_paths[name] = str(destination)
                else:
                    credential_paths[name] = str(record.path)

            block: dict[str, object] = {
                "enabled": True,
                "settings": validated.settings.to_dict(),
            }
            if credential_paths:
                block["credentials"] = {
                    name: {"file": path}
                    for name, path in sorted(credential_paths.items())
                }
            fragment = self._replacement_document(block)
            rendered = MANAGED_HEADER + "\n" + _toml_document(fragment)
            parsed = tomllib.loads(rendered)
            if parsed != fragment:
                raise SetupHostError("managed configuration serialization mismatch")

            if self.export_only:
                effective = load_application_config(
                    base_path=self.base_path,
                    fragment_dirs=self.fragment_dirs,
                    overrides=fragment,
                )
            else:
                effective = load_application_config(
                    base_path=self.base_path,
                    fragment_dirs=self.fragment_dirs,
                    fragment_replacements={self.managed_fragment: fragment},
                )
                if self.plugin_id not in effective.enabled_plugin_ids:
                    raise SetupHostError(
                        "later configuration overrides this setup and leaves the "
                        "plugin disabled"
                    )
            prepare_application_plugins(effective)
            if self._source_fingerprints() != self._watched:
                raise SetupHostError(
                    "configuration changed during setup; restart setup before committing"
                )
            _atomic_bytes(
                self.managed_fragment,
                rendered.encode("utf-8"),
                mode=0o600,
            )
        except Exception:
            for path in created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return commit_result

    def _replacement_document(self, block: Mapping[str, object]) -> dict[str, object]:
        document: dict[str, object] = {}
        if self.managed_fragment.exists():
            try:
                parsed = tomllib.loads(
                    self.managed_fragment.read_text(encoding="utf-8")
                )
            except (OSError, tomllib.TOMLDecodeError) as error:
                raise SetupHostError(
                    "managed configuration fragment is unreadable"
                ) from error
            document = cast(dict[str, object], json.loads(json.dumps(parsed)))
        raw_plugins = document.setdefault("plugins", {})
        if not isinstance(raw_plugins, dict):
            raise SetupHostError(
                "managed configuration fragment has an invalid plugins table"
            )
        raw_plugins[self.plugin_id] = dict(block)
        if self.persisted_plugin_roots is not None:
            document["plugin_roots"] = list(self.persisted_plugin_roots)
        return document

    def _publish_credential(self, name: str, source: Path) -> tuple[Path, bool]:
        self._prepare_credential_dir()
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()[:16]
        plugin_key = hashlib.sha256(self.plugin_id.encode("utf-8")).hexdigest()[:12]
        name_key = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        destination = self.credential_dir / (
            f"credential--{plugin_key}--{name_key}--{digest}.bin"
        )
        if destination.is_symlink():
            raise SetupHostError("managed credential target must not be a symlink")
        if not destination.exists():
            _atomic_bytes(destination, content, mode=0o600)
            created = True
        else:
            _require_private_file(destination)
            if not hmac.compare_digest(destination.read_bytes(), content):
                raise SetupHostError(
                    "managed credential target does not match the tested credential"
                )
            created = False
        return destination, created

    def _prepare_credential_dir(self) -> None:
        _reject_symlink_components(self.credential_dir)
        if self.credential_dir.is_symlink():
            raise SetupHostError("managed credential directory must not be a symlink")
        self.credential_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        mode = stat.S_IMODE(self.credential_dir.stat().st_mode)
        if mode & 0o077:
            raise SetupHostError(
                "managed credential directory must not be accessible by group or others"
            )

    def _validate_managed_target(self) -> None:
        _reject_symlink_components(self.managed_fragment.parent)
        if self.managed_fragment.suffix != ".toml":
            raise SetupHostError("managed configuration fragment must use .toml")
        if self.base_path is not None and (
            self.managed_fragment.resolve() == self.base_path.resolve()
        ):
            raise SetupHostError(
                "setup output must not replace the operator-owned base configuration"
            )
        if (
            not self.export_only
            and self.managed_fragment.parent not in self.fragment_dirs
        ):
            raise SetupHostError(
                "managed configuration fragment must be inside a configured "
                "--config-dir so the service will consume it"
            )
        configured_directories = {path.resolve() for path in self.fragment_dirs}
        if (
            self.export_only
            and self.managed_fragment.parent.resolve() in configured_directories
        ):
            raise SetupHostError(
                "export-only output must be outside configured fragment directories"
            )
        if self.managed_fragment.is_symlink():
            raise SetupHostError("managed configuration fragment must not be a symlink")
        if self.managed_fragment.exists():
            try:
                first = self.managed_fragment.read_text(encoding="utf-8").splitlines()[0]
            except (OSError, IndexError) as error:
                raise SetupHostError("managed configuration fragment is unreadable") from error
            if first != MANAGED_HEADER:
                raise SetupHostError(
                    "refusing to overwrite a configuration file not owned by mcctl setup"
                )

    def _source_fingerprints(self) -> tuple[tuple[str, str], ...]:
        paths: set[Path] = set()
        if self.base_path is not None:
            paths.add(self.base_path)
        for directory in self.fragment_dirs:
            if directory.is_dir():
                paths.update(directory.glob("*.toml"))
        paths.add(self.managed_fragment)
        return tuple(
            (str(path), _file_fingerprint(path))
            for path in sorted(paths, key=lambda item: str(item))
        )


class SetupHostApplication:
    """One expiring browser session and its core-owned commit boundary."""

    def __init__(
        self,
        *,
        session: SetupSession,
        registry: CredentialRegistry,
        committer: SetupCommitter,
        bootstrap_token: str,
        expires_at: float,
    ) -> None:
        self.session = session
        self.registry = registry
        self.committer = committer
        self._bootstrap_token: str | None = bootstrap_token
        self._session_token: str | None = None
        self.expires_at = expires_at
        self.committed = False
        self.commit_result: dict[str, object] | None = None

    def claim(self, token: str) -> str:
        self._require_live()
        if self._bootstrap_token is None or not hmac.compare_digest(
            token, self._bootstrap_token
        ):
            raise SetupHostError("setup invitation is invalid or already used")
        self._bootstrap_token = None
        self._session_token = secrets.token_urlsafe(32)
        return self._session_token

    def authorize(self, authorization: str | None) -> None:
        self._require_live()
        prefix = "Bearer "
        supplied = authorization[len(prefix) :] if authorization and authorization.startswith(prefix) else ""
        if self._session_token is None or not hmac.compare_digest(
            supplied, self._session_token
        ):
            raise SetupHostError("setup session authorization is required")

    def _require_live(self) -> None:
        if time.monotonic() >= self.expires_at:
            raise SetupHostError("setup session expired")


def create_setup_host(
    plugin_id: str,
    *,
    base_path: str | Path | None = None,
    fragment_dirs: Sequence[str | Path] = (),
    roots: Sequence[str | Path] = (),
    managed_fragment: str | Path = "mission-control.setup.toml",
    credential_dir: str | Path = "mission-control.credentials",
    export_only: bool = False,
    timeout_seconds: int = 900,
    temporary_root: Path,
) -> tuple[SetupHostApplication, str]:
    if timeout_seconds < 30 or timeout_seconds > 3600:
        raise SetupHostError("setup timeout must be between 30 and 3600 seconds")
    snapshot = load_application_config(
        base_path=base_path, fragment_dirs=fragment_dirs
    )
    document = snapshot.to_dict()
    plugins = cast(Mapping[str, object], document["plugins"])
    block = cast(Mapping[str, object], plugins.get(plugin_id, {}))
    settings = cast(Mapping[str, object], block.get("settings", {}))
    configured = cast(Mapping[str, object], block.get("credentials", {}))
    workspace = cast(Mapping[str, object], document["workspace"])
    raw_principals = cast(Mapping[str, object], workspace.get("principals", {}))
    principals = tuple(
        {"id": principal_id, "label": cast(Mapping[str, str], value)["label"]}
        for principal_id, value in sorted(raw_principals.items())
    )

    extra_roots = tuple(str(_lexical_absolute(Path(item))) for item in roots)
    effective_roots = tuple(dict.fromkeys((*snapshot.plugin_roots, *extra_roots)))
    prepared = prepare_plugin_setup(plugin_id, roots=effective_roots)
    registry = CredentialRegistry(temporary_root)
    configured_handles: dict[str, str] = {}
    for name, reference in sorted(configured.items()):
        if not isinstance(reference, Mapping) or not isinstance(
            reference.get("file"), str
        ):
            raise SetupHostError("configured credential reference is invalid")
        configured_handles[name] = registry.register_existing(
            cast(str, reference["file"])
        )
    session = create_plugin_setup_session(
        prepared,
        credential_paths=_CredentialPathView(registry),
        settings=settings,
        configured_credentials=configured_handles,
        principals=principals,
    )
    token = secrets.token_urlsafe(32)
    committer = SetupCommitter(
        plugin_id=plugin_id,
        snapshot=snapshot,
        session=session,
        registry=registry,
        base_path=base_path,
        fragment_dirs=fragment_dirs,
        managed_fragment=Path(managed_fragment),
        credential_dir=Path(credential_dir),
        export_only=export_only,
        persisted_plugin_roots=effective_roots if extra_roots else None,
    )
    return (
        SetupHostApplication(
            session=session,
            registry=registry,
            committer=committer,
            bootstrap_token=token,
            expires_at=time.monotonic() + timeout_seconds,
        ),
        token,
    )


class _CredentialPathView(Mapping[str, str]):
    """Dynamic mapping used by the existing setup-session resolver closure."""

    def __init__(self, registry: CredentialRegistry) -> None:
        self.registry = registry

    def __getitem__(self, handle: str) -> str:
        return self.registry.resolve(handle)

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0


def build_setup_server(
    application: SetupHostApplication, host: str = "127.0.0.1", port: int = 0
) -> HTTPServer:
    if host != "127.0.0.1":
        raise SetupHostError("setup server must bind to 127.0.0.1")
    server = HTTPServer((host, port), _handler_for(application))
    server.timeout = 0.5
    return server


def run_setup_host(
    plugin_id: str,
    *,
    base_path: str | Path | None = None,
    fragment_dirs: Sequence[str | Path] = (),
    roots: Sequence[str | Path] = (),
    managed_fragment: str | Path = "mission-control.setup.toml",
    credential_dir: str | Path = "mission-control.credentials",
    export_only: bool = False,
    port: int = 0,
    timeout_seconds: int = 900,
    announce: Callable[[str], None] = print,
) -> dict[str, object] | None:
    with tempfile.TemporaryDirectory(prefix="mission-control-setup-") as root:
        temporary_root = Path(root)
        application, token = create_setup_host(
            plugin_id,
            base_path=base_path,
            fragment_dirs=fragment_dirs,
            roots=roots,
            managed_fragment=managed_fragment,
            credential_dir=credential_dir,
            export_only=export_only,
            timeout_seconds=timeout_seconds,
            temporary_root=temporary_root,
        )
        server = build_setup_server(application, port=port)
        host, actual_port = server.server_address[:2]
        origin = f"http://{host}:{actual_port}"
        setattr(server, "setup_origin", origin)
        announce(f"{origin}/#token={token}")
        try:
            while not application.committed and time.monotonic() < application.expires_at:
                server.handle_request()
        finally:
            server.server_close()
        return application.commit_result


def _handler_for(application: SetupHostApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MissionControlSetup"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        @property
        def origin(self) -> str:
            return cast(str, getattr(self.server, "setup_origin"))

        def do_GET(self) -> None:  # noqa: N802
            if not self._valid_host():
                self._error(HTTPStatus.BAD_REQUEST, "invalid-host", "Invalid setup host.")
                return
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            }
            asset = assets.get(self.path)
            if asset is None:
                self._error(HTTPStatus.NOT_FOUND, "not-found", "Not found.")
                return
            content = files("mission_control").joinpath("setup_web", asset[0]).read_bytes()
            self._send(HTTPStatus.OK, content, asset[1])

        def do_POST(self) -> None:  # noqa: N802
            if not self._valid_host() or self.headers.get("Origin") != self.origin:
                self._error(
                    HTTPStatus.FORBIDDEN,
                    "origin-required",
                    "Setup requests must come from this loopback page.",
                )
                return
            try:
                if self.path == "/api/claim":
                    body = self._json_body()
                    token = body.get("token")
                    if not isinstance(token, str):
                        raise SetupHostError("setup invitation token is required")
                    self._json(HTTPStatus.OK, {"session_token": application.claim(token)})
                    return
                application.authorize(self.headers.get("Authorization"))
                if self.path == "/api/state":
                    self._json(HTTPStatus.OK, application.session.state)
                    return
                if self.path == "/api/action":
                    body = self._json_body()
                    action_id = body.get("action_id")
                    revision = body.get("expected_revision")
                    values = body.get("values", {})
                    if (
                        not isinstance(action_id, str)
                        or not isinstance(revision, str)
                        or not isinstance(values, Mapping)
                    ):
                        raise SetupHostError("setup action request is invalid")
                    self._json(
                        HTTPStatus.OK,
                        application.session.act(
                            action_id,
                            cast(Mapping[str, object], values),
                            expected_revision=revision,
                        ),
                    )
                    return
                if self.path == "/api/credential":
                    if self.headers.get("Content-Type") != "application/octet-stream":
                        raise SetupHostError(
                            "credential content type must be application/octet-stream"
                        )
                    content = self._body(MAX_CREDENTIAL_BYTES)
                    handle = application.registry.upload(content)
                    self._json(HTTPStatus.CREATED, {"handle": handle})
                    return
                if self.path == "/api/commit":
                    body = self._json_body()
                    revision = body.get("expected_revision")
                    if not isinstance(revision, str):
                        raise SetupHostError("setup revision is required")
                    result = application.committer.commit(revision)
                    application.commit_result = result
                    application.committed = True
                    self._json(HTTPStatus.OK, result)
                    return
                self._error(HTTPStatus.NOT_FOUND, "not-found", "Not found.")
            except PluginCallRejected as error:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, error.code, error.detail)
            except (PluginSetupError, SetupHostError) as error:
                self._error(
                    HTTPStatus.CONFLICT,
                    "setup-rejected",
                    str(error),
                )
            except (
                ApplicationConfigError,
                OSError,
                PluginCallContractError,
                PluginLifecycleError,
            ):
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "setup-failed",
                    "Setup could not be validated or saved safely.",
                )
            except Exception:
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "setup-failed",
                    "Setup failed unexpectedly; no configuration was committed.",
                )

        def _valid_host(self) -> bool:
            return self.headers.get("Host") == self.origin.removeprefix("http://")

        def _json_body(self) -> dict[str, object]:
            if not self.headers.get("Content-Type", "").startswith(
                "application/json"
            ):
                raise SetupHostError("request content type must be application/json")
            content = self._body(MAX_JSON_BYTES)
            try:
                document = json.loads(content)
            except json.JSONDecodeError as error:
                raise SetupHostError("request body must be valid JSON") from error
            if not isinstance(document, dict):
                raise SetupHostError("request body must be a JSON object")
            return document

        def _body(self, limit: int) -> bytes:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None or not raw_length.isdigit():
                raise SetupHostError("request content length is required")
            length = int(raw_length)
            if length < 0 or length > limit:
                raise SetupHostError("request body is too large")
            return self.rfile.read(length)

        def _json(self, status: HTTPStatus, document: Mapping[str, object]) -> None:
            self._send(
                status,
                json.dumps(document, sort_keys=True).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _error(
            self, status: HTTPStatus, code: str, detail: str
        ) -> None:
            self._json(status, {"error": {"code": code, "detail": detail}})

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _toml_document(document: Mapping[str, object]) -> str:
    lines: list[str] = []

    def table(path: tuple[str, ...], value: Mapping[str, object]) -> None:
        if path:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append("[" + ".".join(_toml_key(part) for part in path) + "]")
        scalars = {
            key: item for key, item in value.items() if not isinstance(item, Mapping)
        }
        children = {
            key: item for key, item in value.items() if isinstance(item, Mapping)
        }
        for key, item in sorted(scalars.items()):
            lines.append(f"{_toml_key(key)} = {_toml_value(item)}")
        for key, child in sorted(children.items()):
            table((*path, key), cast(Mapping[str, object], child))

    table((), document)
    return "\n".join(lines).lstrip("\n") + "\n"


def _toml_key(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, Mapping):
        return "{ " + ", ".join(
            f"{_toml_key(str(key))} = {_toml_value(item)}"
            for key, item in sorted(value.items())
        ) + " }"
    raise SetupHostError(f"unsupported TOML configuration value: {type(value).__name__}")


def _atomic_bytes(path: Path, content: bytes, *, mode: int) -> None:
    _reject_symlink_components(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SetupHostError("refusing to replace a managed symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _require_private_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise SetupHostError("managed credential target is not a regular file")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SetupHostError("managed credential file has unsafe permissions")


def _file_fingerprint(path: Path) -> str:
    if not path.exists():
        return "broken-symlink" if path.is_symlink() else "missing"
    if path.is_symlink():
        try:
            target = os.readlink(path)
            resolved = path.resolve(strict=True)
            if not resolved.is_file():
                return f"symlink:{target}:unsafe"
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            return f"symlink:{target}:{resolved}:{digest}"
        except OSError:
            return "unreadable-symlink"
    if not path.is_file():
        return "unsafe"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _handle() -> str:
    return secrets.token_hex(18)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise SetupHostError("managed path must not contain symlinks")
