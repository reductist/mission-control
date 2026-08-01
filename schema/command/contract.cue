@experiment(explicitopen)

package command

#PluginID: string & =~"^[a-z][a-z0-9-]*$"
#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"

#SourceRef: close({
	plugin_id!:   #PluginID
	entity_type!: #Identifier
	entity_id!:   #Identifier
})

#CommandEnvelope: close({
	schema_version!:   "mission-control.command/v1"
	command_id!:       #Identifier
	target!:           #SourceRef
	expected_revision!: string & != ""
	command!:          #Identifier
	arguments!:        {[string]: _}
})

#CommandError: close({
	code!:   #Identifier
	detail!: string & != ""
})

let outcomeCommon = {
	schema_version!: "mission-control.command-result/v1"
	command_id!:     #Identifier
	target!:         #SourceRef
}

#Accepted: close({
	outcomeCommon
	status!:   "accepted"
	revision!: string & != ""
	result?:   {[string]: _}
})

#Rejected: close({
	outcomeCommon
	status!: "rejected"
	error!:  #CommandError
})

#Conflicted: close({
	outcomeCommon
	status!:           "conflicted"
	current_revision!: string & != ""
	error!:            #CommandError
})

#Stale: close({
	outcomeCommon
	status!:           "stale"
	current_revision!: string & != ""
	error!:            #CommandError
})

#Unauthorized: close({
	outcomeCommon
	status!: "unauthorized"
	error!:  #CommandError
})

#Failed: close({
	outcomeCommon
	status!: "failed"
	error!:  #CommandError
})

#CommandResult: #Accepted | #Rejected | #Conflicted | #Stale | #Unauthorized | #Failed
