@experiment(explicitopen)

package attribution

import common "mission-control.dev/schema/common"

#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"

#Connection: close({
	id!:    #Identifier
	label!: string & !~"^\\s*$"
})

#Collection: close({
	id!:    #Identifier
	kind!:  #Identifier
	label!: string & !~"^\\s*$"
})

#Integration: close({
	connection!: #Connection
	collection?: #Collection
})

#EntryAttribution: close({
	principal_ids!: [...common.#PrincipalID]
	integration?:   #Integration
})

#AccentToken: "accent-1" | "accent-2" | "accent-3" | "accent-4" | "accent-5" | "accent-6" | "accent-7" | "accent-8"

#PrincipalTarget: close({
	kind!:         "principal"
	principal_id!: common.#PrincipalID
})

#PluginTarget: close({
	kind!:      "plugin"
	plugin_id!: common.#PluginID
})

#ConnectionTarget: close({
	kind!:          "connection"
	plugin_id!:     common.#PluginID
	connection_id!: #Identifier
})

#CollectionTarget: close({
	kind!:          "collection"
	plugin_id!:     common.#PluginID
	connection_id!: #Identifier
	collection_id!: #Identifier
})

#AccentTarget: #PrincipalTarget | #PluginTarget | #ConnectionTarget | #CollectionTarget

#PrincipalDocument: close({
	id!:    common.#PrincipalID
	label!: string & !~"^\\s*$"
	kind!:  "person" | "group"
})

#AccentDocument: close({
	token!:  #AccentToken
	target!: #AccentTarget
})

#AttributionCatalog: close({
	schema_version!: "mission-control.attribution-catalog/v1"
	principals!:     [...#PrincipalDocument]
	accents!:        [...#AccentDocument]
})
