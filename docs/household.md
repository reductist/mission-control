# Household maintenance records

The built-in `household` plugin keeps maintenance cases, contractor contact
details, related task IDs, reference links, and scheduled visits together. The
case appears in Mission Control as an initiative. Visits appear in the shared
Schedule, and both cases and visits support durable notes.

The plugin is configuration-backed in this first version. This keeps private
household data in the operator's configuration and provides a useful workflow
before the planned editing and attachment contracts are available.

## Configuration

Add a `household` block to the Mission Control TOML configuration:

```toml
[plugins.household]
enabled = true

[plugins.household.settings.cases.upstairs-shower-leak]
title = "Repair upstairs shower leak"
state = "open"
area = "Upstairs bathroom and kitchen"
summary = "Water from the upstairs shower is reaching the kitchen light below."
related_task_ids = ["choose-plumber"]

[[plugins.household.settings.cases.upstairs-shower-leak.contacts]]
name = "Example Plumbing"
role = "Plumber"
phone = "+1-555-0100"
email = "service@example.invalid"
website = "https://example.invalid/"

[[plugins.household.settings.cases.upstairs-shower-leak.links]]
label = "Ceiling leak photo"
kind = "photo"
url = "https://photos.example.invalid/shower-leak"

[plugins.household.settings.cases.upstairs-shower-leak.appointments.inspection]
title = "Plumber inspection"
kind = "inspection"
starts_at = "2026-10-12T09:00:00-04:00"
ends_at = "2026-10-12T11:00:00-04:00"
detail = "Inspect the shower pan, drain, supply lines, and affected kitchen light."
```

Restart `mctrld` after changing configured cases or visits. Mission Control
validates the complete document before plugin code is imported.

## Recording investigation results

Open the maintenance case from the Dashboard or Schedule and use **Add a note**
to record tests, observations, decisions, estimates, and work performed. Notes
are stored in Mission Control's shared annotation log and survive restarts. They
can be removed from the active Notes panel without deleting their audit history.

Contact phone numbers, email addresses, websites, and configured links are
clickable in the case detail view. Photo links may point to any operator-chosen
photo service or self-hosted file location.

Mission Control does not yet upload or store image files. Managed attachments,
inline previews, and native links to related Mission Control tasks require the
planned artifact and workspace-link contracts. Until then, the plugin keeps
external links and related task IDs with the case.
