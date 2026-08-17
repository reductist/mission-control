from __future__ import annotations

import json

from mission_control.cli import main


def test_config_validate_and_effective_use_the_same_preflight(tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
schema_version = "mission-control.config/v1"
[plugins.google-calendar]
enabled = true
[plugins.google-calendar.settings]
mode = "demo"
demo_anchor_date = "2026-08-14"
""",
        encoding="utf-8",
    )

    assert main(["config", "validate", str(config)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": "mission-control.config/v1",
        "valid": True,
    }

    assert main(["config", "effective", str(config)]) == 0
    effective = json.loads(capsys.readouterr().out)
    assert effective["http"] == {"host": "127.0.0.1", "port": 8000}
    assert effective["plugins"]["google-calendar"]["settings"] == "<redacted>"


def test_config_explain_reports_ordered_sources_and_redacts(tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
schema_version = "mission-control.config/v1"
[plugins.google-calendar]
enabled = false
[plugins.google-calendar.settings]
api_token = "do-not-print"
""",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "config",
                "explain",
                str(config),
                "/plugins/google-calendar/settings/api_token",
            ]
        )
        == 0
    )
    explanation = json.loads(capsys.readouterr().out)
    assert explanation == {
        "path": "/plugins/google-calendar/settings/api_token",
        "sources": [str(config.resolve())],
        "value": "<redacted>",
    }
