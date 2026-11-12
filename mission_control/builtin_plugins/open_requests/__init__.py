"""Open requests: a follow-through inbox with links to work and outcomes."""
from mission_control.builtin_plugins.open_requests.repository import RequestError, RequestsRepository, canonical
from mission_control.plugin_api import CapabilityRouter

PLUGIN_ID = "open-requests"
TRACKER = {"plugin_id": PLUGIN_ID, "entity_type": "tracker", "entity_id": "requests"}
AFFORDANCES = [{"capability": "open-requests.request.create", "command": "create-request"}, {"capability": "open-requests.request.update", "command": "update-request"}]
ANNOTATE = [{"capability": "entity.annotate", "command": "add-note"}]


def source(request_id):
    return {"plugin_id": PLUGIN_ID, "entity_type": "request", "entity_id": request_id}


def request_attributes(request):
    attributes = [{"key": "next-step", "label": "Next step", "value": request["next_step"] or "Not recorded yet"}, {"key": "tags", "label": "Tags", "value": ", ".join(request["tags"]) or "None"}]
    for index, target in enumerate(request["task_links"]):
        attributes.append({"key": f"task:{index}", "label": "Linked task", "value": f"{target['plugin_id']} / {target['entity_type']} / {target['entity_id']}"})
    for kind in ("work_links", "result_links"):
        for index, link in enumerate(request[kind]):
            attributes.append({"key": f"{kind}:{index}", "label": link["label"], "value": link["url"]})
    return attributes


def activate(context):
    if context.plugin_id != PLUGIN_ID or context.credentials or context.agenda_seed is not None:
        raise ValueError("Unsupported Open requests activation resources")
    repository = RequestsRepository(context.storage)

    def agenda(inputs):
        snapshot = repository.snapshot()
        entries = [{"id": "requests", "source": TRACKER, "kind": "initiative", "title": "Open requests", "state": "open", "context": "Requests, linked work, and results to follow through", "revision": snapshot["revision"], "affordances": AFFORDANCES, "attribution": {"principal_ids": []}}]
        for request in snapshot["requests"]:
            if request["status"] == "closed":
                continue
            entries.append({"id": request["id"], "source": source(request["id"]), "kind": "action", "timing": {"kind": "anytime"}, "title": request["title"], "state": "blocked" if request["status"] == "waiting" else "ready", "context": request["next_step"] or {"open": "Follow-up in progress", "waiting": "Waiting for input", "ready": "Result ready to review"}[request["status"]], "revision": snapshot["revision"], "affordances": ANNOTATE, "attribution": {"principal_ids": []}, **({"detail": request["description"]} if request["description"] else {})})
        return {"schema_version": "mission-control.agenda/v2", "provider": {"plugin_id": PLUGIN_ID}, "revision": snapshot["revision"], "generated_at": inputs["generated_at"], "entries": entries}

    def state(inputs):
        target = dict(inputs["target"])
        snapshot = repository.snapshot()
        if target == TRACKER:
            affordances = AFFORDANCES
        elif target["plugin_id"] == PLUGIN_ID and target["entity_type"] == "request" and any(r["id"] == target["entity_id"] for r in snapshot["requests"]):
            affordances = ANNOTATE
        else:
            return None
        return {"schema_version": "mission-control.command-state/v1", "target": target, "revision": snapshot["revision"], "affordances": affordances}

    def execute(inputs):
        command = inputs["command"]
        try:
            return repository.execute(command, inputs["actor"])
        except RequestError as error:
            common = {"schema_version": "mission-control.command-result/v1", "command_id": command["command_id"], "target": command["target"]}
            if error.code == "stale-revision":
                return {**common, "status": "stale", "current_revision": error.detail, "error": {"code": error.code, "detail": "Requests changed. Refresh before retrying."}}
            return {**common, "status": "rejected", "error": {"code": error.code, "detail": error.detail}}

    def details(inputs):
        target = dict(inputs["target"])
        snapshot = repository.snapshot()
        base = {"schema_version": "mission-control.entity-detail/v1", "source": target, "revision": snapshot["revision"]}
        if target == TRACKER:
            return {**base, "title": "Open requests", "description": "Keep requests open until you have followed through. Linked work and results do not automatically close them.", "state": "active", "affordances": AFFORDANCES, "attributes": [{"key": f"request:{r['id']}", "label": r["title"][:128], "value": canonical(r)} for r in snapshot["requests"]], "activity": []}
        request = next((r for r in snapshot["requests"] if target == source(r["id"])), None)
        if request is None:
            return None
        return {**base, "title": request["title"], "description": request["description"] or "No additional description.", "state": request["status"], "affordances": ANNOTATE, "attributes": request_attributes(request), "activity": [{"activity_id": f"change:{h['id']}", "kind": "event", "activity_type": "open-requests.updated", "summary": "Request created" if h["operation"] == "create-request" else "Request updated", "body": h["document"], "actor": h["actor"], "occurred_at": h["occurred_at"]} for h in repository.history(request["id"])]}

    return CapabilityRouter(PLUGIN_ID, {"agenda.snapshot": agenda, "commands.state": state, "commands.execute": execute, "commands.lookup": lambda inputs: repository.lookup(inputs["command"]), "entity-details.get": details})
