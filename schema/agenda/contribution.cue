@experiment(explicitopen)

package agenda

#PluginID: string & =~"^[a-z][a-z0-9-]*$"
#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#Timestamp: string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
#Date: string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"

#ProviderRef: close({
	plugin_id!: #PluginID
})

#SourceRef: close({
	plugin_id!:   #PluginID
	entity_type!: #Identifier
	entity_id!:   #Identifier
})

#InitiativeState: "open" | "blocked" | "waiting"
#ActionState: "ready" | "blocked" | "waiting"

#Anytime: close({
	kind!: "anytime"
})

#DueOn: close({
	kind!:   "due-on"
	due_on!: #Date
})

#DueAt: close({
	kind!:   "due-at"
	due_at!: #Timestamp
})

#Window: close({
	kind!:      "window"
	starts_at!: #Timestamp
	ends_at!:   #Timestamp
})

#ActionTiming: #Anytime | #DueOn | #DueAt | #Window

#AllDay: close({
	kind!:      "all-day"
	occurs_on!: #Date
})

#Timed: close({
	kind!:      "timed"
	starts_at!: #Timestamp
	ends_at!:   #Timestamp
})

#EventTiming: #AllDay | #Timed

// entryCommon is expanded into each public variant so generated JSON Schema
// contains every shared property locally beside additionalProperties: false.
let entryCommon = {
	id!:      #Identifier
	source!:  #SourceRef
	title!:   string & != ""
	context?: string & != ""
	detail?:  string & != ""
}

#Initiative: close({
	entryCommon
	kind!:  "initiative"
	state!: #InitiativeState
})

#Action: close({
	entryCommon
	kind!:   "action"
	state!:  #ActionState
	timing!: #ActionTiming
})

#Event: close({
	entryCommon
	kind!:   "event"
	timing!: #EventTiming
})

#AgendaEntry: #Initiative | #Action | #Event

#AgendaContribution: close({
	schema_version!: "mission-control.agenda/v1"
	provider!:       #ProviderRef
	revision!:       string & != ""
	generated_at!:   #Timestamp
	entries!:        [...#AgendaEntry]
})
