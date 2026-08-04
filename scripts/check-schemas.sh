#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GENERATED_DIR="./schema/generated"
PLUGIN_GENERATED="$GENERATED_DIR/plugin-registration.runtime-check.schema.json"
PLUGIN_RUNTIME="./mission_control/schemas/plugin-registration.schema.json"
AGENDA_GENERATED="$GENERATED_DIR/agenda-contribution.runtime-check.schema.json"
AGENDA_RUNTIME="./mission_control/schemas/agenda-contribution.schema.json"
AGENDA_QUERY_GENERATED="$GENERATED_DIR/agenda-query.runtime-check.schema.json"
AGENDA_QUERY_RUNTIME="./mission_control/schemas/agenda-query.schema.json"
COMMAND_GENERATED="$GENERATED_DIR/command-envelope.runtime-check.schema.json"
COMMAND_RUNTIME="./mission_control/schemas/command-envelope.schema.json"
COMMAND_RESULT_GENERATED="$GENERATED_DIR/command-result.runtime-check.schema.json"
COMMAND_RESULT_RUNTIME="./mission_control/schemas/command-result.schema.json"
CLOSED_ITEMS_GENERATED="$GENERATED_DIR/closed-items-contribution.runtime-check.schema.json"
CLOSED_ITEMS_RUNTIME="./mission_control/schemas/closed-items-contribution.schema.json"
ENTITY_DETAIL_GENERATED="$GENERATED_DIR/entity-detail.runtime-check.schema.json"
ENTITY_DETAIL_RUNTIME="./mission_control/schemas/entity-detail.schema.json"

cd "$ROOT_DIR"
mkdir -p "$GENERATED_DIR"
trap 'rm -f "$PLUGIN_GENERATED" "$AGENDA_GENERATED" "$AGENDA_QUERY_GENERATED" "$COMMAND_GENERATED" "$COMMAND_RESULT_GENERATED" "$CLOSED_ITEMS_GENERATED" "$ENTITY_DETAIL_GENERATED"' EXIT

cue def --force --out jsonschema -e '#PluginRegistration' \
  -o "$PLUGIN_GENERATED" \
  ./schema/plugin
cue def --force --out jsonschema -e '#AgendaContribution' \
  -o "$AGENDA_GENERATED" \
  ./schema/agenda
cue def --force --out jsonschema -e '#AgendaQuery' \
  -o "$AGENDA_QUERY_GENERATED" \
  ./schema/agenda
cue def --force --out jsonschema -e '#CommandEnvelope' \
  -o "$COMMAND_GENERATED" \
  ./schema/command
cue def --force --out jsonschema -e '#CommandResult' \
  -o "$COMMAND_RESULT_GENERATED" \
  ./schema/command
cue def --force --out jsonschema -e '#ClosedItemsContribution' \
  -o "$CLOSED_ITEMS_GENERATED" \
  ./schema/closed-items
cue def --force --out jsonschema -e '#EntityDetail' \
  -o "$ENTITY_DETAIL_GENERATED" \
  ./schema/entity-detail

compare_schema() {
  local generated="$1"
  local packaged="$2"
  local label="$3"

  python - "$generated" "$packaged" "$label" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as generated_source:
    generated = json.load(generated_source)
with open(sys.argv[2], encoding="utf-8") as packaged_source:
    packaged = json.load(packaged_source)

if generated != packaged:
    print(
        f"packaged {sys.argv[3]} schema is stale; regenerate it from CUE",
        file=sys.stderr,
    )
    print(
        "generated schema: "
        + json.dumps(generated, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
}

compare_schema "$PLUGIN_GENERATED" "$PLUGIN_RUNTIME" "plugin registration"
compare_schema "$AGENDA_GENERATED" "$AGENDA_RUNTIME" "agenda contribution"
compare_schema "$AGENDA_QUERY_GENERATED" "$AGENDA_QUERY_RUNTIME" "agenda query"
compare_schema "$COMMAND_GENERATED" "$COMMAND_RUNTIME" "command envelope"
compare_schema "$COMMAND_RESULT_GENERATED" "$COMMAND_RESULT_RUNTIME" "command result"
compare_schema "$CLOSED_ITEMS_GENERATED" "$CLOSED_ITEMS_RUNTIME" "closed items contribution"
compare_schema "$ENTITY_DETAIL_GENERATED" "$ENTITY_DETAIL_RUNTIME" "entity detail"

validate_success() {
  local definition="$1"
  local cue_path="$2"
  local generated_schema="$3"
  local fixture="$4"

  cue vet -c -d "$definition" "$cue_path" "$fixture"
  cue vet -c "$generated_schema" "$fixture"
}

validate_success '#PluginRegistration' ./schema/plugin "$PLUGIN_GENERATED" \
  ./schema/examples/valid-github-plugin.json
validate_success '#PluginRegistration' ./schema/plugin "$PLUGIN_GENERATED" \
  ./plugins/reference/registration.json

for fixture in \
  ./schema/examples/valid-landscape-agenda.json \
  ./schema/examples/valid-maintenance-agenda.json \
  ./schema/examples/valid-financial-planning-agenda.json \
  ./schema/examples/valid-home-search-agenda.json \
  ./schema/examples/valid-ansible-agenda.json; do
  validate_success '#AgendaContribution' ./schema/agenda "$AGENDA_GENERATED" "$fixture"
done
validate_success '#AgendaQuery' ./schema/agenda "$AGENDA_QUERY_GENERATED" \
  ./schema/examples/valid-agenda-query.json
validate_success '#CommandEnvelope' ./schema/command "$COMMAND_GENERATED" \
  ./schema/examples/valid-core-task-command.json
validate_success '#CommandResult' ./schema/command "$COMMAND_RESULT_GENERATED" \
  ./schema/examples/valid-command-result.json
validate_success '#ClosedItemsContribution' ./schema/closed-items "$CLOSED_ITEMS_GENERATED" \
  ./schema/examples/valid-landscape-closed-items.json
validate_success '#EntityDetail' ./schema/entity-detail "$ENTITY_DETAIL_GENERATED" \
  ./schema/examples/valid-landscape-entity-detail.json

expect_failure() {
  local definition="$1"
  local cue_path="$2"
  local generated_schema="$3"
  local fixture="$4"

  if cue vet -c -d "$definition" "$cue_path" "$fixture" >/dev/null 2>&1; then
    echo "expected direct CUE validation to fail: $fixture" >&2
    exit 1
  fi

  if cue vet -c "$generated_schema" "$fixture" >/dev/null 2>&1; then
    echo "expected generated JSON Schema validation to fail: $fixture" >&2
    exit 1
  fi
}

for fixture in \
  ./schema/examples/invalid-misspelled-key.json \
  ./schema/examples/invalid-argument-key.json \
  ./schema/examples/invalid-argument-type.json \
  ./schema/examples/invalid-value-type.json \
  ./schema/examples/invalid-default-type.json; do
  expect_failure '#PluginRegistration' ./schema/plugin "$PLUGIN_GENERATED" "$fixture"
done

expect_failure '#CommandEnvelope' ./schema/command "$COMMAND_GENERATED" \
  ./schema/examples/invalid-command-key.json
expect_failure '#CommandResult' ./schema/command "$COMMAND_RESULT_GENERATED" \
  ./schema/examples/invalid-command-result.json
expect_failure '#ClosedItemsContribution' ./schema/closed-items "$CLOSED_ITEMS_GENERATED" \
  ./schema/examples/invalid-closed-item-key.json
expect_failure '#EntityDetail' ./schema/entity-detail "$ENTITY_DETAIL_GENERATED" \
  ./schema/examples/invalid-entity-detail-key.json

for fixture in \
  ./schema/examples/invalid-agenda-kind.json \
  ./schema/examples/invalid-agenda-timing.json \
  ./schema/examples/invalid-agenda-key.json; do
  expect_failure '#AgendaContribution' ./schema/agenda "$AGENDA_GENERATED" "$fixture"
done

echo "Mission Control schema checks passed"
