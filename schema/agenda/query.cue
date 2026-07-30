package agenda

#QueryWindow: close({
	starts_at!: #Timestamp
	ends_at!:   #Timestamp
})

#AgendaQuery: close({
	schema_version!:     "mission-control.agenda-query/v1"
	window!:             #QueryWindow
	include_unscheduled!: bool
	include_initiatives!: bool
})
