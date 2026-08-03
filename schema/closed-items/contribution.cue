@experiment(explicitopen)

package closeditems

#PluginID:   string & =~"^[a-z][a-z0-9-]*$"
#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#Timestamp:  string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"

#StandardEntityCapability:
	"entity.annotate" |
	"entity.attach" |
	"activity.read" |
	"lifecycle.complete" |
	"lifecycle.reopen" |
	"lifecycle.acknowledge" |
	"lifecycle.dismiss" |
	"entity.edit" |
	"entity.delete"

#EntityCapability:
	#StandardEntityCapability |
	string & =~"^[a-z][a-z0-9-]*\\.[A-Za-z0-9][A-Za-z0-9._:-]*$"

#EntityAffordance: close({
	capability!: #EntityCapability
	command!:    #Identifier
})

#ProviderRef: close({
	plugin_id!: #PluginID
})

#SourceRef: close({
	plugin_id!:   #PluginID
	entity_type!: #Identifier
	entity_id!:   #Identifier
})

#ClosedItem: close({
	id!:          #Identifier
	source!:      #SourceRef
	title!:       string & !=""
	state!:       string & !=""
	closed_at!:   #Timestamp
	context?:     string & !=""
	detail?:      string & !=""
	revision?:    string & !=""
	affordances?: [...#EntityAffordance]
})

#ClosedItemsContribution: close({
	schema_version!: "mission-control.closed-items/v1"
	provider!:       #ProviderRef
	revision!:       string & !=""
	generated_at!:   #Timestamp
	items!:          [...#ClosedItem]
})
