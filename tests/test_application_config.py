from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_control.application_config import (
    ApplicationConfigError,
    load_application_config,
    prepare_application_plugins,
)


def _write(path: Path, document: str) -> Path:
    path.write_text(document, encoding="utf-8")
    return path


def test_defaults_are_packaged_and_snapshot_is_detached() -> None:
    snapshot = load_application_config()

    assert snapshot.database_path == "mission-control.db"
    assert snapshot.host == "127.0.0.1"
    assert snapshot.port == 8000
    assert snapshot.enabled_plugin_ids == ()

    mutable = snapshot.to_dict()
    mutable["database"] = {"path": "changed.db"}
    assert snapshot.database_path == "mission-control.db"


def test_base_and_lexical_fragments_deep_merge_with_source_chains(tmp_path) -> None:
    base = _write(
        tmp_path / "config.toml",
        """
schema_version = "mission-control.config/v1"
plugin_roots = ["base"]

[http]
host = "127.0.0.2"

[plugins.google]
enabled = false

[plugins.google.settings]
mode = "demo"
""",
    )
    fragments = tmp_path / "conf.d"
    fragments.mkdir()
    _write(
        fragments / "20-http.toml",
        """
plugin_roots = ["replacement"]
[http]
port = 9000
""",
    )
    _write(
        fragments / "10-google.toml",
        """
[plugins.google]
enabled = true
[plugins.google.settings]
demo_anchor_date = "2026-08-14"
""",
    )

    snapshot = load_application_config(base_path=base, fragment_dirs=(fragments,))

    assert snapshot.host == "127.0.0.2"
    assert snapshot.port == 9000
    assert snapshot.plugin_roots == ("replacement",)
    assert snapshot.plugin_settings()["google"] == {
        "demo_anchor_date": "2026-08-14",
        "mode": "demo",
    }
    assert snapshot.explain("/http/port").sources == (
        "defaults",
        str((fragments / "20-http.toml").resolve()),
    )
    assert snapshot.explain("/plugins/google/enabled").sources == (
        str(base.resolve()),
        str((fragments / "10-google.toml").resolve()),
    )
    assert snapshot.explain("/http").sources == (
        "defaults",
        str(base.resolve()),
        str((fragments / "20-http.toml").resolve()),
    )
    assert snapshot.explain("/plugin_roots/0").value == "replacement"
    assert snapshot.explain("/plugin_roots/0").sources == (
        "defaults",
        str(base.resolve()),
        str((fragments / "20-http.toml").resolve()),
    )


def test_explain_rejects_invalid_json_pointer_escapes() -> None:
    snapshot = load_application_config()

    with pytest.raises(ApplicationConfigError, match="invalid JSON Pointer escape"):
        snapshot.explain("/http/~2port")


def test_incompatible_layer_types_name_both_sources(tmp_path) -> None:
    base = _write(
        tmp_path / "config.toml",
        'schema_version = "mission-control.config/v1"\n[http]\nport = 8001\n',
    )
    fragments = tmp_path / "conf.d"
    fragments.mkdir()
    fragment = _write(fragments / "10-bad.toml", 'http = "not-a-table"\n')

    with pytest.raises(ApplicationConfigError) as caught:
        load_application_config(base_path=base, fragment_dirs=(fragments,))

    message = str(caught.value)
    assert "configuration type conflict at http" in message
    assert str(base.resolve()) in message
    assert str(fragment.resolve()) in message


def test_malformed_toml_is_attributed_to_its_file(tmp_path) -> None:
    path = _write(tmp_path / "broken.toml", "[http\nport = 8000\n")

    with pytest.raises(ApplicationConfigError) as caught:
        load_application_config(base_path=path)

    assert f"invalid TOML in {path.resolve()}" in str(caught.value)


@pytest.mark.parametrize(
    "body, expected",
    (
        ('unexpected = true\n', "Additional properties are not allowed"),
        ('[http]\nport = 70000\n', "greater than the maximum"),
        ('[plugins.Bad_ID]\nenabled = false\n', "does not match"),
        (
            '[plugins.google]\nenabled = false\n'
            '[plugins.google.credentials."oauth:prod"]\nfile = "/run/value"\n',
            "does not match",
        ),
        ('[plugins.google]\n', "'enabled' is a required property"),
        ('value = 2026-08-17\n', "date is not a valid JSON configuration value"),
        ('value = inf\n', "non-finite numbers are not valid JSON"),
    ),
)
def test_invalid_outer_configuration_is_rejected(
    tmp_path, body: str, expected: str
) -> None:
    path = _write(
        tmp_path / "config.toml",
        'schema_version = "mission-control.config/v1"\n' + body,
    )

    with pytest.raises(ApplicationConfigError, match=expected):
        load_application_config(base_path=path)


def test_disabled_unavailable_plugin_is_preserved_but_not_prepared(tmp_path) -> None:
    path = _write(
        tmp_path / "config.toml",
        """
schema_version = "mission-control.config/v1"
[plugins.unavailable]
enabled = false
[plugins.unavailable.settings]
future_field = "preserved"
""",
    )

    snapshot = load_application_config(base_path=path)

    assert prepare_application_plugins(snapshot) == ()
    assert snapshot.to_dict()["plugins"] == {
        "unavailable": {
            "enabled": False,
            "settings": {"future_field": "preserved"},
        }
    }


def test_null_is_not_in_the_portable_toml_configuration_value_set() -> None:
    with pytest.raises(ApplicationConfigError, match="not valid under any"):
        load_application_config(
            overrides={
                "plugins": {
                    "google": {
                        "enabled": False,
                        "settings": {"unsupported": None},
                    }
                }
            }
        )


def test_enabled_plugin_configuration_is_validated_before_activation(tmp_path) -> None:
    path = _write(
        tmp_path / "config.toml",
        """
schema_version = "mission-control.config/v1"
[plugins.google]
enabled = true
[plugins.google.settings]
mode = "invalid"
""",
    )

    snapshot = load_application_config(base_path=path)

    with pytest.raises(ApplicationConfigError, match="google: mode"):
        prepare_application_plugins(snapshot)


def test_credential_references_and_sensitive_settings_are_redacted(tmp_path) -> None:
    credential = _write(tmp_path / "oauth.json", json.dumps({"token": "secret"}))
    path = _write(
        tmp_path / "config.toml",
        f"""
schema_version = "mission-control.config/v1"
[plugins.google]
enabled = false
[plugins.google.credentials.oauth]
file = "{credential}"
[plugins.google.settings]
api_token = "must-not-appear"
""",
    )

    snapshot = load_application_config(base_path=path)
    redacted = snapshot.to_dict(redacted=True)

    assert redacted["plugins"]["google"]["credentials"] == {  # type: ignore[index]
        "oauth": {"file": "<redacted>"}
    }
    assert redacted["plugins"]["google"]["settings"] == "<redacted>"  # type: ignore[index]
    assert snapshot.explain(
        "/plugins/google/credentials/oauth/file"
    ).value == "<redacted>"


def test_all_opaque_plugin_settings_are_redacted_not_just_secret_like_names(
    tmp_path,
) -> None:
    path = _write(
        tmp_path / "config.toml",
        """
schema_version = "mission-control.config/v1"
[plugins.unavailable]
enabled = false
[plugins.unavailable.settings]
api_key = "must-not-appear"
authorization = "must-not-appear-either"
ordinary_name = "also-hidden-until-the-plugin-schema-marks-it-safe"
""",
    )

    rendered = json.dumps(
        load_application_config(base_path=path).to_dict(redacted=True)
    )

    assert "must-not-appear" not in rendered
    assert "also-hidden" not in rendered


def test_enabled_credential_reference_must_be_available(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    path = _write(
        tmp_path / "config.toml",
        f"""
schema_version = "mission-control.config/v1"
[plugins.google]
enabled = true
[plugins.google.settings]
mode = "live"
[plugins.google.credentials.oauth]
file = "{missing}"
""",
    )

    snapshot = load_application_config(base_path=path)

    with pytest.raises(ApplicationConfigError, match="credential file is unavailable"):
        prepare_application_plugins(snapshot)


def test_enabled_credential_reference_must_not_be_broadly_readable(tmp_path) -> None:
    credential = _write(tmp_path / "oauth.json", "{}")
    credential.chmod(0o640)
    path = _write(
        tmp_path / "config.toml",
        f"""
schema_version = "mission-control.config/v1"
[plugins.google]
enabled = true
[plugins.google.settings]
mode = "live"
[plugins.google.credentials.oauth]
file = "{credential}"
""",
    )

    snapshot = load_application_config(base_path=path)

    with pytest.raises(ApplicationConfigError, match="must not be accessible"):
        prepare_application_plugins(snapshot)
