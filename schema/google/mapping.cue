package google

import agenda "mission-control.dev/schema/agenda"

import "strings"

import "time"

// The source shapes below are the fields consumed by Mission Control's mapper,
// not replicas of Google's much larger wire schemas. Conformance fixtures pair
// this input projection with the exact public agenda outcome.
#MapperCalendarCollection: {
	id:               string
	summary?:         string
	summaryOverride?: string
	accessRole?:      string
	...
}

#MapperTaskList: {
	id:     string
	title?: string
	...
}

#MapperEventBoundary: {
	date?:     string
	dateTime?: string
	timeZone?: string
	...
}

#MapperAttendee: {
	self?:           bool
	responseStatus?: string
	...
}

#MapperCalendarEvent: {
	id?:                string
	recurringEventId?:  string
	originalStartTime?: #MapperEventBoundary
	summary?:           string
	description?:       string
	visibility?:        string
	status?:            string
	location?:          string
	htmlLink?:          string
	start?:             #MapperEventBoundary
	end?:               #MapperEventBoundary
	attendees?: [...#MapperAttendee]
	updated?: string
	etag?:    string
	...
}

#MapperTask: {
	id?:          string
	title?:       string
	notes?:       string
	status?:      string
	due?:         string
	deleted?:     bool
	webViewLink?: string
	updated?:     string
	etag?:        string
	...
}

#MappedCalendarOutcome: close({
	schema_version: "mission-control.google-mapping/v2"
	status:         "mapped"
	entry: agenda.#Event & {
		source: {
			plugin_id:   "google-calendar"
			entity_type: "calendar-event"
		}
	}
})

#MappedTaskOutcome: close({
	schema_version: "mission-control.google-mapping/v2"
	status:         "mapped"
	entry: agenda.#Action & {
		source: {
			plugin_id:   "google-calendar"
			entity_type: "task"
		}
	}
})

#FilteredCalendarOutcome: close({
	schema_version: "mission-control.google-mapping/v2"
	status:         "filtered"
	reason:         "cancelled" | "self-declined"
})

#FilteredTaskOutcome: close({
	schema_version: "mission-control.google-mapping/v2"
	status:         "filtered"
	reason:         "completed" | "deleted"
})

#RejectedMappingOutcome: close({
	schema_version: "mission-control.google-mapping/v2"
	status:         "rejected"
	code:           "invalid-upstream-resource"
})

#CalendarMappingEnvelope: close({
	name:          string & !~"^\\s*$"
	resource_kind: "calendar-event"
	input: close({
		collection: #MapperCalendarCollection
		resource:   #MapperCalendarEvent
	})
	outcome: #MappedCalendarOutcome | #FilteredCalendarOutcome | #RejectedMappingOutcome
})

#CalendarFreeBusyOverrideCase: C=#CalendarMappingEnvelope & {
	input: collection: {
		accessRole:      "freeBusyReader"
		summaryOverride: string & !=""
	}
	outcome: #MappedCalendarOutcome
	outcome: entry: {
		title:   "Busy"
		context: C.input.collection.summaryOverride
		detail?: _|_
	}
}

#CalendarFreeBusySummaryCase: C=#CalendarMappingEnvelope & {
	input: collection: {
		accessRole:       "freeBusyReader"
		summaryOverride?: null
		summary:          string & !=""
	}
	outcome: #MappedCalendarOutcome
	outcome: entry: {
		title:   "Busy"
		context: C.input.collection.summary
		detail?: _|_
	}
}

#CalendarFreeBusyFallbackCase: #CalendarMappingEnvelope & {
	input: collection: {
		accessRole:       "freeBusyReader"
		summaryOverride?: null
		summary?:         null
	}
	outcome: #MappedCalendarOutcome
	outcome: entry: {
		title:   "Busy"
		context: "Calendar"
		detail?: _|_
	}
}

#CalendarFreeBusyMappedCase:
	#CalendarFreeBusyOverrideCase |
	#CalendarFreeBusySummaryCase |
	#CalendarFreeBusyFallbackCase

#CalendarVisibleTitleCase: C=#CalendarMappingEnvelope & {
	input: collection: accessRole?: string & !="freeBusyReader"
	input: resource: summary:       string & !=""
	outcome: #MappedCalendarOutcome & {
		entry: title: C.input.resource.summary
	}
}

#CalendarVisibleFallbackTitleCase: #CalendarMappingEnvelope & {
	input: collection: accessRole?: string & !="freeBusyReader"
	input: resource: summary?:      null
	outcome: #MappedCalendarOutcome & {
		entry: title: "Busy"
	}
}

#CalendarVisibleMappedCase:
	#CalendarVisibleTitleCase |
	#CalendarVisibleFallbackTitleCase

#CalendarAllDayMappedCase: C=#CalendarMappingEnvelope & {
	input: resource: {
		start: date: string
		end: date:   string
	}
	outcome: #MappedCalendarOutcome & {
		entry: timing: {
			kind:        "all-day"
			occurs_on:   C.input.resource.start.date
			ends_before: C.input.resource.end.date
		}
	}
}

#CalendarTimedMappedCase: C=#CalendarMappingEnvelope & {
	input: resource: {
		start: {
			date?:    null
			dateTime: string
		}
		end: dateTime: string
	}
	outcome: #MappedCalendarOutcome & {
		entry: timing: {
			kind: "timed"
		}
	}
	_startsMatch: true & (time.Parse(time.RFC3339, C.input.resource.start.dateTime) == time.Parse(time.RFC3339, C.outcome.entry.timing.starts_at))
	_endsMatch:   true & (time.Parse(time.RFC3339, C.input.resource.end.dateTime) == time.Parse(time.RFC3339, C.outcome.entry.timing.ends_at))
}

#CalendarIdentityCase: C=#CalendarMappingEnvelope & {
	outcome: #MappedCalendarOutcome & {
		entry: source: entity_id: C.outcome.entry.id
	}
}

#CalendarMappedCase:
	(#CalendarFreeBusyMappedCase | #CalendarVisibleMappedCase) &
	(#CalendarAllDayMappedCase | #CalendarTimedMappedCase) &
	#CalendarIdentityCase

#CalendarMappingCase: #CalendarMappedCase | (#CalendarMappingEnvelope & {
	outcome: #FilteredCalendarOutcome | #RejectedMappingOutcome
})

#TaskMappingEnvelope: close({
	name:          string & !~"^\\s*$"
	resource_kind: "task"
	input: close({
		collection: #MapperTaskList
		resource:   #MapperTask
	})
	outcome: #MappedTaskOutcome | #FilteredTaskOutcome | #RejectedMappingOutcome
})

#TaskNamedCase: C=#TaskMappingEnvelope & {
	outcome: #MappedTaskOutcome & {
		entry: {
			title:   C.input.resource.title
			context: C.input.collection.title
		}
	}
}

#TaskDueCase: C=#TaskMappingEnvelope & {
	input: resource: due: string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
	outcome: #MappedTaskOutcome & {
		entry: timing: {
			kind:   "due-on"
			due_on: strings.Split(C.input.resource.due, "T")[0]
		}
	}
}

#TaskAnytimeCase: #TaskMappingEnvelope & {
	input: resource: due?: null
	outcome: #MappedTaskOutcome & {
		entry: timing: {
			kind: "anytime"
		}
	}
}

#TaskIdentityCase: C=#TaskMappingEnvelope & {
	outcome: #MappedTaskOutcome & {
		entry: source: entity_id: C.outcome.entry.id
	}
}

#TaskMappedCase:
	#TaskNamedCase &
	(#TaskDueCase | #TaskAnytimeCase) &
	#TaskIdentityCase

#TaskMappingCase: #TaskMappedCase | (#TaskMappingEnvelope & {
	outcome: #FilteredTaskOutcome | #RejectedMappingOutcome
})

#GoogleMappingCase: #CalendarMappingCase | #TaskMappingCase

#GoogleMappingCases: close({
	schema_version: "mission-control.google-mapping-cases/v2"
	cases: [#GoogleMappingCase, ...#GoogleMappingCase]
})
