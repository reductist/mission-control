package google

import (
	common "mission-control.dev/schema/common"
	plugin "mission-control.dev/schema/plugin"
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
		document_version:      "mission-control.google-calendar.config/v1"
		schema_resource:       "config.schema.json"
		defaults_resource:     "config.defaults.json"
		presentation_resource: "config.presentation.json"
	}
	entity_types: close({
		"calendar-event": {capabilities: ["entity.annotate", "activity.read"]}
		task: {capabilities: ["entity.annotate", "activity.read"]}
	})
}

let googleSettings = {
	calendar_ids?: [...string & !~"^\\s*$"]
	lookahead_days?:          int & >=1 & <=366
	lookback_days?:           int & >=0 & <=366
	request_timeout_seconds?: int & >=3 & <=60
	sync_interval_seconds?:   int & >=60 & <=86400
	task_list_ids?: [...string & !~"^\\s*$"]
}

// GoogleConfiguration is the only public configuration definition. It covers
// settings and credential references together, so cross-field requirements are
// enforced before migrations or plugin imports.
#GoogleConfiguration:
	close({
		settings!: close(googleSettings & {
			mode!: "live"
		})
		credentials!: close({
			oauth!: common.#CredentialReference
		})
	}) |
	close({
		settings!: close(googleSettings & {
			mode!:             "demo"
			demo_anchor_date?: #Date
		})
		credentials!: close({})
	})

#GoogleConfigurationJSONSchemaOverlay: {
	"$id":     "mission-control.google-calendar.config/v1"
	"$schema": "https://json-schema.org/draft/2020-12/schema"
}

#GoogleDemoConfiguration: #GoogleConfiguration & {
	settings: mode: "demo"
}

#GoogleConfigurationDefaults: plugin.#ConfigurationDefaults & {
	schema_version:       "mission-control.plugin-config-defaults/v1"
	configuration_schema: "mission-control.google-calendar.config/v1"
	defaults: {
		settings: {
			calendar_ids: []
			lookahead_days:          42
			lookback_days:           42
			mode:                    "live"
			request_timeout_seconds: 15
			sync_interval_seconds:   300
			task_list_ids: []
		}
		credentials: {}
	}
}

#GoogleConfigurationPresentation: plugin.#ConfigurationPresentation & {
	schema_version:       "mission-control.plugin-config-presentation/v1"
	configuration_schema: "mission-control.google-calendar.config/v1"
	fields: [
		{path: "/settings/mode", label: "Connection mode", order: 10, widget: "select"},
		{path: "/credentials/oauth/file", label: "Google authorization", order: 20, widget: "credential-file"},
		{path: "/settings/calendar_ids", label: "Calendars", order: 30},
		{path: "/settings/task_list_ids", label: "Task lists", order: 40},
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
