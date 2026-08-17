#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GENERATED_DIR="$ROOT_DIR/schema/generated"
PLUGIN_GENERATED="$GENERATED_DIR/plugin-registration.runtime-check.schema.json"
PLUGIN_RUNTIME="$ROOT_DIR/mission_control/schemas/plugin-registration.schema.json"
PLUGIN_RAW="$GENERATED_DIR/plugin-registration.raw.schema.json"
PLUGIN_OVERLAY="$GENERATED_DIR/plugin-registration.schema-overlay.json"
PLUGIN_DEFAULTS_GENERATED="$GENERATED_DIR/plugin-config-defaults.runtime-check.schema.json"
PLUGIN_DEFAULTS_RUNTIME="$ROOT_DIR/mission_control/schemas/plugin-config-defaults.schema.json"
PLUGIN_PRESENTATION_GENERATED="$GENERATED_DIR/plugin-config-presentation.runtime-check.schema.json"
PLUGIN_PRESENTATION_RUNTIME="$ROOT_DIR/mission_control/schemas/plugin-config-presentation.schema.json"
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
APPLICATION_CONFIG_GENERATED="$GENERATED_DIR/application-config.runtime-check.schema.json"
APPLICATION_CONFIG_RUNTIME="$ROOT_DIR/mission_control/schemas/application-config.schema.json"
APPLICATION_CONFIG_RAW="$GENERATED_DIR/application-config.raw.schema.json"
APPLICATION_CONFIG_OVERLAY="$GENERATED_DIR/application-config.schema-overlay.json"
APPLICATION_DEFAULTS_GENERATED="$GENERATED_DIR/application-config.defaults.runtime-check.json"
APPLICATION_DEFAULTS_RUNTIME="$ROOT_DIR/mission_control/schemas/application-config.defaults.json"
GOOGLE_CONFIG_GENERATED="$GENERATED_DIR/google-config.runtime-check.schema.json"
GOOGLE_CONFIG_RAW="$GENERATED_DIR/google-config.raw.schema.json"
GOOGLE_CONFIG_OVERLAY="$GENERATED_DIR/google-config.schema-overlay.json"
GOOGLE_DEFAULTS_GENERATED="$GENERATED_DIR/google-config.defaults.runtime-check.json"
GOOGLE_PRESENTATION_GENERATED="$GENERATED_DIR/google-config.presentation.runtime-check.json"
GOOGLE_CONFIG_RUNTIME="$ROOT_DIR/mission_control/builtin_plugins/google/config.schema.json"
GOOGLE_DEFAULTS_RUNTIME="$ROOT_DIR/mission_control/builtin_plugins/google/config.defaults.json"
GOOGLE_PRESENTATION_RUNTIME="$ROOT_DIR/mission_control/builtin_plugins/google/config.presentation.json"
LANDSCAPE_CONFIG_GENERATED="$GENERATED_DIR/landscape-config.runtime-check.schema.json"
LANDSCAPE_CONFIG_RAW="$GENERATED_DIR/landscape-config.raw.schema.json"
LANDSCAPE_CONFIG_OVERLAY="$GENERATED_DIR/landscape-config.schema-overlay.json"
LANDSCAPE_DEFAULTS_GENERATED="$GENERATED_DIR/landscape-config.defaults.runtime-check.json"
LANDSCAPE_PRESENTATION_GENERATED="$GENERATED_DIR/landscape-config.presentation.runtime-check.json"
LANDSCAPE_CONFIG_RUNTIME="$ROOT_DIR/mission_control/builtin_plugins/landscape/config.schema.json"
LANDSCAPE_DEFAULTS_RUNTIME="$ROOT_DIR/mission_control/builtin_plugins/landscape/config.defaults.json"
LANDSCAPE_PRESENTATION_RUNTIME="$ROOT_DIR/mission_control/builtin_plugins/landscape/config.presentation.json"
REFERENCE_CONFIG_GENERATED="$GENERATED_DIR/reference-config.runtime-check.schema.json"
REFERENCE_CONFIG_RAW="$GENERATED_DIR/reference-config.raw.schema.json"
REFERENCE_CONFIG_OVERLAY="$GENERATED_DIR/reference-config.schema-overlay.json"
REFERENCE_DEFAULTS_GENERATED="$GENERATED_DIR/reference-config.defaults.runtime-check.json"
REFERENCE_PRESENTATION_GENERATED="$GENERATED_DIR/reference-config.presentation.runtime-check.json"
REFERENCE_CONFIG_RUNTIME="$ROOT_DIR/plugins/reference/config.schema.json"
REFERENCE_DEFAULTS_RUNTIME="$ROOT_DIR/plugins/reference/config.defaults.json"
REFERENCE_PRESENTATION_RUNTIME="$ROOT_DIR/plugins/reference/config.presentation.json"

cd "$ROOT_DIR"
mkdir -p "$GENERATED_DIR"
trap 'rm -f "$GENERATED_DIR"/*.runtime-check.* "$GENERATED_DIR"/*.raw.schema.json "$GENERATED_DIR"/*.schema-overlay.json' EXIT

(
  cd ./schema
  cue def --force --out jsonschema -e '#PluginRegistration' \
    -o "$PLUGIN_RAW" \
    ./plugin
  cue export -e '#PluginRegistrationJSONSchemaOverlay' \
    -o "$PLUGIN_OVERLAY" \
    ./plugin
)
python ./scripts/merge-json.py "$PLUGIN_RAW" "$PLUGIN_OVERLAY" "$PLUGIN_GENERATED"
(
  cd ./schema
  cue def --force --out jsonschema -e '#ConfigurationDefaults' \
    -o "$PLUGIN_DEFAULTS_GENERATED" \
    ./plugin
  cue def --force --out jsonschema -e '#ConfigurationPresentation' \
    -o "$PLUGIN_PRESENTATION_GENERATED" \
    ./plugin
)
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
(
  cd ./schema
  cue def --force --out jsonschema -e '#ApplicationConfig' \
    -o "$APPLICATION_CONFIG_RAW" \
    ./config
  cue export -e '#ApplicationJSONSchemaOverlay' \
    -o "$APPLICATION_CONFIG_OVERLAY" \
    ./config
)

generate_plugin_bundle() {
  local cue_path="$1"
  local config_definition="$2"
  local overlay_definition="$3"
  local defaults_definition="$4"
  local presentation_definition="$5"
  local raw="$6"
  local overlay="$7"
  local schema_output="$8"
  local defaults_output="$9"
  local presentation_output="${10}"

  if [[ "$cue_path" == ./schema/* ]]; then
    (
      cd ./schema
      cue def --force --out jsonschema -e "$config_definition" -o "$raw" \
        "./${cue_path#./schema/}"
      cue export -e "$overlay_definition" -o "$overlay" \
        "./${cue_path#./schema/}"
      cue export -e "$defaults_definition" -o "$defaults_output" \
        "./${cue_path#./schema/}"
      cue export -e "$presentation_definition" -o "$presentation_output" \
        "./${cue_path#./schema/}"
    )
  else
    cue def --force --out jsonschema -e "$config_definition" -o "$raw" "$cue_path"
    cue export -e "$overlay_definition" -o "$overlay" "$cue_path"
    cue export -e "$defaults_definition" -o "$defaults_output" "$cue_path"
    cue export -e "$presentation_definition" -o "$presentation_output" "$cue_path"
  fi
  python ./scripts/merge-json.py "$raw" "$overlay" "$schema_output"
}

generate_plugin_bundle ./schema/google '#GoogleConfiguration' \
  '#GoogleConfigurationJSONSchemaOverlay' '#GoogleConfigurationDefaults' \
  '#GoogleConfigurationPresentation' "$GOOGLE_CONFIG_RAW" "$GOOGLE_CONFIG_OVERLAY" \
  "$GOOGLE_CONFIG_GENERATED" "$GOOGLE_DEFAULTS_GENERATED" "$GOOGLE_PRESENTATION_GENERATED"
generate_plugin_bundle ./schema/landscape '#LandscapeConfiguration' \
  '#LandscapeConfigurationJSONSchemaOverlay' '#LandscapeConfigurationDefaults' \
  '#LandscapeConfigurationPresentation' "$LANDSCAPE_CONFIG_RAW" "$LANDSCAPE_CONFIG_OVERLAY" \
  "$LANDSCAPE_CONFIG_GENERATED" "$LANDSCAPE_DEFAULTS_GENERATED" "$LANDSCAPE_PRESENTATION_GENERATED"
generate_plugin_bundle ./plugins/reference '#ReferenceConfiguration' \
  '#ReferenceConfigurationJSONSchemaOverlay' '#ReferenceConfigurationDefaults' \
  '#ReferenceConfigurationPresentation' "$REFERENCE_CONFIG_RAW" "$REFERENCE_CONFIG_OVERLAY" \
  "$REFERENCE_CONFIG_GENERATED" "$REFERENCE_DEFAULTS_GENERATED" "$REFERENCE_PRESENTATION_GENERATED"
python ./scripts/merge-json.py \
  "$APPLICATION_CONFIG_RAW" \
  "$APPLICATION_CONFIG_OVERLAY" \
  "$APPLICATION_CONFIG_GENERATED"
(
  cd ./schema
  cue export -e '#ApplicationDefaults' \
    -o "$APPLICATION_DEFAULTS_GENERATED" \
    ./config
)

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
compare_schema "$PLUGIN_DEFAULTS_GENERATED" "$PLUGIN_DEFAULTS_RUNTIME" "plugin configuration defaults"
compare_schema "$PLUGIN_PRESENTATION_GENERATED" "$PLUGIN_PRESENTATION_RUNTIME" "plugin configuration presentation"
compare_schema "$AGENDA_GENERATED" "$AGENDA_RUNTIME" "agenda contribution"
compare_schema "$AGENDA_QUERY_GENERATED" "$AGENDA_QUERY_RUNTIME" "agenda query"
compare_schema "$COMMAND_GENERATED" "$COMMAND_RUNTIME" "command envelope"
compare_schema "$COMMAND_RESULT_GENERATED" "$COMMAND_RESULT_RUNTIME" "command result"
compare_schema "$CLOSED_ITEMS_GENERATED" "$CLOSED_ITEMS_RUNTIME" "closed items contribution"
compare_schema "$ENTITY_DETAIL_GENERATED" "$ENTITY_DETAIL_RUNTIME" "entity detail"
compare_schema "$APPLICATION_CONFIG_GENERATED" "$APPLICATION_CONFIG_RUNTIME" "application config"
compare_schema "$APPLICATION_DEFAULTS_GENERATED" "$APPLICATION_DEFAULTS_RUNTIME" "application defaults"
compare_schema "$GOOGLE_CONFIG_GENERATED" "$GOOGLE_CONFIG_RUNTIME" "Google configuration"
compare_schema "$GOOGLE_DEFAULTS_GENERATED" "$GOOGLE_DEFAULTS_RUNTIME" "Google configuration defaults"
compare_schema "$GOOGLE_PRESENTATION_GENERATED" "$GOOGLE_PRESENTATION_RUNTIME" "Google configuration presentation"
compare_schema "$LANDSCAPE_CONFIG_GENERATED" "$LANDSCAPE_CONFIG_RUNTIME" "Landscape configuration"
compare_schema "$LANDSCAPE_DEFAULTS_GENERATED" "$LANDSCAPE_DEFAULTS_RUNTIME" "Landscape configuration defaults"
compare_schema "$LANDSCAPE_PRESENTATION_GENERATED" "$LANDSCAPE_PRESENTATION_RUNTIME" "Landscape configuration presentation"
compare_schema "$REFERENCE_CONFIG_GENERATED" "$REFERENCE_CONFIG_RUNTIME" "reference configuration"
compare_schema "$REFERENCE_DEFAULTS_GENERATED" "$REFERENCE_DEFAULTS_RUNTIME" "reference configuration defaults"
compare_schema "$REFERENCE_PRESENTATION_GENERATED" "$REFERENCE_PRESENTATION_RUNTIME" "reference configuration presentation"

validate_success() {
  local definition="$1"
  local cue_path="$2"
  local generated_schema="$3"
  local fixture="$4"

  if [[ "$cue_path" == ./schema/* ]]; then
    (
      cd ./schema
      cue vet -c -d "$definition" \
        "./${cue_path#./schema/}" "$ROOT_DIR/${fixture#./}"
    )
  else
    cue vet -c -d "$definition" "$cue_path" "$fixture"
  fi
  python - "$generated_schema" "$fixture" <<'PY'
import json
import sys

from jsonschema import Draft202012Validator, FormatChecker

with open(sys.argv[1], encoding="utf-8") as source:
    schema = json.load(source)
with open(sys.argv[2], encoding="utf-8") as source:
    document = json.load(source)
errors = list(
    Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document)
)
if errors:
    print(f"generated runtime schema rejected {sys.argv[2]}: {errors[0].message}")
    raise SystemExit(1)
PY
}

validate_success '#PluginRegistration' ./schema/plugin "$PLUGIN_GENERATED" \
  ./schema/examples/valid-github-plugin.json
validate_success '#PluginRegistration' ./schema/plugin "$PLUGIN_GENERATED" \
  ./plugins/reference/registration.json
validate_success '#PluginRegistration' ./schema/plugin "$PLUGIN_GENERATED" \
  ./mission_control/builtin_plugins/google/registration.json
validate_success '#PluginRegistration' ./schema/plugin "$PLUGIN_GENERATED" \
  ./mission_control/builtin_plugins/landscape/registration.json

for fixture in \
  ./schema/examples/valid-landscape-agenda.json \
  ./schema/examples/valid-maintenance-agenda.json \
  ./schema/examples/valid-financial-planning-agenda.json \
  ./schema/examples/valid-home-search-agenda.json \
  ./schema/examples/valid-ansible-agenda.json; do
  validate_success '#AgendaContribution' ./schema/agenda "$AGENDA_GENERATED" "$fixture"
done
validate_success '#AgendaContribution' ./schema/agenda "$AGENDA_GENERATED" \
  ./mission_control/builtin_plugins/landscape/agenda.json
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
validate_success '#ApplicationConfig' ./schema/config "$APPLICATION_CONFIG_GENERATED" \
  ./schema/examples/valid-application-config.json
validate_success '#GoogleConfiguration' ./schema/google "$GOOGLE_CONFIG_GENERATED" \
  ./schema/google/examples/valid-demo-config.json

validate_cue_success() {
  local definition="$1"
  local fixture="$2"

  (
    cd ./schema
    cue vet -c -d "$definition" ./google "$fixture"
  )
}

validate_cue_success '#GoogleRegistration' \
  ../mission_control/builtin_plugins/google/registration.json
validate_cue_success '#GoogleDemoConfiguration' \
  ./google/examples/valid-demo-config.json
validate_cue_success '#GoogleDemoFixture' \
  ../mission_control/builtin_plugins/google/demo.json
validate_cue_success '#GoogleMappingCases' \
  ./google/examples/valid-mapping-cases.json
validate_cue_success '#GoogleMappingCases' \
  ./google/examples/valid-mapping-additive-fields.json

expect_failure() {
  local definition="$1"
  local cue_path="$2"
  local generated_schema="$3"
  local fixture="$4"

  if [[ "$cue_path" == ./schema/* ]]; then
    if (
      cd ./schema
      cue vet -c -d "$definition" \
        "./${cue_path#./schema/}" "$ROOT_DIR/${fixture#./}"
    ) >/dev/null 2>&1; then
      echo "expected direct CUE validation to fail: $fixture" >&2
      exit 1
    fi
  elif cue vet -c -d "$definition" "$cue_path" "$fixture" >/dev/null 2>&1; then
    echo "expected direct CUE validation to fail: $fixture" >&2
    exit 1
  fi

  python - "$generated_schema" "$fixture" <<'PY'
import json
import sys

from jsonschema import Draft202012Validator, FormatChecker

with open(sys.argv[1], encoding="utf-8") as source:
    schema = json.load(source)
with open(sys.argv[2], encoding="utf-8") as source:
    document = json.load(source)
if not list(
    Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document)
):
    print(f"expected generated JSON Schema validation to fail: {sys.argv[2]}")
    raise SystemExit(1)
PY
}

for fixture in \
  ./schema/examples/invalid-misspelled-key.json \
  ./schema/examples/invalid-plugin-resource-path.json \
  ./schema/examples/invalid-plugin-configuration-key.json \
  ./schema/examples/invalid-plugin-v1.json; do
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
expect_failure '#ApplicationConfig' ./schema/config "$APPLICATION_CONFIG_GENERATED" \
  ./schema/examples/invalid-application-config.json
expect_failure '#ApplicationConfig' ./schema/config "$APPLICATION_CONFIG_GENERATED" \
  ./schema/examples/invalid-application-plugin-block.json
expect_failure '#ApplicationConfig' ./schema/config "$APPLICATION_CONFIG_GENERATED" \
  ./schema/examples/invalid-application-plugin-id.json
expect_failure '#ApplicationConfig' ./schema/config "$APPLICATION_CONFIG_GENERATED" \
  ./schema/examples/invalid-application-credential-name.json
expect_failure '#GoogleConfiguration' ./schema/google "$GOOGLE_CONFIG_GENERATED" \
  ./schema/google/examples/invalid-demo-settings.json
expect_failure '#GoogleConfiguration' ./schema/google "$GOOGLE_CONFIG_GENERATED" \
  ./schema/google/examples/invalid-live-demo-anchor.json
expect_failure '#GoogleConfiguration' ./schema/google "$GOOGLE_CONFIG_GENERATED" \
  ./schema/google/examples/invalid-demo-date.json

expect_cue_failure() {
  local definition="$1"
  local fixture="$2"

  if (cd ./schema && cue vet -c -d "$definition" ./google "$fixture") >/dev/null 2>&1; then
    echo "expected direct CUE validation to fail: $fixture" >&2
    exit 1
  fi
}

expect_cue_failure '#GoogleDemoConfiguration' \
  ./google/examples/invalid-demo-settings.json
expect_cue_failure '#GoogleConfiguration' \
  ./google/examples/invalid-live-demo-anchor.json
expect_cue_failure '#GoogleDemoConfiguration' \
  ./google/examples/invalid-demo-date.json
expect_cue_failure '#GoogleDemoFixture' \
  ./google/examples/invalid-demo-fixture.json
expect_cue_failure '#GoogleMappingCases' \
  ./google/examples/invalid-mapping-case.json
expect_cue_failure '#GoogleMappingCases' \
  ./google/examples/invalid-mapping-title-mismatch.json
expect_cue_failure '#GoogleMappingCases' \
  ./google/examples/invalid-mapping-freebusy-detail.json
expect_cue_failure '#GoogleMappingCases' \
  ./google/examples/invalid-mapping-timing-mismatch.json

for fixture in \
  ./schema/examples/invalid-agenda-kind.json \
  ./schema/examples/invalid-agenda-timing.json \
  ./schema/examples/invalid-agenda-key.json; do
  expect_failure '#AgendaContribution' ./schema/agenda "$AGENDA_GENERATED" "$fixture"
done

echo "Mission Control schema checks passed"
