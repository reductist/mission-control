@experiment(explicitopen)

package config

import (
	attribution "mission-control.dev/schema/attribution"
	common "mission-control.dev/schema/common"
)

#JSONValue: bool | number | string | [...#JSONValue] | {
	[string]: #JSONValue
}

#PluginConfiguration: close({
	enabled!: bool
	// Settings are owned and validated by the selected plugin's CUE contract.
	settings?: [string]: #JSONValue
	credentials?: {
		[string]:                          common.#CredentialReference
		[!~common.#CredentialNamePattern]: _|_("invalid credential name")
	}
})

#Workspace: close({
	principals?: {
		[string]: close({
			label!: string & !~"^\\s*$"
			kind!:  "person" | "group"
		})
		[!~common.#PrincipalIDPattern]: _|_("invalid principal ID")
	}
	accents?: [...close({
		token!:  attribution.#AccentToken
		target!: attribution.#AccentTarget
	})]
})

#ApplicationConfig: close({
	schema_version: "mission-control.config/v2"
	database?: close({
		path?: string & !~"^\\s*$"
	})
	http?: close({
		host?: string & !~"^\\s*$"
		port?: int & >=1 & <=65535
	})
	demo?: bool
	plugin_roots?: [...string & !~"^\\s*$"]
	workspace?: #Workspace
	plugins?: {
		[string]:                    #PluginConfiguration
		[!~common.#PluginIDPattern]: _|_("invalid plugin ID")
	}
})

// ApplicationDefaults is exported as a separate runtime artifact because JSON
// Schema validates defaults but does not materialize them.
#ApplicationDefaults: #ApplicationConfig & {
	schema_version: "mission-control.config/v2"
	database: path: "mission-control.db"
	http: {
		host: "127.0.0.1"
		port: 8000
	}
	demo: false
	plugin_roots: []
	workspace: {
		principals: {}
		accents:    []
	}
	plugins: {}
}

// CUE 0.16's JSON Schema exporter preserves dynamic-map value constraints but
// omits their key patterns. The generation script deep-merges this CUE-owned
// overlay into the exported schema so every consumer sees the same constraints.
#ApplicationJSONSchemaOverlay: {
	properties: plugins: propertyNames: {
		type:    "string"
		pattern: common.#PluginIDPattern
	}
	"$defs": "#Workspace": properties: principals: propertyNames: {
		type:    "string"
		pattern: common.#PrincipalIDPattern
	}
	"$defs": "#PluginConfiguration": properties: credentials: propertyNames: {
		type:    "string"
		pattern: common.#CredentialNamePattern
	}
}
