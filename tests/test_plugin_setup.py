from __future__ import annotations

from dataclasses import replace
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from mission_control.plugin_api import CapabilityRouter
from mission_control.plugin_lifecycle import (
    PluginLifecycleError,
    create_plugin_setup_session,
    prepare_plugin_setup,
)
from mission_control.plugins import ValidatedPluginConfiguration
from mission_control.setup import DocumentPluginSetup, PluginSetupError, SetupSession


ROOT = Path(__file__).parents[1]


def test_google_demo_setup_is_typed_storage_free_and_core_validated(tmp_path) -> None:
    database = tmp_path / "must-not-exist.db"
    prepared = prepare_plugin_setup("google-calendar")
    session = create_plugin_setup_session(
        prepared,
        credential_paths={},
        principals=({"id": "pat", "label": "Pat"},),
    )

    connection = session.state
    assert connection["step"]["id"] == "connection"
    resources = session.act(
        "start",
        {
            "connection_id": "family",
            "label": "Family Google",
            "mode": "demo",
        },
        expected_revision=connection["revision"],
    )
    assert resources["step"]["id"] == "resources"
    assert resources["notice"]["detail"] == "Found 2 calendars and 2 task lists."

    attribution = session.act(
        "select",
        {
            "calendar_mode": "selected",
            "calendar_ids": ["primary@example.invalid"],
            "task_mode": "disabled",
        },
        expected_revision=resources["revision"],
    )
    assert attribution["step"]["id"] == "attribution"
    owner_field = attribution["step"]["fields"][0]["id"]

    review = session.act(
        "assign",
        {owner_field: ["pat"]},
        expected_revision=attribution["revision"],
    )
    complete = session.act(
        "finish", {}, expected_revision=review["revision"]
    )

    assert complete["complete"] is True
    assert "setup_connection_id" not in complete["draft"]["settings"]
    validated = session.validated_configuration
    assert isinstance(validated, ValidatedPluginConfiguration)
    settings = validated.settings.to_dict()
    assert settings["connections"]["family"]["attribution"] == {
        "calendars": {
            "primary@example.invalid": {"principal_ids": ["pat"]}
        }
    }
    assert not database.exists()


def test_external_reference_plugin_uses_the_same_setup_boundary(tmp_path) -> None:
    database = tmp_path / "must-not-exist.db"
    prepared = prepare_plugin_setup(
        "reference", roots=(ROOT / "plugins" / "reference",)
    )
    session = create_plugin_setup_session(prepared, credential_paths={})

    initial = session.state
    complete = session.act(
        "save",
        {"message": "Reference setup ready"},
        expected_revision=initial["revision"],
    )

    assert complete["complete"] is True
    validated = session.validated_configuration
    assert isinstance(validated, ValidatedPluginConfiguration)
    assert validated.settings.to_dict() == {
        "message": "Reference setup ready",
        "repeat": 1,
    }
    assert not database.exists()


def test_setup_session_enforces_revision_actions_and_declared_fields() -> None:
    def state(_inputs):
        return {
            "schema_version": "mission-control.setup-transition/v1",
            "plugin_id": "reference",
            "draft": {"settings": {}, "credentials": {}},
            "step": {
                "id": "one",
                "title": "One",
                "fields": [],
                "actions": [
                    {
                        "id": "next",
                        "label": "Next",
                        "style": "primary",
                        "intent": "continue",
                    }
                ],
            },
            "complete": False,
        }

    registration = prepare_plugin_setup("google-calendar").registration
    registration = replace(
        registration, plugin_id=registration.plugin_id.__class__("reference")
    )
    provider = DocumentPluginSetup(
        registration,
        CapabilityRouter(
            "reference", {"setup.describe": state, "setup.action": state}
        ),
    )
    session = SetupSession(provider)

    with pytest.raises(PluginSetupError, match="changed"):
        session.act("next", {}, expected_revision="stale")
    with pytest.raises(PluginSetupError, match="not available"):
        session.act("missing", {}, expected_revision="r0")
    with pytest.raises(PluginSetupError, match="unknown field"):
        session.act("next", {"escape": True}, expected_revision="r0")


def test_setup_compare_and_swap_serializes_concurrent_actions() -> None:
    entered = Event()
    release = Event()

    def transition(inputs):
        if "action_id" in inputs:
            entered.set()
            assert release.wait(timeout=2)
        return {
            "schema_version": "mission-control.setup-transition/v1",
            "plugin_id": "reference",
            "draft": {"settings": {}, "credentials": {}},
            "step": {
                "id": "one",
                "title": "One",
                "fields": [],
                "actions": [
                    {
                        "id": "next",
                        "label": "Next",
                        "style": "primary",
                        "intent": "continue",
                    }
                ],
            },
            "complete": False,
        }

    registration = replace(
        prepare_plugin_setup("google-calendar").registration,
        plugin_id=prepare_plugin_setup("google-calendar").registration.plugin_id.__class__(
            "reference"
        ),
    )
    session = SetupSession(
        DocumentPluginSetup(
            registration,
            CapabilityRouter(
                "reference",
                {"setup.describe": transition, "setup.action": transition},
            ),
        )
    )
    revision = session.state["revision"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            session.act, "next", {}, expected_revision=revision
        )
        assert entered.wait(timeout=2)
        second = executor.submit(
            session.act, "next", {}, expected_revision=revision
        )
        release.set()
        outcomes = (first, second)

    successes = [future.result() for future in outcomes if future.exception() is None]
    failures = [future.exception() for future in outcomes if future.exception() is not None]
    assert len(successes) == 1
    assert successes[0]["revision"] == "r1"
    assert len(failures) == 1
    assert isinstance(failures[0], PluginSetupError)
    assert "changed" in str(failures[0])


def test_back_action_does_not_require_incomplete_forward_fields() -> None:
    seen: list[dict[str, object]] = []

    def transition(inputs):
        seen.append(dict(inputs.get("values", {})))
        return {
            "schema_version": "mission-control.setup-transition/v1",
            "plugin_id": "reference",
            "draft": {"settings": {}, "credentials": {}},
            "step": {
                "id": "credential",
                "title": "Credential",
                "fields": [
                    {
                        "id": "credential",
                        "label": "Credential",
                        "widget": "credential-file",
                        "required": True,
                    }
                ],
                "actions": [
                    {
                        "id": "back",
                        "label": "Back",
                        "style": "secondary",
                        "intent": "back",
                    }
                ],
            },
            "complete": False,
        }

    registration = replace(
        prepare_plugin_setup("google-calendar").registration,
        plugin_id=prepare_plugin_setup("google-calendar").registration.plugin_id.__class__(
            "reference"
        ),
    )
    session = SetupSession(
        DocumentPluginSetup(
            registration,
            CapabilityRouter(
                "reference",
                {"setup.describe": transition, "setup.action": transition},
            ),
        )
    )
    state = session.state

    session.act("back", {}, expected_revision=state["revision"])

    assert seen[-1] == {}


def test_live_setup_keeps_paths_and_oauth_values_behind_opaque_handle(
    tmp_path, monkeypatch
) -> None:
    from mission_control.builtin_plugins.google.fixture import FixtureGoogleClient
    from mission_control.builtin_plugins.google import setup as google_setup

    credential = tmp_path / "oauth.json"
    credential.write_text(
        json.dumps(
            {
                "client_id": "client-id",
                "client_secret": "never-in-browser",
                "refresh_token": "refresh-token",
            }
        ),
        encoding="utf-8",
    )
    credential.chmod(0o600)
    monkeypatch.setattr(
        google_setup,
        "GoogleHttpClient",
        lambda _authorized: FixtureGoogleClient.load(None),
    )
    session = create_plugin_setup_session(
        prepare_plugin_setup("google-calendar"),
        credential_paths={"opaque-handle": str(credential)},
    )
    connection = session.state
    authorize = session.act(
        "start",
        {"connection_id": "personal", "label": "Personal", "mode": "live"},
        expected_revision=connection["revision"],
    )
    resources = session.act(
        "connect",
        {"credential": "opaque-handle"},
        expected_revision=authorize["revision"],
    )

    rendered = json.dumps(resources)
    assert str(credential) not in rendered
    assert "never-in-browser" not in rendered
    assert resources["draft"]["credentials"] == {
        "oauth-4a0a339b0c6d": {"handle": "opaque-handle"}
    }


def test_rejected_setup_action_keeps_core_revision_and_can_be_retried(
    tmp_path, monkeypatch
) -> None:
    from mission_control.builtin_plugins.google.fixture import FixtureGoogleClient
    from mission_control.builtin_plugins.google import setup as google_setup
    from mission_control.plugin_api import PluginCallRejected

    credential_paths: dict[str, str] = {}
    session = create_plugin_setup_session(
        prepare_plugin_setup("google-calendar"),
        credential_paths=credential_paths,
    )
    connection = session.state
    authorize = session.act(
        "start",
        {"connection_id": "retry", "label": "Retry", "mode": "live"},
        expected_revision=connection["revision"],
    )
    with pytest.raises(PluginCallRejected, match="no longer available"):
        session.act(
            "connect",
            {"credential": "later"},
            expected_revision=authorize["revision"],
        )
    assert session.state["revision"] == authorize["revision"]

    credential = tmp_path / "oauth.json"
    credential.write_text(
        json.dumps(
            {
                "client_id": "client-id",
                "client_secret": "secret",
                "refresh_token": "refresh",
            }
        ),
        encoding="utf-8",
    )
    credential.chmod(0o600)
    credential_paths["later"] = str(credential)
    monkeypatch.setattr(
        google_setup,
        "GoogleHttpClient",
        lambda _authorized: FixtureGoogleClient.load(None),
    )
    resources = session.act(
        "connect",
        {"credential": "later"},
        expected_revision=authorize["revision"],
    )
    assert resources["step"]["id"] == "resources"


def test_google_setup_rejects_accidental_connection_replacement() -> None:
    session = create_plugin_setup_session(
        prepare_plugin_setup("google-calendar"),
        credential_paths={},
        settings={
            "connections": {
                "existing": {
                    "label": "Existing",
                    "mode": "demo",
                    "calendars": {"mode": "disabled"},
                    "tasks": {"mode": "disabled"},
                }
            }
        },
    )
    state = session.state

    from mission_control.plugin_api import PluginCallRejected

    with pytest.raises(PluginCallRejected, match="already exists"):
        session.act(
            "start",
            {"connection_id": "existing", "label": "Replace", "mode": "demo"},
            expected_revision=state["revision"],
        )


def test_default_calendar_attribution_uses_google_selected_metadata() -> None:
    from mission_control.builtin_plugins.google.setup import GoogleCalendarSetup
    from mission_control.plugin_api import PluginSetupContext

    flow = GoogleCalendarSetup(
        PluginSetupContext.create(
            plugin_id="google-calendar",
            credential_resolver=lambda _handle: "unused",
        )
    )
    flow._calendars = (
        ("shown", "Shown", True),
        ("hidden", "Hidden", False),
    )
    draft = {
        "settings": {
            "setup_connection_id": "demo",
            "connections": {
                "demo": {
                    "label": "Demo",
                    "mode": "demo",
                    "calendars": {"mode": "disabled"},
                    "tasks": {"mode": "disabled"},
                }
            },
        },
        "credentials": {},
    }

    state = flow._select(
        draft,
        {"calendar_mode": "defaults", "task_mode": "disabled"},
        [{"id": "pat", "label": "Pat"}],
    )

    labels = [field["label"] for field in state["step"]["fields"]]
    assert labels == ["Who owns Shown?"]


def test_non_setup_plugin_is_rejected_before_database_or_runtime(tmp_path) -> None:
    database = tmp_path / "must-not-exist.db"

    with pytest.raises(PluginLifecycleError, match="does not declare a setup"):
        prepare_plugin_setup("landscape")

    assert not database.exists()


def test_credential_resolver_does_not_appear_in_setup_context_repr(tmp_path) -> None:
    from mission_control.plugin_api import PluginSetupContext

    secret_path = str(Path(tmp_path) / "do-not-print.json")
    context = PluginSetupContext.create(
        plugin_id="reference", credential_resolver=lambda _handle: secret_path
    )

    assert secret_path not in repr(context)
