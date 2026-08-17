package reference

#ReferenceConfiguration: close({
	settings!: close({
		message!: string & !~"^\\s*$"
		repeat!:  int & >=1 & <=10
	})
	credentials!: close({})
})

#ReferenceConfigurationJSONSchemaOverlay: {
	"$id":     "mission-control.reference.config/v1"
	"$schema": "https://json-schema.org/draft/2020-12/schema"
}

#ReferenceConfigurationDefaults: close({
	schema_version:       "mission-control.plugin-config-defaults/v1"
	configuration_schema: "mission-control.reference.config/v1"
	defaults: {
		settings: repeat: 1
		credentials: {}
	}
})

#ReferenceConfigurationPresentation: close({
	schema_version:       "mission-control.plugin-config-presentation/v1"
	configuration_schema: "mission-control.reference.config/v1"
	fields: [{
		path:        "/settings/message"
		label:       "Message"
		description: "Message returned by the reference capability"
		order:       10
		widget:      "text"
	}]
})
