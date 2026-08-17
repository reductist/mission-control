package plugin

import "strings"

#JSONPointer: "" | (string & =~"^/([^~/]|~[01])*(/([^~/]|~[01])*)*$")

#ConfigurationDefaults: close({
	schema_version!:       "mission-control.plugin-config-defaults/v1"
	configuration_schema!: strings.MinRunes(1)
	defaults!: close({
		settings?: {...}
		credentials?: close({})
	})
})

#ConfigurationField: close({
	path!:        #JSONPointer
	label!:       strings.MinRunes(1)
	description?: string
	order?:       int & >=0
	widget?:      "text" | "number" | "checkbox" | "select" | "credential-file"
})

#ConfigurationPresentation: close({
	schema_version!:       "mission-control.plugin-config-presentation/v1"
	configuration_schema!: strings.MinRunes(1)
	fields!: [...#ConfigurationField]
})
