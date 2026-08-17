@experiment(explicitopen)

package setup

import common "mission-control.dev/schema/common"

#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#JSONValue: null | bool | number | string | [...#JSONValue] | {[string]: #JSONValue}
#JSONObject: {[string]: #JSONValue}

#Principal: close({
	id!:    common.#PrincipalID
	label!: string & !~"^\\s*$"
})

#Option: close({
	id!:          string & !~"^\\s*$"
	label!:       string & !~"^\\s*$"
	description?: string
})

#FieldCommon: {
	id!:          #Identifier
	label!:       string & !~"^\\s*$"
	description?: string
	required!:    bool
	...
}

#TextField: close(#FieldCommon & {
	widget!: "text" | "credential-file"
	value?:  string
})

#SelectField: close(#FieldCommon & {
	widget!: "select"
	value?:  string
	options!: [...#Option]
})

#MultiSelectField: close(#FieldCommon & {
	widget!: "multi-select"
	value?: [...string]
	options!: [...#Option]
})

#CheckboxField: close(#FieldCommon & {
	widget!: "checkbox"
	value?:  bool
})

#Field: #TextField | #SelectField | #MultiSelectField | #CheckboxField

#Action: close({
	id!:     #Identifier
	label!:  string & !~"^\\s*$"
	style!:  "primary" | "secondary"
	intent!: "continue" | "validate" | "authorize" | "discover" | "test" | "review" | "commit" | "back"
})

#Step: close({
	id!:          #Identifier
	title!:       string & !~"^\\s*$"
	description?: string
	fields!: [...#Field]
	actions!: [...#Action]
})

#CredentialHandle: close({handle!: #Identifier})

#Draft: close({
	settings!: #JSONObject
	credentials!: [string]: #CredentialHandle
})

#Transition: close({
	schema_version!: "mission-control.setup-transition/v1"
	plugin_id!:      common.#PluginID
	draft!:          #Draft
	step!:           #Step
	complete!:       bool
	notice?: close({
		kind!:   "info" | "success" | "warning" | "error"
		detail!: string & !~"^\\s*$"
	})
})

#State: close({
	schema_version!: "mission-control.setup-state/v1"
	plugin_id!:      common.#PluginID
	revision!:       string & !~"^\\s*$"
	draft!:          #Draft
	step!:           #Step
	complete!:       bool
	notice?: close({
		kind!:   "info" | "success" | "warning" | "error"
		detail!: string & !~"^\\s*$"
	})
})

#CommitResult: close({
    schema_version!:   "mission-control.setup-commit/v1"
    plugin_id!:        common.#PluginID
    disposition!:      "managed"
    restart_required!: true
}) | close({
    schema_version!:   "mission-control.setup-commit/v1"
    plugin_id!:        common.#PluginID
    disposition!:      "exported"
    restart_required!: false
})
