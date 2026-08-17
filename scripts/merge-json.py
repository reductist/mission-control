"""Deep-merge generated JSON objects without introducing another schema source."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def merge(target: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = value


raw_path, overlay_path, destination_path = map(Path, sys.argv[1:])
raw = json.loads(raw_path.read_text(encoding="utf-8"))
overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
if not isinstance(raw, dict) or not isinstance(overlay, dict):
    raise SystemExit("generated schema and overlay must be JSON objects")
merge(raw, overlay)
destination_path.write_text(json.dumps(raw, indent=4) + "\n", encoding="utf-8")
