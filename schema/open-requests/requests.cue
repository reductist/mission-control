@experiment(explicitopen)
package openrequests
import "strings"
#Configuration: close({settings!: close({}), credentials!: close({})})
#SourceRef: close({plugin_id!: string & =~"^[a-z][a-z0-9-]*$" & strings.MaxRunes(256), entity_type!: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$" & strings.MaxRunes(256), entity_id!: string & =~"^[A-Za-z0-9][A-Za-z0-9._:-]*$" & strings.MaxRunes(256)})
#Link: close({label!: string & strings.MinRunes(1) & strings.MaxRunes(128), url!: string & =~"^https?://" & strings.MaxRunes(1024)})
#Request: close({
 title!: string & strings.MinRunes(1) & strings.MaxRunes(256)
 description!: string & strings.MaxRunes(1200)
 status!: "open" | "waiting" | "ready" | "closed"
 next_step!: string & strings.MaxRunes(512)
 tags!: [...string & strings.MinRunes(1) & strings.MaxRunes(48)]
 task_links!: [...#SourceRef]
 work_links!: [...#Link]
 result_links!: [...#Link]
})
