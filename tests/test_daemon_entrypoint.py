from __future__ import annotations

import pytest

import mission_control.server as server
from mission_control.server import build_parser


def test_daemon_parser_uses_canonical_command_name() -> None:
    assert build_parser().prog == "mctrld"


@pytest.mark.parametrize(
    "settings",
    (
        'mode = "invalid"',
        'mode = "demo"\ndemo_anchor_date = "2026-02-31"',
    ),
)
def test_invalid_enabled_plugin_configuration_aborts_before_database_or_import(
    tmp_path, monkeypatch, settings
) -> None:
    database = tmp_path / "mission-control.db"
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
schema_version = "mission-control.config/v2"
[database]
path = "{database}"
[plugins.google-calendar]
enabled = true
[plugins.google-calendar.settings]
{settings}
[plugins.landscape]
enabled = true
""",
        encoding="utf-8",
    )
    imported = False

    def fail_import(_name):
        nonlocal imported
        imported = True
        raise AssertionError("plugin implementation must not be imported")

    monkeypatch.setattr("mission_control.plugin_lifecycle.import_module", fail_import)

    with pytest.raises(SystemExit) as caught:
        server.main(["--config", str(config)])

    assert caught.value.code == 2
    assert not imported
    assert not database.exists()


def test_daemon_consumes_effective_config_and_starts_valid_plugins(
    tmp_path, monkeypatch
) -> None:
    captured = {}
    database = tmp_path / "mission-control.db"
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
schema_version = "mission-control.config/v2"
demo = true
[database]
path = "{database}"
[http]
host = "127.0.0.2"
port = 8123
[plugins.landscape]
enabled = true
""",
        encoding="utf-8",
    )

    class FakeServer:
        server_address = ("127.0.0.2", 8123)

        def serve_forever(self) -> None:
            return None

        def server_close(self) -> None:
            return None

    def fake_build_server(application, host, port):
        captured.update(application=application, host=host, port=port)
        return FakeServer()

    monkeypatch.setattr(server, "build_server", fake_build_server)

    assert server.main(["--config", str(config)]) == 0
    assert captured["host"] == "127.0.0.2"
    assert captured["port"] == 8123
    providers = {
        provider["id"]: provider
        for provider in captured["application"].dashboard()["providers"]
    }
    assert "agenda" in providers["landscape"]["capabilities"]
