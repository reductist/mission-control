# Google Calendar and Tasks integration

## Scope

The bundled `google-calendar` provider imports Google Calendar and Google Tasks read-only for presentation. The capability-oriented ID leaves room for separate integrations such as `google-photos`. Google remains authoritative; Mission Control keeps a plugin-owned SQLite cache so the wall view can survive transient API failures.

> **Pre-release storage reset (August 2026):** the JSON capability adapter moved
> plugin tables into a prefix-safe namespace. An older development database may
> still contain unreachable `google_calendar_*` cache tables. They are not
> covered by the new provider's reconnect/revocation erasure path. Before using
> that database with a live account again, stop Mission Control and either
> archive and replace the development database, or back it up and explicitly
> remove those legacy Google cache tables. The single-service cutover checklist
> treats this cleanup as a required, operator-approved step; it must never happen
> silently during startup.

| Google resource | Mission Control projection | Notes |
| --- | --- | --- |
| Calendar event or appointment | Schedule event | Recurring series are expanded by Google inside the configured window. |
| All-day or multi-day event | Schedule event | Google's exclusive end date is preserved as `ends_before`; date-only values are never timezone-shifted. |
| Task with a due value | Schedule action due on a date | Google Tasks exposes only the date portion; Mission Control does not invent a due time. |
| Task without a due value | Anytime Schedule action | Completed and deleted tasks are omitted. |
| Migrated Google Reminder | Schedule action | Google migrated Reminders into Tasks; the task list label remains visible. |
| Calendar notification/alarm | No separate card | Notification offsets remain part of the Google event and are not duplicated as schedule items. |

Google Calendar appointment bookings appear after they create ordinary calendar events. This integration does not import appointment-schedule availability pages or open booking slots.

## Mapping contract

The read-only Google-to-Mission-Control boundary is specified in
`schema/google/mapping.cue`. It intentionally models only the Google fields the
adapter consumes, then constrains the public Agenda event/action emitted for
each resource kind. Versioned conformance cases cover mapped, deliberately
filtered, and invalid-resource outcomes, including exclusive all-day ends,
timezone offsets, Tasks' date-only due semantics, declined/completed filtering,
free/busy privacy masking, and malformed upstream data.

`tests/test_google_mapping.py` executes those same cases through the production
Python mapper. The schema check validates both the positive cases and a negative
cross-interface case, so a code or CUE change cannot silently redefine one side
of the mapping. There is no reverse mapping: the plugin is read-only and never
translates Mission Control changes into Google API writes.

## Try the synthetic wall view

No Google account or secret is needed. Create `mission-control-demo.toml`:

```toml
schema_version = "mission-control.config/v2"
demo = true
[database]
path = "mission-control-demo.db"
[plugins.google-calendar]
enabled = true
[plugins.google-calendar.settings.connections.demo]
label = "Google demo"
mode = "demo"
demo_anchor_date = "2026-08-14"
[plugins.google-calendar.settings.connections.demo.calendars]
mode = "defaults"
[plugins.google-calendar.settings.connections.demo.tasks]
mode = "all"
[plugins.landscape]
enabled = true
```

```sh
mctrld --config ./mission-control-demo.toml
```

Open `http://127.0.0.1:8000` and select **Schedule**. The packaged fixture includes events in New York and Zürich offsets, an all-day Switzerland trip, an appointment, Tasks, and Reminders.

## Configure live read-only access

### Guided setup

Mission Control can guide the connection-specific part of this process after you
have an authorized-user OAuth JSON file. Give the service a configuration
fragment directory, then run the separate loopback setup host:

```sh
mkdir -p ./config.d
mcctl --config ./mission-control.toml --config-dir ./config.d \
  setup google-calendar --credential-dir ./mission-control.credentials
```

Open the private URL printed in the terminal. The one-time token is carried in
the URL fragment, claimed once by the local page, and removed from the address
bar. The browser sends the selected file only to the loopback setup process; it
receives an opaque handle rather than a server path or OAuth value. The wizard
tests the credential, discovers calendars and task lists, distinguishes
defaults/all/selected/disabled policies, offers the existing workspace people
for attribution, and shows a review step. Core then runs the same generated
configuration validator used at daemon startup.

On save, imported credentials are stored as mode-0600 files beneath a mode-0700
directory and the wizard atomically writes only
`config.d/90-mission-control-setup--google-calendar.toml`. It refuses to overwrite an
operator-authored file and stops if the input configuration changed during the
session. Restart the ordinary service with the same `--config` and
`--config-dir` arguments. `mctrld` itself never exposes these write endpoints.

Declaratively managed deployments can use
`--export-only --managed-fragment candidate.toml`. Export mode does not copy
uploaded secrets or apply/restart the
service; a live export must already refer to an operator-managed credential.

### Manual setup

1. Create a Google Cloud project and configure its OAuth consent screen.
2. Enable the Google Calendar API and Google Tasks API.
3. Create an OAuth client and authorize the intended Google account out of band with exactly these scopes:

   - `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
   - `https://www.googleapis.com/auth/calendar.events.readonly`
   - `https://www.googleapis.com/auth/tasks.readonly`

4. Store the resulting authorized-user values in a file readable only by the Mission Control service user:

```json
{
  "client_id": "…apps.googleusercontent.com",
  "client_secret": "…",
  "refresh_token": "…",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

On POSIX systems, Mission Control rejects files accessible by group or other users. It refreshes access tokens in memory and never writes the client secret, refresh token, or access token to SQLite.

5. Create the canonical non-secret application configuration, for example
   `mission-control.toml`:

```toml
schema_version = "mission-control.config/v2"
[database]
path = "mission-control.db"
[plugins.google-calendar]
enabled = true
[plugins.google-calendar.credentials.personal-oauth]
file = "/run/secrets/mission-control-google-oauth.json"

[plugins.google-calendar.settings]
lookback_days = 42
lookahead_days = 42
sync_interval_seconds = 300
request_timeout_seconds = 15

[plugins.google-calendar.settings.connections.personal]
label = "Personal Google"
mode = "live"
credential = "personal-oauth"

[plugins.google-calendar.settings.connections.personal.calendars]
mode = "defaults"

[plugins.google-calendar.settings.connections.personal.tasks]
mode = "all"
```

Each entry under `connections` is one independently authorized Google account.
Add another named credential and connection block for another account; overlapping
Google IDs remain separate, and one failed or revoked account cannot erase the
other account's cache.

Selection is explicit rather than encoded through overloaded empty lists:

- Calendars accept `disabled`, `defaults` (primary plus Google-selected), `all`,
  or `selected` with a non-empty `ids` list.
- Tasks accept `disabled`, `all`, or `selected` with a non-empty `ids` list.

To label entries by person without baking a household member into the plugin,
declare people once in the shared workspace catalog and assign their IDs to the
relevant Google collections:

```toml
[workspace.principals.pat]
label = "Pat"
kind = "person"

[plugins.google-calendar.settings.connections.personal.attribution.calendars."primary@example.com"]
principal_ids = ["pat"]
```

The calendar or task-list ID on that final table is the exact ID returned by
Google discovery. Mission Control validates every principal reference against
the workspace catalog before opening the database or importing plugin code.
Public filter and accent identities prefix that value with `calendar:` or
`task-list:` so Google's two resource namespaces cannot collide.
Colors remain a workspace presentation preference, not Google-owned identity;
text labels are always retained for accessibility and non-visual clients.

6. Validate and start the daemon. Configuration stores only the credential file
   reference, never its contents:

```sh
mcctl config validate ./mission-control.toml
mctrld --config ./mission-control.toml
```

The first live refresh begins after application initialization. Calendar pages use a bounded moving window sized to cover the current month view by default; Tasks pages are fully polled because the Tasks API does not expose a compatible sync token. A source replaces its cached collection only after every page and resource validates. Other sources and the last good cache remain readable after transient failures. The plugin fingerprints each OAuth authorization without persisting a recoverable credential and clears only that connection's imported cache before switching modes or authorizations. Health reports both a safe plugin summary and one typed component per connection. If Google reports that authorization is no longer valid, Mission Control marks that connection `reconnect-required` and erases its imported Google cache rather than retaining private records after revocation.

## OAuth testing-mode warning

For an External OAuth app whose publishing status remains **Testing**, Google issues refresh tokens that expire after seven days for these scopes. A connection authorized on August 14 can therefore require reconnection around August 21—before an August 22 return. Add the demo account as a test user for a quick trial, but move the OAuth app to **In production** for durable household use and complete any Google verification required for the intended audience. See Google's [OAuth 2.0 documentation](https://developers.google.com/identity/protocols/oauth2#expiration) and [verification guidance](https://support.google.com/cloud/answer/13461325).

## Privacy and exposure

The current server has no user authentication. Live mode can display private titles, descriptions, locations, tasks, and travel plans. Keep the listener on loopback and use a local browser, SSH tunnel, or access-controlled Tailscale Serve/reverse proxy. Do not expose it directly to a guest LAN or the public internet.
