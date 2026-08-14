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

## Try the synthetic wall view

No Google account or secret is needed:

```sh
mctrld --database ./mission-control-demo.db --demo --plugin google --plugin landscape
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

5. Create a non-secret settings file, for example:

```json
{
  "mode": "live",
  "calendar_ids": [],
  "task_list_ids": [],
  "lookback_days": 1,
  "lookahead_days": 30,
  "sync_interval_seconds": 300,
  "request_timeout_seconds": 15
}
```

Empty calendar IDs select the primary and Google-selected calendars. Empty task-list IDs select every available task list. Explicit IDs limit either set.

6. Start the daemon with separate settings and credential references:

```sh
mctrld \
  --database ./mission-control.db \
  --plugin google \
  --plugin-settings google=./google-settings.json \
  --plugin-credential google.oauth=/run/secrets/mission-control-google-oauth.json
```

The first live refresh begins after application initialization. Calendar pages use a bounded moving window; Tasks pages are fully polled because the Tasks API does not expose a compatible sync token. A source replaces its cached collection only after every page and resource validates. Other sources and the last good cache remain readable after transient failures. If Google reports that authorization is no longer valid, Mission Control marks the provider `reconnect-required` and erases imported Google cache data rather than retaining private records after revocation.

## OAuth testing-mode warning

For an External OAuth app whose publishing status remains **Testing**, Google issues refresh tokens that expire after seven days for these scopes. A connection authorized on August 14 can therefore require reconnection around August 21—before an August 22 return. Add the demo account as a test user for a quick trial, but move the OAuth app to **In production** for durable household use and complete any Google verification required for the intended audience. See Google's [OAuth 2.0 documentation](https://developers.google.com/identity/protocols/oauth2#expiration) and [verification guidance](https://support.google.com/cloud/answer/13461325).

## Privacy and exposure

The current server has no user authentication. Live mode can display private titles, descriptions, locations, tasks, and travel plans. Keep the listener on loopback and use a local browser, SSH tunnel, or access-controlled Tailscale Serve/reverse proxy. Do not expose it directly to a guest LAN or the public internet.
