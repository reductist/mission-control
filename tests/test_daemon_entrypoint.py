from __future__ import annotations

from mission_control.server import build_parser


def test_daemon_parser_uses_canonical_command_name() -> None:
    assert build_parser().prog == "mctrld"
