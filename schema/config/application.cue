@experiment(explicitopen)

package config

import common "mission-control.dev/schema/common"

#JSONValue: bool | number | string | [...#JSONValue] | {
	[string]: #JSONValue
}

#CredentialReference: close({
	file!: string & !~"^\\s*$"
})

#PluginConfiguration: close({
	enabled!: bool
	// Settings are owned and validated by the selected plugin's CUE contract.
	settings?: [string]: #JSONValue
	credentials?: {
		[string]: #CredentialReference
		[!~common.#CredentialNamePattern]: _|_("invalid credential name")
	}
})

#ApplicationConfig: close({
	schema_version: "mission-control.config/v1"
	database?: close({
		path?: string & !~"^\\s*$"
	})
	http?: close({
		host?: string & !~"^\\s*$"
		port?: int & >=1 & <=65535
	})
	demo?: bool
	plugin_roots?: [...string & !~"^\\s*$"]
	plugins?: {
		[string]: #PluginConfiguration
		[!~common.#PluginIDPattern]: _|_("invalid plugin ID")
	}
})

// ApplicationDefaults is exported as a separate runtime artifact because JSON
// Schema validates defaults but does not materialize them.
#ApplicationDefaults: #ApplicationConfig & {
	schema_version: "mission-control.config/v1"
	database: path: "mission-control.db"
	http: {
		host: "127.0.0.1"
		port: 8000
	}
	demo:         false
	plugin_roots: []
	plugins:      {}
}

// CUE 0.16's JSON Schema exporter preserves dynamic-map value constraints but
// omits their key patterns. The generation script deep-merges this CUE-owned
// overlay into the exported schema so every consumer sees the same constraints.
#ApplicationJSONSchemaOverlay: {
	properties: plugins: propertyNames: {
		type:    "string"
		pattern: common.#PluginIDPattern
	}
	"$defs": "#PluginConfiguration": properties: credentials: propertyNames: {
		type:    "string"
		pattern: common.#CredentialNamePattern
	}
}
