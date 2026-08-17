@experiment(explicitopen)

package plugin

import cmd "mission-control.dev/schema/command"

#PluginID:   string & =~"^[a-z][a-z0-9-]*$"
#Identifier: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
#Timestamp:  string & =~"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"

#SourceRef: close({
	plugin_id!:   #PluginID
	entity_type!: #Identifier
	entity_id!:   #Identifier
})

#SnapshotCall: close({
	schema_version!: "mission-control.plugin-call/v1"
	operation!:      "agenda.snapshot" | "closed-items.snapshot"
	input!: close({
		generated_at!: #Timestamp
	})
})

#EntityDetailCall: close({
	schema_version!: "mission-control.plugin-call/v1"
	operation!:      "entity-details.get"
	input!: close({target!: #SourceRef})
})

#CommandStateCall: close({
	schema_version!: "mission-control.plugin-call/v1"
	operation!:      "commands.state"
	input!: close({target!: #SourceRef})
})

#CommandExecuteCall: close({
	schema_version!: "mission-control.plugin-call/v1"
	operation!:      "commands.execute"
	input!: close({
		command!: cmd.CommandEnvelope
		actor!:   string & != ""
	})
})

#EmptyCall: close({
	schema_version!: "mission-control.plugin-call/v1"
	operation!:      "health.get" | "jobs.list" | "runtime.describe" | "runtime.stop"
	input!:           close({})
})

#JobCall: close({
	schema_version!: "mission-control.plugin-call/v1"
	operation!:      "jobs.run" | "jobs.failure"
	input!: close({job_id!: #Identifier})
})

#PluginCall:
	#SnapshotCall |
	#EntityDetailCall |
	#CommandStateCall |
	#CommandExecuteCall |
	#EmptyCall |
	#JobCall

#PluginCallError: close({
	code!:   #Identifier
	detail!: string & != ""
})

#PluginCallSuccess: close({
	schema_version!: "mission-control.plugin-call-result/v1"
	operation!:      string & != ""
	status!:         "ok"
	output!:         _
})

#PluginCallFailure: close({
	schema_version!: "mission-control.plugin-call-result/v1"
	operation!:      string & != ""
	status!:         "error"
	error!:          #PluginCallError
})

#PluginCallResult: #PluginCallSuccess | #PluginCallFailure

#CommandStateDocument: close({
	schema_version!: "mission-control.command-state/v1"
	target!:         #SourceRef
	revision!:       string & != ""
	affordances!: [...close({
		capability!: string & =~"^[a-z][A-Za-z0-9._:-]*$"
		command!:    #Identifier
	})]
})

#PluginHealthDocument: close({
	schema_version!:  "mission-control.plugin-health/v1"
	plugin_id!:       #PluginID
	state!:           "starting" | "ready" | "degraded" | "failed"
	code!:            #Identifier
	detail!:          string & != ""
	checked_at!:      #Timestamp
	last_success_at?: #Timestamp
})

#PluginJobsDocument: close({
	schema_version!: "mission-control.plugin-jobs/v1"
	plugin_id!:      #PluginID
	jobs!: [...close({
		job_id!:           #Identifier
		interval_seconds!: int & >=1 & <=86400
	})]
})

#PluginOperation:
	"agenda.snapshot" |
	"closed-items.snapshot" |
	"commands.execute" |
	"commands.state" |
	"entity-details.get" |
	"health.get" |
	"jobs.failure" |
	"jobs.list" |
	"jobs.run" |
	"runtime.describe" |
	"runtime.stop"

#PluginRuntimeDocument: close({
	schema_version!: "mission-control.plugin-runtime/v1"
	plugin_id!:      #PluginID
	operations!: [...#PluginOperation]
})
