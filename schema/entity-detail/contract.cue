@experiment(explicitopen)

package entitydetail

import "strings"

#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#Timestamp: string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"

#SourceRef: close({
	plugin_id!:  string & =~"^[a-z][a-z0-9-]*$"
	entity_type!: #Identifier
	entity_id!:   #Identifier
})

#EntityCapability: string & =~"^[a-z][A-Za-z0-9._:-]*$"

#Affordance: close({
	capability!: #EntityCapability
	command!:    #Identifier
})

#Attribute: close({
	key!:   #Identifier
	label!: string & strings.MinRunes(1) & strings.MaxRunes(128)
	value!: string & strings.MinRunes(1) & strings.MaxRunes(4096)
})

let activityCommon = {
	activity_id!:   #Identifier
	activity_type!: string & =~"^[a-z][a-z0-9-]*\\.[A-Za-z0-9][A-Za-z0-9._:-]*$"
	summary!:       string & strings.MinRunes(1) & strings.MaxRunes(512)
	occurred_at!:   #Timestamp
}

#EventActivity: close({
	activityCommon
	kind!:  "event"
	body?:  string & strings.MinRunes(1) & strings.MaxRunes(16384)
	actor?: string & strings.MinRunes(1) & strings.MaxRunes(256)
})

#NoteActivity: close({
	activityCommon
	kind!:  "note"
	body!:  string & strings.MinRunes(1) & strings.MaxRunes(16384)
	actor!: string & strings.MinRunes(1) & strings.MaxRunes(256)
})

#ActivityEntry: #EventActivity | #NoteActivity

#EntityDetail: close({
	schema_version!: "mission-control.entity-detail/v1"
	source!:         #SourceRef
	title!:          string & strings.MinRunes(1) & strings.MaxRunes(256)
	description?:    string & strings.MinRunes(1) & strings.MaxRunes(16384)
	state?:          string & strings.MinRunes(1) & strings.MaxRunes(128)
	revision?:       string & strings.MinRunes(1) & strings.MaxRunes(256)
	attributes!: [...#Attribute]
	affordances!: [...#Affordance]
	activity!: [...#ActivityEntry]
})
