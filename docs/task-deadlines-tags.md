# Task deadlines and tags

In **Overview**, enter a title in **Add a shared task…** and open **Deadline
and tags**. Choose a due date if needed. **End of day** is selected by default;
choose **Specific time** to enter a clock time. The timezone starts with your
device's timezone and can be changed. Open **Tags** and check any combination
of Maintenance, House search, Personal/social, and Yard, then select **Add**.

Select **Edit** on a shared task, or its title in Schedule / occurrence in
Calendar, to change its title, description, deadline, and tags. Clear the date
to remove a deadline; uncheck tags to remove them. Save with **Save task**.
Completed shared tasks can also be edited from History.

In **Schedule**, open **Filter by tags** and select several tags to match any
of them. The same selection applies to Agenda and Calendar. **Clear all tags**
restores unfiltered results. Shared tasks tagged House search, Maintenance,
or Yard also appear in their corresponding section, even when that section's
plugin is not enabled. Personal/social tasks remain in Overview and Schedule.

Core tasks can have an optional deadline and several tags. A task without a
deadline remains unscheduled. These are deadline metadata, not notifications or
reminders. The internal `review_after` review date is separate and is never
treated as a deadline.

Selecting End of day stores a calendar date (`due-on`) and the user's IANA
timezone. The task is due by the end of that date in that timezone; it does not
invent a 23:59 UTC timestamp. Date-only agenda entries retain that calendar date.
Specific time stores `due-at`, an ISO timestamp with an explicit offset, plus the
IANA timezone. The offset and local clock must agree with that timezone at the
instant. Nonexistent DST times are rejected; either valid offset at a repeated
DST time is accepted. Stored timestamp spelling and offset roundtrip unchanged.
Timed agenda entries represent instants and can display in the viewer's timezone.

`POST /api/tasks` accepts title, optional description, nullable deadline, and a
list of unique tag IDs. `PATCH /api/tasks/{id}` accepts the same fields plus
existing workflow fields and optional `expected_revision` from `updated_at`.
Omitted fields stay unchanged; null clears a deadline and an empty list clears
tags. Stale revisions return HTTP 409. Example deadline objects:

```json
{"kind":"due-on","due_on":"2026-10-15","time_zone":"Europe/Zurich"}
```

```json
{"kind":"due-at","due_at":"2026-10-25T02:30:00+01:00","time_zone":"Europe/Zurich"}
```

The dashboard's backend-owned `task_tag_catalog` defines stable IDs, labels,
optional section views, and provider associations. Current tags are Maintenance
(`maintenance`, Household provider), House search (`house-search`, Home search),
Personal/social (`personal-social`), and Yard (`yard`, Landscape). A core task
can carry Yard and Maintenance together. Provider-owned records keep their own
source contracts; filter classification uses catalog provider associations
without copying or modifying their source data. Multiple selected filter tags
match any selected tag. Untagged core records and unmapped providers are visible
when filtering is cleared and do not match selected tags.

Migration 5 adds nullable deadline JSON and tags JSON defaulting to an empty
list. Existing tasks, review dates, and event history are retained. There is no
automatic conversion of review dates to deadlines.
