"""Durable request tracking, independent of the lifetime of linked work."""
from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from jsonschema import Draft202012Validator
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from mission_control.plugin_api import PluginStorage

PREFIX = "plugin__13__open_requests__"
REQUEST_VALIDATOR = Draft202012Validator(json.loads(files("mission_control.builtin_plugins.open_requests").joinpath("request.schema.json").read_text()))
FIELDS = {"title", "description", "status", "next_step", "tags", "task_links", "work_links", "result_links"}


class RequestError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code, self.detail = code, detail


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_request(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise RequestError("invalid-request", "Supply exactly the documented request fields.")
    if next(REQUEST_VALIDATOR.iter_errors(value), None) is not None:
        raise RequestError("invalid-request", "Request does not match the documented fields and limits.")
    result = dict(value)
    for key, limit in (("title", 256), ("description", 1200), ("next_step", 512)):
        text = value[key]
        if not isinstance(text, str) or len(text) > limit or (key == "title" and not text.strip()):
            raise RequestError("invalid-request", f"{key} must be text of at most {limit} characters.")
        result[key] = text.strip()
    if value["status"] not in ("open", "waiting", "ready", "closed"):
        raise RequestError("invalid-request", "Choose open, waiting, ready, or closed.")
    tags = value["tags"]
    if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t, str) or not t.strip() or len(t) > 48 for t in tags):
        raise RequestError("invalid-tags", "Use at most 20 nonempty tags of at most 48 characters.")
    result["tags"] = list(dict.fromkeys(t.strip().lower() for t in tags))
    refs = value["task_links"]
    if not isinstance(refs, list) or len(refs) > 20:
        raise RequestError("invalid-links", "Use at most 20 task links.")
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"plugin_id", "entity_type", "entity_id"}:
            raise RequestError("invalid-links", "Task links require plugin_id, entity_type, and entity_id.")
        for key, pattern in (("plugin_id", r"[a-z][a-z0-9-]*"), ("entity_type", r"[A-Za-z0-9][A-Za-z0-9._:-]*"), ("entity_id", r"[A-Za-z0-9][A-Za-z0-9._:-]*")):
            if not isinstance(ref[key], str) or len(ref[key]) > 256 or not re.fullmatch(pattern, ref[key]):
                raise RequestError("invalid-links", "Task links must contain valid source identifiers.")
    result["task_links"] = [json.loads(item) for item in dict.fromkeys(canonical(ref) for ref in refs)]
    for key in ("work_links", "result_links"):
        links = value[key]
        if not isinstance(links, list) or len(links) > 10:
            raise RequestError("invalid-links", "Use at most 10 links of each kind.")
        clean = []
        for link in links:
            if not isinstance(link, dict) or set(link) != {"label", "url"} or not isinstance(link["label"], str) or not 1 <= len(link["label"].strip()) <= 128 or not isinstance(link["url"], str) or len(link["url"]) > 1024:
                raise RequestError("invalid-links", "Each link needs a label and an HTTP(S) URL.")
            url = link["url"]
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password and not any(c.isspace() or ord(c) < 32 for c in url) and "\\" not in url
                parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise RequestError("invalid-links", "Links must be absolute HTTP(S) URLs without credentials.")
            clean.append({"label": link["label"].strip(), "url": url})
        result[key] = clean
    return result


class RequestsRepository:
    def __init__(self, storage: PluginStorage):
        self.storage = storage

    def snapshot(self):
        with self.storage.connect() as c:
            c.execute("BEGIN")
            revision = c.execute(f"SELECT revision FROM {PREFIX}state").fetchone()[0]
            requests = [json.loads(r[0]) for r in c.execute(f"SELECT document FROM {PREFIX}requests ORDER BY id")]
        return {"revision": f"r{revision}", "requests": requests}

    def history(self, request_id):
        with self.storage.connect() as c:
            return [dict(r) for r in c.execute(f"SELECT * FROM {PREFIX}history WHERE request_id = ? ORDER BY id", (request_id,))]

    def lookup(self, command):
        with self.storage.connect() as c:
            row = c.execute(f"SELECT * FROM {PREFIX}receipts WHERE command_id = ?", (command["command_id"],)).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != hashlib.sha256(canonical(command).encode()).hexdigest():
            return {"schema_version": "mission-control.command-result/v1", "command_id": command["command_id"], "target": command["target"], "status": "rejected", "error": {"code": "command-id-conflict", "detail": "Command id already used for a different request."}}
        return json.loads(row["result"])

    def execute(self, command, actor):
        fingerprint = hashlib.sha256(canonical(command).encode()).hexdigest()
        with self.storage.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            receipt = c.execute(f"SELECT * FROM {PREFIX}receipts WHERE command_id = ?", (command["command_id"],)).fetchone()
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise RequestError("command-id-conflict", "Command id already used for a different request.")
                return json.loads(receipt["result"])
            revision = c.execute(f"SELECT revision FROM {PREFIX}state").fetchone()[0]
            if command["expected_revision"] != f"r{revision}":
                raise RequestError("stale-revision", f"r{revision}")
            args = command.get("arguments", {})
            operation = command["command"]
            expected = {"request"} if operation == "create-request" else {"request_id", "request"}
            if operation not in ("create-request", "update-request") or not isinstance(args, dict) or set(args) != expected:
                raise RequestError("invalid-arguments", "Use create-request or update-request with the complete request.")
            now = datetime.now(UTC).isoformat()
            document = validate_request(args["request"])
            if operation == "create-request":
                request_id, created_at = str(uuid4()), now
            else:
                request_id = args["request_id"]
                if not isinstance(request_id, str):
                    raise RequestError("invalid-request", "request_id must be text.")
                row = c.execute(f"SELECT document FROM {PREFIX}requests WHERE id = ?", (request_id,)).fetchone()
                if row is None:
                    raise RequestError("not-found", "Request not found.")
                created_at = json.loads(row[0])["created_at"]
            document.update(id=request_id, created_at=created_at, updated_at=now)
            serialized = canonical(document)
            if len(serialized) > 4096:
                raise RequestError("request-too-large", "Keep the request under 4096 characters including links; put longer content in a linked document.")
            c.execute(f"INSERT INTO {PREFIX}requests VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET document = excluded.document", (request_id, serialized))
            c.execute(f"INSERT INTO {PREFIX}history(request_id, actor, occurred_at, operation, document) VALUES (?, ?, ?, ?, ?)", (request_id, actor, now, operation, serialized))
            c.execute(f"UPDATE {PREFIX}state SET revision = revision + 1")
            outcome = {"schema_version": "mission-control.command-result/v1", "command_id": command["command_id"], "target": command["target"], "status": "accepted", "revision": f"r{revision+1}", "result": {"request_id": request_id}}
            c.execute(f"INSERT INTO {PREFIX}receipts VALUES (?, ?, ?)", (command["command_id"], fingerprint, canonical(outcome)))
            return outcome
