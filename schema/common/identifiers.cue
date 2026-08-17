package common

#PluginIDPattern:       "^[a-z][a-z0-9-]*$"
#CredentialNamePattern: "^[A-Za-z0-9][A-Za-z0-9._-]*$"

#PluginID:       string & =~#PluginIDPattern
#CredentialName: string & =~#CredentialNamePattern

#CredentialReference: close({
	file!: string & !~"^\\s*$"
})
