# Google Calendar and Tasks integration

## Scope

The bundled `google` provider is a read-only import and presentation adapter. Google remains authoritative; Mission Control keeps a plugin-owned SQLite cache so the wall view can survive transient API failures.

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
schema_version = "mission-control.config/v1"
demo = true
[database]
path = "mission-control-demo.db"
[plugins.google]
enabled = true
[plugins.google.settings]
mode = "demo"
demo_anchor_date = "2026-08-14"
[plugins.landscape]
enabled = true
```

```sh
mctrld --config ./mission-control-demo.toml
```

Open `http://127.0.0.1:8000` and select **Schedule**. The packaged fixture includes events in New York and Zürich offsets, an all-day Switzerland trip, an appointment, Tasks, and Reminders.

## Configure live read-only access

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
schema_version = "mission-control.config/v1"
[database]
path = "mission-control.db"
[plugins.google]
enabled = true
[plugins.google.credentials.oauth]
file = "/run/secrets/mission-control-google-oauth.json"
[plugins.google.settings]
mode = "live"
calendar_ids = []
task_list_ids = []
lookback_days = 42
lookahead_days = 42
sync_interval_seconds = 300
request_timeout_seconds = 15
```

Empty calendar IDs select the primary and Google-selected calendars. Empty task-list IDs select every available task list. Explicit IDs limit either set.

6. Validate and start the daemon. Configuration stores only the credential file
   reference, never its contents:

```sh
mcctl config validate ./mission-control.toml
mctrld --config ./mission-control.toml
```

The first live refresh begins after application initialization. Calendar pages use a bounded moving window sized to cover the current month view by default; Tasks pages are fully polled because the Tasks API does not expose a compatible sync token. A source replaces its cached collection only after every page and resource validates. Other sources and the last good cache remain readable after transient failures. The plugin fingerprints the OAuth authorization without persisting a recoverable credential and clears cached imports before switching between fixture/live modes or authorizations, preventing one source's rows from appearing under another. If Google reports that authorization is no longer valid, Mission Control marks the provider `reconnect-required` and erases imported Google cache data rather than retaining private records after revocation.

## OAuth testing-mode warning

For an External OAuth app whose publishing status remains **Testing**, Google issues refresh tokens that expire after seven days for these scopes. A connection authorized on August 14 can therefore require reconnection around August 21—before an August 22 return. Add the demo account as a test user for a quick trial, but move the OAuth app to **In production** for durable household use and complete any Google verification required for the intended audience. See Google's [OAuth 2.0 documentation](https://developers.google.com/identity/protocols/oauth2#expiration) and [verification guidance](https://support.google.com/cloud/answer/13461325).

## Privacy and exposure

The current server has no user authentication. Live mode can display private titles, descriptions, locations, tasks, and travel plans. Keep the listener on loopback and use a local browser, SSH tunnel, or access-controlled Tailscale Serve/reverse proxy. Do not expose it directly to a guest LAN or the public internet.
