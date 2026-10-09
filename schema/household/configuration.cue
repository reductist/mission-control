package household

import (
	plugin "mission-control.dev/schema/plugin"
	"list"
	"strings"
	"time"
)

#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#DateTime: time.Format(time.RFC3339)
#NonBlank: string & !~"^\\s*$"

#Contact: close({
	name!:     #NonBlank & strings.MaxRunes(256)
	role?:     #NonBlank & strings.MaxRunes(128)
	company?:  #NonBlank & strings.MaxRunes(256)
	phone?:    #NonBlank & strings.MaxRunes(64)
	email?:    #NonBlank & strings.MaxRunes(320)
	website?:  string & =~"^https?://" & strings.MaxRunes(2048)
})

#Link: close({
	label!: #NonBlank & strings.MaxRunes(256)
	kind!:  "photo" | "document" | "reference" | "todo"
	url!:   string & =~"^https?://" & strings.MaxRunes(2048)
})

#Appointment: close({
	title!:     #NonBlank & strings.MaxRunes(256)
	kind!:      "inspection" | "repair" | "follow-up" | "other"
	starts_at!: #DateTime
	ends_at!:   #DateTime
	detail?:    #NonBlank & strings.MaxRunes(4096)
})

#Case: close({
	title!:   #NonBlank & strings.MaxRunes(256)
	state!:   "open" | "blocked" | "waiting"
	summary!: #NonBlank & strings.MaxRunes(16384)
	area?:    #NonBlank & strings.MaxRunes(256)
	contacts?: [...#Contact]
	links?: [...#Link]
	related_task_ids?: [...#Identifier] & list.UniqueItems()
	appointments?: {
		[string]:                  #Appointment
		[!~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"]: _|_("invalid appointment ID")
	}
})

#HouseholdSettings: close({
	cases!: {
		[string]:                  #Case
		[!~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"]: _|_("invalid case ID")
	}
})

#HouseholdConfiguration: close({
	settings!:    #HouseholdSettings
	credentials!: close({})
})

#HouseholdConfigurationJSONSchemaOverlay: {
	"$id":     "mission-control.household.config/v1"
	"$schema": "https://json-schema.org/draft/2020-12/schema"
	"$defs": {
		"#Case": properties: related_task_ids: uniqueItems: true
		"#HouseholdSettings": properties: cases: propertyNames: {
			type:    "string"
			pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]*$"
		}
	}
}

#HouseholdConfigurationDefaults: plugin.#ConfigurationDefaults & {
	schema_version:       "mission-control.plugin-config-defaults/v1"
	configuration_schema: "mission-control.household.config/v1"
	defaults: {
		settings: cases: {}
		credentials: {}
	}
}

#HouseholdConfigurationPresentation: plugin.#ConfigurationPresentation & {
	schema_version:       "mission-control.plugin-config-presentation/v1"
	configuration_schema: "mission-control.household.config/v1"
	fields: [
		{path: "/settings/cases", label: "Household maintenance cases", order: 10},
	]
}
