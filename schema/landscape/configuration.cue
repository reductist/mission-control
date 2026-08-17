package landscape

import plugin "mission-control.dev/schema/plugin"

#LandscapeConfiguration: close({
	settings!: close({})
	credentials!: close({})
})

#LandscapeConfigurationJSONSchemaOverlay: {
	"$id":     "mission-control.landscape.config/v1"
	"$schema": "https://json-schema.org/draft/2020-12/schema"
}

#LandscapeConfigurationDefaults: plugin.#ConfigurationDefaults & {
	schema_version:       "mission-control.plugin-config-defaults/v1"
	configuration_schema: "mission-control.landscape.config/v1"
	defaults: {
		settings: {}
		credentials: {}
	}
}

#LandscapeConfigurationPresentation: plugin.#ConfigurationPresentation & {
	schema_version:       "mission-control.plugin-config-presentation/v1"
	configuration_schema: "mission-control.landscape.config/v1"
	fields: []
}
