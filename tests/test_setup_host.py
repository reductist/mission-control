from __future__ import annotations

import json
import os
import stat
import threading
import tomllib
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mission_control.application_config import load_application_config
from mission_control.cli import main
from mission_control.plugin_api import PluginCallRejected
from mission_control.setup_host import (
    MANAGED_HEADER,
    SetupHostError,
    build_setup_server,
    create_setup_host,
)


def _complete_demo(application):
    state = application.session.state
    state = application.session.act(
        "start",
        {"connection_id": "demo", "label": "Family calendar", "mode": "demo"},
        expected_revision=state["revision"],
    )
    state = application.session.act(
        "select",
        {"calendar_mode": "defaults", "task_mode": "disabled"},
        expected_revision=state["revision"],
    )
    if state["step"]["id"] == "attribution":
        state = application.session.act(
            "assign",
            {field["id"]: [] for field in state["step"]["fields"]},
            expected_revision=state["revision"],
        )
    return application.session.act(
        "finish", {}, expected_revision=state["revision"]
    )


def test_demo_commit_writes_only_managed_fragment_and_normal_config(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    fragment = tmp_path / "fragments" / "50-setup.toml"
    fragment.parent.mkdir()
    application, _token = create_setup_host(
        "google-calendar",
        fragment_dirs=(fragment.parent,),
        managed_fragment=fragment,
        credential_dir=tmp_path / "credentials",
        temporary_root=temporary,
    )
    complete = _complete_demo(application)

    result = application.committer.commit(complete["revision"])

    assert result == {
        "schema_version": "mission-control.setup-commit/v1",
        "plugin_id": "google-calendar",
        "disposition": "managed",
        "restart_required": True,
    }
    assert fragment.read_text(encoding="utf-8").startswith(MANAGED_HEADER + "\n")
    assert stat.S_IMODE(fragment.stat().st_mode) == 0o600
    parsed = tomllib.loads(fragment.read_text(encoding="utf-8"))
    assert parsed["plugins"]["google-calendar"]["settings"]["connections"][
        "demo"
    ]["label"] == "Family calendar"
    effective = load_application_config(fragment_dirs=(fragment.parent,))
    assert effective.enabled_plugin_ids == ("google-calendar",)
    assert not (tmp_path / "mission-control.db").exists()


def test_reconfiguration_preserves_other_managed_configuration_and_validates_it(
    tmp_path, monkeypatch
) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    fragment = tmp_path / "fragments" / "50-setup.toml"
    fragment.parent.mkdir()
    fragment.write_text(
        MANAGED_HEADER
        + "\n"
        + "demo = true\n"
        + '[plugins."landscape"]\n'
        + "enabled = true\n",
        encoding="utf-8",
    )
    application, _token = create_setup_host(
        "google-calendar",
        fragment_dirs=(fragment.parent,),
        managed_fragment=fragment,
        credential_dir=tmp_path / "credentials",
        temporary_root=temporary,
    )
    complete = _complete_demo(application)

    import mission_control.setup_host as setup_host

    real_prepare = setup_host.prepare_application_plugins
    observed = {}

    def capture_candidate(snapshot):
        observed["demo"] = snapshot.demo
        observed["plugins"] = snapshot.enabled_plugin_ids
        return real_prepare(snapshot)

    monkeypatch.setattr(setup_host, "prepare_application_plugins", capture_candidate)

    application.committer.commit(complete["revision"])

    rendered = fragment.read_text(encoding="utf-8")
    assert tomllib.loads(rendered)["demo"] is True
    assert observed == {
        "demo": True,
        "plugins": ("google-calendar", "landscape"),
    }
    effective = load_application_config(fragment_dirs=(fragment.parent,))
    assert effective.demo is True
    assert effective.enabled_plugin_ids == ("google-calendar", "landscape")


def test_external_setup_root_is_persisted_for_final_preflight(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    fragment_dir = tmp_path / "fragments"
    fragment_dir.mkdir()
    root = Path(__file__).parents[1] / "plugins" / "reference"
    application, _token = create_setup_host(
        "reference",
        roots=(root,),
        fragment_dirs=(fragment_dir,),
        managed_fragment=fragment_dir / "reference.toml",
        temporary_root=temporary,
    )
    state = application.session.state
    complete = application.session.act(
        "save",
        {"message": "External setup ready"},
        expected_revision=state["revision"],
    )

    application.committer.commit(complete["revision"])

    effective = load_application_config(fragment_dirs=(fragment_dir,))
    assert str(root.resolve()) in effective.plugin_roots
    assert effective.enabled_plugin_ids == ("reference",)


def test_export_target_cannot_be_a_consumed_fragment(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)

    with pytest.raises(SetupHostError, match="outside configured"):
        create_setup_host(
            "google-calendar",
            fragment_dirs=(tmp_path,),
            managed_fragment=tmp_path / "candidate.toml",
            export_only=True,
            temporary_root=temporary,
        )

    base = tmp_path / "base.toml"
    base.write_text(MANAGED_HEADER + "\ndemo = false\n", encoding="utf-8")
    with pytest.raises(SetupHostError, match="base configuration"):
        create_setup_host(
            "google-calendar",
            base_path=base,
            managed_fragment=base,
            export_only=True,
            temporary_root=temporary,
        )

    real_fragments = tmp_path / "real-fragments"
    real_fragments.mkdir()
    linked_fragments = tmp_path / "linked-fragments"
    linked_fragments.symlink_to(real_fragments, target_is_directory=True)
    with pytest.raises(SetupHostError, match="outside configured"):
        create_setup_host(
            "google-calendar",
            fragment_dirs=(linked_fragments,),
            managed_fragment=real_fragments / "candidate.toml",
            export_only=True,
            temporary_root=temporary,
        )


def test_managed_candidate_is_validated_at_its_actual_layer_position(
    tmp_path,
) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    fragment_dir = tmp_path / "fragments"
    fragment_dir.mkdir()
    managed = fragment_dir / "50-google.toml"
    (fragment_dir / "99-disable.toml").write_text(
        '[plugins."google-calendar"]\nenabled = false\n',
        encoding="utf-8",
    )
    application, _token = create_setup_host(
        "google-calendar",
        fragment_dirs=(fragment_dir,),
        managed_fragment=managed,
        temporary_root=temporary,
    )
    complete = _complete_demo(application)

    with pytest.raises(SetupHostError, match="later configuration"):
        application.committer.commit(complete["revision"])
    assert not managed.exists()


def test_source_symlink_retarget_is_detected_before_commit(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text("demo = false\n", encoding="utf-8")
    second.write_text("demo = true\n", encoding="utf-8")
    link = tmp_path / "current.toml"
    link.symlink_to(first)
    fragment_dir = tmp_path / "fragments"
    fragment_dir.mkdir()
    application, _token = create_setup_host(
        "google-calendar",
        base_path=link,
        fragment_dirs=(fragment_dir,),
        managed_fragment=fragment_dir / "google.toml",
        temporary_root=temporary,
    )
    complete = _complete_demo(application)
    link.unlink()
    link.symlink_to(second)

    with pytest.raises(SetupHostError, match="changed during setup"):
        application.committer.commit(complete["revision"])


def test_managed_credential_names_are_encoded_and_reuse_checks_content(
    tmp_path,
) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    fragment_dir = tmp_path / "fragments"
    fragment_dir.mkdir()
    application, _token = create_setup_host(
        "google-calendar",
        fragment_dirs=(fragment_dir,),
        managed_fragment=fragment_dir / "google.toml",
        credential_dir=tmp_path / "credentials",
        temporary_root=temporary,
    )
    source = temporary / "source"
    source.write_bytes(b"tested credential")
    destination, created = application.committer._publish_credential(
        "../../escape", source
    )
    assert created is True
    assert destination.parent == tmp_path / "credentials"
    destination.write_bytes(b"different bytes")
    os.chmod(destination, 0o600)

    with pytest.raises(SetupHostError, match="does not match"):
        application.committer._publish_credential("../../escape", source)


def test_commit_refuses_operator_owned_output_and_mid_session_config_change(
    tmp_path,
) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    operator_file = tmp_path / "operator.toml"
    operator_file.write_text("demo = false\n", encoding="utf-8")
    with pytest.raises(SetupHostError, match="not owned"):
        create_setup_host(
            "google-calendar",
            fragment_dirs=(tmp_path,),
            managed_fragment=operator_file,
            temporary_root=temporary,
        )

    base = tmp_path / "base.toml"
    base.write_text("demo = false\n", encoding="utf-8")
    application, _token = create_setup_host(
        "google-calendar",
        base_path=base,
        fragment_dirs=(tmp_path,),
        managed_fragment=tmp_path / "managed.toml",
        temporary_root=temporary,
    )
    complete = _complete_demo(application)
    base.write_text("demo = true\n", encoding="utf-8")

    with pytest.raises(SetupHostError, match="changed during setup"):
        application.committer.commit(complete["revision"])
    assert not (tmp_path / "managed.toml").exists()


def test_live_commit_imports_credential_privately_without_exposing_it(
    tmp_path, monkeypatch
) -> None:
    from mission_control.builtin_plugins.google import setup as google_setup
    from mission_control.builtin_plugins.google.fixture import FixtureGoogleClient

    monkeypatch.setattr(
        google_setup,
        "GoogleHttpClient",
        lambda _authorized: FixtureGoogleClient.load(None),
    )
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    application, _token = create_setup_host(
        "google-calendar",
        fragment_dirs=(tmp_path,),
        managed_fragment=tmp_path / "managed.toml",
        credential_dir=tmp_path / "credentials",
        temporary_root=temporary,
    )
    secret = json.dumps(
        {
            "client_id": "client",
            "client_secret": "never-in-config",
            "refresh_token": "refresh",
        }
    ).encode()
    handle = application.registry.upload(secret)
    state = application.session.state
    state = application.session.act(
        "start",
        {"connection_id": "personal", "label": "Personal", "mode": "live"},
        expected_revision=state["revision"],
    )
    state = application.session.act(
        "connect", {"credential": handle}, expected_revision=state["revision"]
    )
    state = application.session.act(
        "select",
        {"calendar_mode": "disabled", "task_mode": "disabled"},
        expected_revision=state["revision"],
    )
    state = application.session.act(
        "finish", {}, expected_revision=state["revision"]
    )

    result = application.committer.commit(state["revision"])

    assert result["disposition"] == "managed"
    credential_files = list((tmp_path / "credentials").iterdir())
    assert len(credential_files) == 1
    assert credential_files[0].read_bytes() == secret
    assert stat.S_IMODE((tmp_path / "credentials").stat().st_mode) == 0o700
    assert stat.S_IMODE(credential_files[0].stat().st_mode) == 0o600
    rendered = (tmp_path / "managed.toml").read_text(encoding="utf-8")
    assert "never-in-config" not in rendered
    assert str(temporary) not in rendered


def test_existing_symlink_credential_reference_is_preserved(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    target = secrets_dir / "generation-1.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o600)
    current = secrets_dir / "current.json"
    current.symlink_to(target.name)
    fragment_dir = tmp_path / "fragments"
    fragment_dir.mkdir()
    fragment = fragment_dir / "google.toml"
    fragment.write_text(
        MANAGED_HEADER
        + "\n"
        + '[plugins."google-calendar"]\n'
        + "enabled = true\n"
        + '[plugins."google-calendar".credentials."oauth-old"]\n'
        + f"file = {json.dumps(str(current))}\n"
        + '[plugins."google-calendar".settings.connections.old]\n'
        + 'label = "Old account"\n'
        + 'mode = "live"\n'
        + 'credential = "oauth-old"\n'
        + '[plugins."google-calendar".settings.connections.old.calendars]\n'
        + 'mode = "disabled"\n'
        + '[plugins."google-calendar".settings.connections.old.tasks]\n'
        + 'mode = "disabled"\n',
        encoding="utf-8",
    )
    application, _token = create_setup_host(
        "google-calendar",
        fragment_dirs=(fragment_dir,),
        managed_fragment=fragment,
        temporary_root=temporary,
    )
    complete = _complete_demo(application)

    application.committer.commit(complete["revision"])

    parsed = tomllib.loads(fragment.read_text(encoding="utf-8"))
    assert (
        parsed["plugins"]["google-calendar"]["credentials"]["oauth-old"]["file"]
        == str(current)
    )


def test_export_only_rejects_new_secret_without_writing(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    application, _token = create_setup_host(
        "google-calendar",
        managed_fragment=tmp_path / "export.toml",
        credential_dir=tmp_path / "credentials",
        temporary_root=temporary,
        export_only=True,
    )
    handle = application.registry.upload(b"not-used-by-demo")
    # A plugin cannot smuggle an uploaded handle through final commit. This
    # focused assertion exercises the core policy without needing live discovery.
    application.registry.record(handle)
    complete = _complete_demo(application)
    draft = application.session._state["draft"]
    draft["credentials"]["oauth"] = {"handle": handle}

    with pytest.raises(SetupHostError, match="export-only"):
        application.committer.commit(complete["revision"])
    assert not (tmp_path / "export.toml").exists()
    assert not (tmp_path / "credentials").exists()


def _request(url: str, *, body: object | bytes | None = None, token=None, origin=None):
    headers = {}
    data = None
    if isinstance(body, bytes):
        data = body
        headers["Content-Type"] = "application/octet-stream"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    return urlopen(Request(url, data=data, headers=headers), timeout=3)


def test_loopback_host_claim_is_one_time_and_responses_are_hardened(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    application, bootstrap = create_setup_host(
        "google-calendar",
        fragment_dirs=(tmp_path,),
        managed_fragment=tmp_path / "managed.toml",
        temporary_root=temporary,
    )
    server = build_setup_server(application)
    host, port = server.server_address
    origin = f"http://{host}:{port}"
    setattr(server, "setup_origin", origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with _request(origin + "/") as response:
            html = response.read().decode()
            assert bootstrap not in html
            assert response.headers["Cache-Control"] == "no-store"
            assert "default-src 'none'" in response.headers["Content-Security-Policy"]

        with pytest.raises(HTTPError) as missing_origin:
            _request(origin + "/api/claim", body={"token": bootstrap})
        assert missing_origin.value.code == 403

        with _request(
            origin + "/api/claim",
            body={"token": bootstrap},
            origin=origin,
        ) as response:
            session_token = json.load(response)["session_token"]
        with pytest.raises(HTTPError) as reused:
            _request(
                origin + "/api/claim",
                body={"token": bootstrap},
                origin=origin,
            )
        assert reused.value.code == 409

        with _request(
            origin + "/api/state",
            body={},
            token=session_token,
            origin=origin,
        ) as response:
            state = json.load(response)
        assert state["schema_version"] == "mission-control.setup-state/v1"

        secret = b'{"client_secret":"never-return"}'
        with _request(
            origin + "/api/credential",
            body=secret,
            token=session_token,
            origin=origin,
        ) as response:
            uploaded = json.load(response)
        assert set(uploaded) == {"handle"}
        assert str(temporary) not in json.dumps(uploaded)
        assert "never-return" not in json.dumps(uploaded)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_setup_server_refuses_non_loopback_bind(tmp_path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir(mode=0o700)
    application, _token = create_setup_host(
        "google-calendar",
        fragment_dirs=(tmp_path,),
        managed_fragment=tmp_path / "managed.toml",
        temporary_root=temporary,
    )

    with pytest.raises(SetupHostError, match="127.0.0.1"):
        build_setup_server(application, host="0.0.0.0")


def test_cli_requires_consumed_fragment_and_uses_config_dir_default(
    tmp_path, capsys, monkeypatch
) -> None:
    assert main(["setup", "google-calendar", "--timeout", "30"]) == 2
    assert "requires --config-dir" in capsys.readouterr().err

    config_dir = tmp_path / "config.d"
    config_dir.mkdir()
    seen = {}

    def fake_run(plugin_id, **kwargs):
        seen.update({"plugin_id": plugin_id, **kwargs})
        kwargs["announce"]("http://127.0.0.1:1234/#token=opaque")
        return {
            "schema_version": "mission-control.setup-commit/v1",
            "plugin_id": plugin_id,
            "disposition": "managed",
            "restart_required": True,
        }

    import mission_control.setup_host as setup_host

    monkeypatch.setattr(setup_host, "run_setup_host", fake_run)
    assert (
        main(
            [
                "--config-dir",
                str(config_dir),
                "setup",
                "google-calendar",
                "--timeout",
                "30",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Open this private setup link" in output
    assert seen["managed_fragment"] == (
        config_dir / "90-mission-control-setup--google-calendar.toml"
    )

    seen.clear()
    assert (
        main(
            [
                "--config-dir",
                str(config_dir),
                "setup",
                "google-calendar",
                "--export-only",
                "--timeout",
                "30",
            ]
        )
        == 0
    )
    assert seen["managed_fragment"] == Path("mission-control.setup.toml")
