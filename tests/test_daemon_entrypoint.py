from __future__ import annotations

import mission_control.server as server
from mission_control.server import build_parser


def test_daemon_parser_uses_canonical_command_name() -> None:
    assert build_parser().prog == "mctrld"


def test_invalid_google_configuration_is_isolated_from_daemon_and_healthy_plugin(
    tmp_path, monkeypatch
) -> None:
    captured = {}

    class FakeServer:
        server_address = ("127.0.0.1", 8000)

        def serve_forever(self) -> None:
            return None

        def server_close(self) -> None:
            return None

    def fake_build_server(application, _host, _port):
        captured["application"] = application
        return FakeServer()

    monkeypatch.setattr(server, "build_server", fake_build_server)

    assert (
        server.main(
            [
                "--database",
                str(tmp_path / "mission-control.db"),
                "--demo",
            "--plugin",
            "google",
            "--plugin",
            "landscape",
            ]
        )
        == 0
    )

    dashboard = captured["application"].dashboard()
    providers = {provider["id"]: provider for provider in dashboard["providers"]}
    google = providers["google"]
    assert google["id"] == "google"
    assert google["capabilities"] == []
    assert google["health"]["state"] == "failed"
    assert google["health"]["code"] == "preparation-failed"
    assert google["health"]["detail"] == (
        "Plugin validation failed; its contributions are unavailable."
    )
    assert "agenda" in providers["landscape"]["capabilities"]
    assert any(
        entry["source"]["plugin_id"] == "landscape"
        for entry in dashboard["agenda"]
    )
