@experiment(explicitopen)

package plugin

import "strings"

#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#StandardEntityCapability:
	"entity.annotate" |
	"entity.attach" |
	"activity.read" |
	"lifecycle.complete" |
	"lifecycle.reopen" |
	"lifecycle.acknowledge" |
	"lifecycle.dismiss" |
	"entity.edit" |
	"entity.delete"

#EntityCapability:
	#StandardEntityCapability |
	string & =~"^[a-z][a-z0-9-]*\\.[A-Za-z0-9][A-Za-z0-9._:-]*$"

#EntityTypeRegistration: close({
	capabilities!: [...#EntityCapability]
})

#PluginRuntime: close({
	// Entrypoints are resolved only after the complete manifest, compatibility,
	// configuration, credentials, and optional resources have been validated.
	entrypoint!:    =~"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$"
	migration_set?: =~"^[a-z][a-z0-9_]*$"
	agenda_seed?:   =~"^[A-Za-z0-9][A-Za-z0-9._-]*$"
})

#Permission: "database" | "network" | "credentials"

#ResourceName: string & =~"^[A-Za-z0-9][A-Za-z0-9._-]*$"

// ConfigurationContract points at data files that Mission Control reads and
// validates before importing plugin implementation code. The CUE source stays
// plugin-owned; these generated resources are the portable runtime boundary.
#ConfigurationContract: close({
	document_version!:      =~"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
	schema_resource!:       #ResourceName
	defaults_resource!:     #ResourceName
	presentation_resource!: #ResourceName
})

// PluginRegistration is the language-neutral document a plugin presents before
// Mission Control imports or activates any implementation code.
#PluginRegistration: {
	schema_version!: "mission-control.plugin/v2"
	id!:             =~"^[a-z][a-z0-9-]*$"
	name!:           strings.MinRunes(1)
	version!:        strings.MinRunes(1)
	plugin_api!:     strings.MinRunes(1)
	capabilities!: [...#Capability]
	runtime?: #PluginRuntime
	permissions?: [...#Permission]
	configuration!: #ConfigurationContract
	entity_types?: {
		[string]:                            #EntityTypeRegistration
		[!~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"]: _|_("invalid entity type")
	}
}

// See config.#ApplicationJSONSchemaOverlay. CUE 0.16 requires the same
// CUE-owned overlay for dynamic-map key constraints in generated JSON Schema.
#PluginRegistrationJSONSchemaOverlay: {
	properties: {
		entity_types: propertyNames: {
			type:    "string"
			pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]*$"
		}
	}
}

#Capability:
	"agenda" |
	"closed-items" |
	"commands" |
	"entity-details" |
	"cli" |
	"http" |
	"jobs" |
	"events" |
	"ui" |
	"health"
