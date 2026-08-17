package google

import (
	common "mission-control.dev/schema/common"
	plugin "mission-control.dev/schema/plugin"
	"list"
	"time"
)

#Date:     time.Format("2006-01-02")
#DateTime: time.Format(time.RFC3339)

// GoogleRegistration locks the bundled adapter to the same public manifest
// boundary used by every other plugin while also proving its exact envelope.
#GoogleRegistration: plugin.#PluginRegistration & {
	id:   "google-calendar"
	name: "Google Calendar & Tasks"
	capabilities: ["agenda", "entity-details", "jobs", "health"]
	runtime: {
		entrypoint:    "mission_control.builtin_plugins.google:activate"
		migration_set: "google_calendar_v2"
	}
	permissions: ["database", "network", "credentials"]
	configuration: {
		document_version:      "mission-control.google-calendar.config/v2"
		schema_resource:       "config.schema.json"
		defaults_resource:     "config.defaults.json"
		presentation_resource: "config.presentation.json"
	}
	entity_types: close({
		"calendar-event": {capabilities: ["entity.annotate", "activity.read"]}
		task: {capabilities: ["entity.annotate", "activity.read"]}
	})
}

#ConnectionID: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"

#DisabledSelection: close({mode!: "disabled"})
#DefaultSelection: close({mode!: "defaults"})
#AllSelection: close({mode!: "all"})
#SelectedSelection: close({
	mode!: "selected"
	ids!: [string & !~"^\\s*$", ...string & !~"^\\s*$"] & list.UniqueItems()
})
#CalendarSelection: #DisabledSelection | #DefaultSelection | #AllSelection | #SelectedSelection
#TaskSelection: #DisabledSelection | #AllSelection | #SelectedSelection

#CollectionAttribution: close({
	principal_ids!: [...common.#PrincipalID] & list.UniqueItems()
})

let connectionCommon = {
	label!:     string & !~"^\\s*$"
	calendars!: #CalendarSelection
	tasks!:     #TaskSelection
	attribution?: close({
		calendars?: [string]: #CollectionAttribution
		task_lists?: [string]: #CollectionAttribution
	})
}

#LiveConnection: close(connectionCommon & {
	mode!:       "live"
	credential!: common.#CredentialName
})

#DemoConnection: close(connectionCommon & {
	mode!:             "demo"
	demo_anchor_date?: #Date
})

#GoogleConnection: #LiveConnection | #DemoConnection

#GoogleSettings: close({
	connections!: {
		[string]:                   #GoogleConnection
		[!~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"]: _|_("invalid connection ID")
	}
	lookahead_days!:          int & >=1 & <=366
	lookback_days!:           int & >=0 & <=366
	request_timeout_seconds!: int & >=3 & <=60
	sync_interval_seconds!:   int & >=60 & <=86400
})

// GoogleConfiguration is the only public configuration definition. Credential
// and workspace-principal references are annotated in the generated schema and
// resolved generically by core before migrations or plugin imports.
#GoogleConfiguration: close({
	settings!: #GoogleSettings
	credentials!: {
		[string]:                          common.#CredentialReference
		[!~common.#CredentialNamePattern]: _|_("invalid credential name")
	}
})

#GoogleConfigurationJSONSchemaOverlay: {
	"$id":     "mission-control.google-calendar.config/v2"
	"$schema": "https://json-schema.org/draft/2020-12/schema"
	"$defs": {
		"#SelectedSelection": properties: ids: {
			minItems:    1
			uniqueItems: true
		}
		"#GoogleSettings": properties: connections: propertyNames: {
			type:    "string"
			pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]*$"
		}
		"#LiveConnection": properties: credential: {
			"x-mission-control-reference": "credential"
		}
		"#CollectionAttribution": properties: principal_ids: {
			uniqueItems: true
			items: {
				"x-mission-control-reference": "workspace-principal"
			}
		}
	}
	properties: credentials: propertyNames: {
		type:    "string"
		pattern: common.#CredentialNamePattern
	}
}

#GoogleDemoConfiguration: #GoogleConfiguration & {
	settings: connections: demo: {
		label: "Google demo"
		mode:  "demo"
		calendars: mode: "defaults"
		tasks: mode: "all"
	}
}

#GoogleConfigurationDefaults: plugin.#ConfigurationDefaults & {
	schema_version:       "mission-control.plugin-config-defaults/v1"
	configuration_schema: "mission-control.google-calendar.config/v2"
	defaults: {
		settings: {
			connections: {}
			lookahead_days:          42
			lookback_days:           42
			request_timeout_seconds: 15
			sync_interval_seconds:   300
		}
		credentials: {}
	}
}

#GoogleConfigurationPresentation: plugin.#ConfigurationPresentation & {
	schema_version:       "mission-control.plugin-config-presentation/v1"
	configuration_schema: "mission-control.google-calendar.config/v2"
	fields: [
		{path: "/settings/connections", label: "Google connections", order: 10},
		{path: "/settings/lookback_days", label: "Past calendar window", order: 20, widget: "number"},
		{path: "/settings/lookahead_days", label: "Future calendar window", order: 30, widget: "number"},
	]
}

#CalendarCollection: close({
	id:         string & !~"^\\s*$"
	summary:    string & !~"^\\s*$"
	primary?:   bool
	selected?:  bool
	accessRole: string & !~"^\\s*$"
})

#AllDayBoundary: close({date: #Date})
#TimedBoundary: close({
	dateTime:  #DateTime
	timeZone?: string & !~"^\\s*$"
})

let calendarEventCommon = {
	id:                 string & !~"^\\s*$"
	recurringEventId?:  string & !~"^\\s*$"
	originalStartTime?: #TimedBoundary
	summary:            string & !~"^\\s*$"
	description?:       string
	visibility?:        string & !~"^\\s*$"
	status:             string & !~"^\\s*$"
	location?:          string
	updated:            #DateTime
	etag:               string & !~"^\\s*$"
}

#CalendarEvent: close(calendarEventCommon & {
	start: #AllDayBoundary
	end:   #AllDayBoundary
}) | close(calendarEventCommon & {
	start: #TimedBoundary
	end:   #TimedBoundary
})

#TaskList: close({
	id:    string & !~"^\\s*$"
	title: string & !~"^\\s*$"
})

#Task: close({
	id:      string & !~"^\\s*$"
	title:   string & !~"^\\s*$"
	notes?:  string
	status:  string & !~"^\\s*$"
	due?:    #DateTime
	updated: #DateTime
	etag:    string & !~"^\\s*$"
})

#GoogleDemoFixture: close({
	anchor_date: #Date
	calendarList: close({items: [...#CalendarCollection]})
	events: [string]: close({items: [...#CalendarEvent]})
	tasklists: close({items: [...#TaskList]})
	tasks: [string]: close({items: [...#Task]})
})
