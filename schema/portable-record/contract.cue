@experiment(explicitopen)

package portablerecord

import "strings"

// This is a deliberately small supported profile, not a complete schema for
// RFC 8984 or RFC 9553. The standards-native object stays open so newer IANA
// properties and namespaced extensions survive a Mission Control round trip.
#JSONValue: null | bool | number | string | [...#JSONValue] | {[string]: #JSONValue}

#NonEmpty:      string & strings.MinRunes(1)
#Identifier:    string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#PluginID:      string & =~"^[a-z][a-z0-9-]*$"
#UTCDateTime:   string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]*[1-9])?Z$"
#LocalDateTime: string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]*[1-9])?$"
#Date:          string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
#TimeZoneID:    string & strings.MinRunes(1)
#Duration:      string & =~"^P(?:(?:[0-9]+W(?:[0-9]+D)?|[0-9]+D)(?:T(?:[0-9]+H(?:[0-9]+M(?:[0-9]+(?:\\.[0-9]*[1-9])?S)?|[0-9]+(?:\\.[0-9]*[1-9])?S)?|[0-9]+M(?:[0-9]+(?:\\.[0-9]*[1-9])?S)?|[0-9]+(?:\\.[0-9]*[1-9])?S))?|T(?:[0-9]+H(?:[0-9]+M(?:[0-9]+(?:\\.[0-9]*[1-9])?S)?|[0-9]+(?:\\.[0-9]*[1-9])?S)?|[0-9]+M(?:[0-9]+(?:\\.[0-9]*[1-9])?S)?|[0-9]+(?:\\.[0-9]*[1-9])?S))$"

#SourceRef: close({
	plugin_id!:   #PluginID
	entity_type!: #Identifier
	entity_id!:   #Identifier
})

#Standard: close({
	name!:    "jscalendar"
	version!: "1.0"
	profile!: "mission-control.jscalendar/v1"
}) | close({
	name!:    "jscontact"
	version!: "2.0"
	profile!: "mission-control.jscontact/v1"
})

#Relation: {
	"@type"!: "Relation"
	relation?: {[string]: true}
	...
}

let calendarCommon = {
	uid!:                    #NonEmpty
	updated!:                #UTCDateTime
	created?:                #UTCDateTime
	title?:                  string
	description?:            string
	descriptionContentType?: string & =~"^text/"
	showWithoutTime?:        bool
	timeZone?:               #TimeZoneID | null
	relatedTo?: {[string]: #Relation}
	keywords?: {[string]: true}
	categories?: {[string]: true}
	sequence?: int & >=0
}

#JSCalendarTask: {
	calendarCommon
	"@type"!:           "Task"
	due?:               #LocalDateTime
	start?:             #LocalDateTime
	estimatedDuration?: #Duration
	percentComplete?:   int & >=0 & <=100
	progress?:          "needs-action" | "in-process" | "completed" | "failed" | "cancelled" | string & =~"^[a-z0-9.-]+:[A-Za-z0-9._:-]+$"
	progressUpdated?:   #UTCDateTime
	...
}

#JSCalendarEvent: {
	calendarCommon
	"@type"!:  "Event"
	start!:    #LocalDateTime
	duration?: #Duration
	status?:   "confirmed" | "cancelled" | "tentative" | string & =~"^[a-z0-9.-]+:[A-Za-z0-9._:-]+$"
	...
}

#NameComponent: {
	"@type"?: "NameComponent"
	kind!:    #NonEmpty
	value!:   string
	...
}

#Name: {
	"@type"?: "Name"
	full?:    string
	components?: [...#NameComponent]
	isOrdered?: bool
	...
}

#ContactContexts: {[string]: true}

#EmailAddress: {
	"@type"?:  "EmailAddress"
	address!:  #NonEmpty
	contexts?: #ContactContexts
	pref?:     int & >=1 & <=100
	...
}

#Phone: {
	"@type"?:  "Phone"
	number!:   #NonEmpty
	contexts?: #ContactContexts
	pref?:     int & >=1 & <=100
	...
}

#Organization: {
	"@type"?:  "Organization"
	name?:     #NonEmpty
	contexts?: #ContactContexts
	...
}

#Address: {
	"@type"?: "Address"
	full?:    string
	components?: [...#JSONValue]
	contexts?: #ContactContexts
	...
}

#OnlineService: {
	"@type"?:  "OnlineService"
	uri?:      #NonEmpty
	user?:     #NonEmpty
	service?:  #NonEmpty
	contexts?: #ContactContexts
	...
}

#ContactRelation: {
	"@type"?: "Relation"
	relation?: {[string]: true}
	...
}

#JSContactCard: {
	"@type"!: "Card"
	version!: "2.0"
	uid?:     #NonEmpty
	created?: #UTCDateTime
	updated?: #UTCDateTime
	kind?:    "individual" | "group" | "org" | "location" | "device" | "application" | string & =~"^[a-z0-9.-]+:[A-Za-z0-9._:-]+$"
	name?:    #Name
	emails?: {[string]: #EmailAddress}
	phones?: {[string]: #Phone}
	organizations?: {[string]: #Organization}
	addresses?: {[string]: #Address}
	onlineServices?: {[string]: #OnlineService}
	members?: {[string]: true}
	relatedTo?: {[string]: #ContactRelation}
	...
}

#Workflow: close({
	state!:        "backlog" | "ready" | "in-progress" | "done" | "canceled"
	blocked?:      bool
	waiting_on?:   #NonEmpty
	review_after?: #Date
})

#Planning: close({
	intent!: "none"
}) | close({
	intent!:            "planning-target"
	target!:            #LocalDateTime
	time_zone!:         #TimeZoneID | null
	show_without_time!: bool
}) | close({
	intent!: "hard-deadline"
})

#MissionControlMetadata: close({
	workflow?:      #Workflow
	planning?:      #Planning
	sibling_order?: int & >=0
})

#PortableRecord: close({
	schema_version!: "mission-control.portable-record/v1"
	record_id!:      #Identifier
	kind!:           "task" | "event" | "contact"
	standard!:       #Standard
	source!:         #SourceRef
	revision!:       #NonEmpty
	observed_at!:    #UTCDateTime
	record!:         #JSCalendarTask | #JSCalendarEvent | #JSContactCard
	mc!:             #MissionControlMetadata
})

#SelectionWindow: close({
	starts_at!: #UTCDateTime
	ends_at!:   #UTCDateTime
})

#SnapshotSelection: close({
	record_ids?: [...#Identifier]
	kinds?: [...("task" | "event" | "contact")]
	plugin_ids?: [...#PluginID]
	states?: [...("backlog" | "ready" | "in-progress" | "done" | "canceled")]
	tags?: [...#NonEmpty]
	window?: #SelectionWindow
})

#PortableSnapshot: close({
	schema_version!: "mission-control.portable-snapshot/v1"
	snapshot_id!:    #Identifier
	generated_at!:   #UTCDateTime
	selection!:      #SnapshotSelection
	records!: [...#PortableRecord]
})
