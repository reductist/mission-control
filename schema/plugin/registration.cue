@experiment(explicitopen)

package plugin

import "strings"

#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"

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

#EntityTypeRegistration: close({
	capabilities!: [...#EntityCapability]
})

// PluginRegistration is the language-neutral document a plugin presents before
// Mission Control imports or activates any implementation code.
#PluginRegistration: {
	schema_version!: "mission-control.plugin/v1"
	id!:             =~"^[a-z][a-z0-9-]*$"
	name!:           strings.MinRunes(1)
	version!:        strings.MinRunes(1)
	plugin_api!:     strings.MinRunes(1)
	capabilities!: [...#Capability]
	entity_types?: [#Identifier]: #EntityTypeRegistration
	arguments?: [string]:         #ArgumentDefinition
}

#Capability:
	"agenda" |
	"commands" |
	"cli" |
	"http" |
	"jobs" |
	"events" |
	"ui" |
	"health"

// ArgumentType is the authoritative set of argument discriminator values.
#ArgumentType:
	"string" |
	"integer" |
	"number" |
	"boolean" |
	"array" |
	"object"

// argumentCommon is a private compositional helper rather than a public
// validation boundary. A let binding is intentionally used here: embedding a
// hidden field causes the JSON Schema exporter to emit a sibling $ref beside
// additionalProperties: false, which rejects these shared properties when the
// generated schema is consumed. The let value is expanded into each variant.
let argumentCommon = {
	type!:        #ArgumentType
	required?:    bool | *false
	description?: string
}

#StringArgument: close({
	argumentCommon
	type!:    "string"
	default?: string
	enum?: [...string]
	pattern?:    string
	min_length?: int & >=0
	max_length?: int & >=0
})

#IntegerArgument: close({
	argumentCommon
	type!:    "integer"
	default?: int
	enum?: [...int]
	minimum?: int
	maximum?: int
})

#NumberArgument: close({
	argumentCommon
	type!:    "number"
	default?: number
	enum?: [...number]
	minimum?: number
	maximum?: number
})

#BooleanArgument: close({
	argumentCommon
	type!:    "boolean"
	default?: bool
})

#ArrayArgument: close({
	argumentCommon
	type!:  "array"
	items!: #ArgumentDefinition
	default?: [...]
	min_items?: int & >=0
	max_items?: int & >=0
})

#ObjectArgument: close({
	argumentCommon
	type!: "object"
	properties?: [string]: #ArgumentDefinition
	additional_properties?: bool | *false
	default?: {...}
})

#ArgumentDefinition:
	#StringArgument |
	#IntegerArgument |
	#NumberArgument |
	#BooleanArgument |
	#ArrayArgument |
	#ObjectArgument
