package common

#PluginIDPattern:       "^[a-z][a-z0-9-]*$"
#CredentialNamePattern: "^[A-Za-z0-9][A-Za-z0-9._-]*$"
#PrincipalIDPattern:     "^[a-z][a-z0-9-]*$"

#PluginID:       string & =~#PluginIDPattern
#CredentialName: string & =~#CredentialNamePattern
#PrincipalID:     string & =~#PrincipalIDPattern

#CredentialReference: close({
	file!: string & !~"^\\s*$"
})
