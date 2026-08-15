package google

import (
	plugin "mission-control.dev/schema/plugin"
	"time"
)

#Date:     time.Format("2006-01-02")
#DateTime: time.Format(time.RFC3339)

// GoogleRegistration locks the bundled adapter to the same public manifest
// boundary used by every other plugin while also proving its exact envelope.
#GoogleRegistration: plugin.#PluginRegistration & {
	id:   "google"
	name: "Google"
	capabilities: ["agenda", "entity-details", "jobs", "health"]
	runtime: {
		entrypoint:    "mission_control.builtin_plugins.google:activate"
		migration_set: "google"
	}
	permissions: ["database", "network", "credentials"]
	credentials: close({
		oauth: {required_when: {argument: "mode", equals: "live"}}
	})
	entity_types: close({
		"calendar-event": {capabilities: ["entity.annotate", "activity.read"]}
		task: {capabilities: ["entity.annotate", "activity.read"]}
	})
	arguments: close({
		calendar_ids: {
			type: "array"
			items: {type: "string", min_length: 1}
			default: []
		}
		demo_anchor_date: {
			type:    "string"
			pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
		}
		lookahead_days: {
			type:    "integer"
			default: 42
			minimum: 1
			maximum: 366
		}
		lookback_days: {
			type:    "integer"
			default: 42
			minimum: 0
			maximum: 366
		}
		mode: {
			type:    "string"
			default: "live"
			enum: ["live", "demo"]
		}
		request_timeout_seconds: {
			type:    "integer"
			default: 15
			minimum: 3
			maximum: 60
		}
		sync_interval_seconds: {
			type:    "integer"
			default: 300
			minimum: 60
			maximum: 86400
		}
		task_list_ids: {
			type: "array"
			items: {type: "string", min_length: 1}
			default: []
		}
	})
}

// GoogleConfiguration mirrors the registration arguments at the plugin's
// language-neutral boundary. Credential material is deliberately separate.
#GoogleConfiguration: close({
	calendar_ids?: [...string & !~"^\\s*$"]
	lookahead_days?:          int & >=1 & <=366
	lookback_days?:           int & >=0 & <=366
	mode:                     *"live" | "demo"
	request_timeout_seconds?: int & >=3 & <=60
	sync_interval_seconds?:   int & >=60 & <=86400
	task_list_ids?: [...string & !~"^\\s*$"]
	if mode == "demo" {
		demo_anchor_date?: #Date
	}
})

#GoogleDemoConfiguration: #GoogleConfiguration & {
	mode: "demo"
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
