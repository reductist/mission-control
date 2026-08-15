"""Narrow read-only Google Calendar and Tasks HTTP adapter."""

from __future__ import annotations

import hashlib
import json
import os
import random
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from mission_control.builtin_plugins.google.domain import (
    GoogleCollection,
    calendar_collection,
    task_list_collection,
)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
TASKS_API = "https://tasks.googleapis.com/tasks/v1"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleApiError(ValueError):
    """A safe upstream failure suitable for plugin health reporting."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class GoogleClient(Protocol):
    def calendars(self) -> tuple[tuple[GoogleCollection, Mapping[str, Any]], ...]: ...

    def events(
        self, calendar_id: str, *, starts_at: datetime, ends_at: datetime
    ) -> tuple[Mapping[str, Any], ...]: ...

    def task_lists(self) -> tuple[GoogleCollection, ...]: ...

    def tasks(self, task_list_id: str) -> tuple[Mapping[str, Any], ...]: ...


@dataclass(frozen=True, slots=True)
class AuthorizedUserCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    token_uri: str = DEFAULT_TOKEN_URI

    def source_fingerprint(self) -> str:
        """Identify one authorization without persisting recoverable credentials."""

        material = f"{self.client_id}\0{self.refresh_token}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @classmethod
    def load(cls, path: Path) -> AuthorizedUserCredentials:
        if os.name == "posix":
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise GoogleApiError(
                    "insecure-credential-file",
                    "OAuth credential must not be accessible by group or other users.",
                )
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GoogleApiError(
                "invalid-credential-file", "OAuth credential could not be read."
            ) from error
        if not isinstance(document, Mapping):
            raise GoogleApiError(
                "invalid-credential-file", "OAuth credential must be a JSON object."
            )
        values: dict[str, str] = {}
        for key in ("client_id", "client_secret", "refresh_token"):
            value = document.get(key)
            if not isinstance(value, str) or not value.strip():
                raise GoogleApiError(
                    "invalid-credential-file",
                    f"OAuth credential is missing {key}.",
                )
            values[key] = value
        token_uri = document.get("token_uri", DEFAULT_TOKEN_URI)
        if token_uri != DEFAULT_TOKEN_URI:
            raise GoogleApiError(
                "invalid-credential-file",
                "OAuth token URI must use Google's token endpoint.",
            )
        return cls(token_uri=token_uri, **values)


class GoogleHttpClient:
    """Paginated Calendar/Tasks reader with in-memory access-token refresh."""

    def __init__(
        self,
        credentials: AuthorizedUserCredentials,
        *,
        timeout_seconds: int = 15,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        self._sleeper = sleeper
        self._access_token: str | None = None
        self._expires_at: datetime | None = None

    def calendars(self) -> tuple[tuple[GoogleCollection, Mapping[str, Any]], ...]:
        items = self._paginated(
            f"{CALENDAR_API}/users/me/calendarList",
            {"maxResults": "250", "showHidden": "true"},
        )
        result = []
        for item in items:
            collection = calendar_collection(item)
            result.append((collection, item))
        return tuple(result)

    def events(
        self, calendar_id: str, *, starts_at: datetime, ends_at: datetime
    ) -> tuple[Mapping[str, Any], ...]:
        return self._paginated(
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
            {
                "maxResults": "2500",
                "orderBy": "startTime",
                "showDeleted": "false",
                "singleEvents": "true",
                "timeMin": starts_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "timeMax": ends_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            },
        )

    def task_lists(self) -> tuple[GoogleCollection, ...]:
        items = self._paginated(
            f"{TASKS_API}/users/@me/lists", {"maxResults": "1000"}
        )
        return tuple(task_list_collection(item) for item in items)

    def tasks(self, task_list_id: str) -> tuple[Mapping[str, Any], ...]:
        return self._paginated(
            f"{TASKS_API}/lists/{quote(task_list_id, safe='')}/tasks",
            {
                "maxResults": "100",
                "showAssigned": "true",
                "showCompleted": "false",
                "showDeleted": "false",
                "showHidden": "false",
            },
        )

    def _paginated(
        self, url: str, parameters: Mapping[str, str]
    ) -> tuple[Mapping[str, Any], ...]:
        items: list[Mapping[str, Any]] = []
        page_token: str | None = None
        while True:
            query = dict(parameters)
            if page_token is not None:
                query["pageToken"] = page_token
            document = self._request_json(f"{url}?{urlencode(query)}")
            page_items = document.get("items", [])
            if not isinstance(page_items, list):
                raise GoogleApiError(
                    "invalid-upstream-response", "Google returned an invalid item page."
                )
            for item in page_items:
                if not isinstance(item, Mapping):
                    raise GoogleApiError(
                        "invalid-upstream-response",
                        "Google returned an invalid resource.",
                    )
                items.append(cast(Mapping[str, Any], item))
            next_token = document.get("nextPageToken")
            if next_token is None:
                return tuple(items)
            if not isinstance(next_token, str) or not next_token:
                raise GoogleApiError(
                    "invalid-upstream-response", "Google returned an invalid page token."
                )
            page_token = next_token

    def _request_json(self, url: str) -> Mapping[str, Any]:
        refreshed_after_401 = False
        for attempt in range(4):
            token = self._token()
            request = Request(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    document = json.load(response)
            except HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code == 401 and not refreshed_after_401:
                    self._access_token = None
                    self._expires_at = None
                    refreshed_after_401 = True
                    continue
                retryable = error.code == 429 or 500 <= error.code < 600
                if error.code == 403 and (
                    "rateLimitExceeded" in body or "userRateLimitExceeded" in body
                ):
                    retryable = True
                if retryable and attempt < 3:
                    self._sleeper(self._retry_delay(error.headers.get("Retry-After"), attempt))
                    continue
                code = "rate-limited" if retryable else "upstream-rejected"
                raise GoogleApiError(code, "Google rejected the read request.") from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt < 3:
                    self._sleeper(self._retry_delay(None, attempt))
                    continue
                raise GoogleApiError(
                    "upstream-unavailable", "Google could not be reached."
                ) from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise GoogleApiError(
                    "invalid-upstream-response", "Google returned invalid JSON."
                ) from error
            if not isinstance(document, Mapping):
                raise GoogleApiError(
                    "invalid-upstream-response", "Google returned an invalid response."
                )
            return cast(Mapping[str, Any], document)
        raise AssertionError("request retry loop did not return")

    def _token(self) -> str:
        now = datetime.now(UTC)
        if (
            self._access_token is not None
            and self._expires_at is not None
            and now + timedelta(seconds=30) < self._expires_at
        ):
            return self._access_token
        body = urlencode(
            {
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "refresh_token": self.credentials.refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("ascii")
        request = Request(
            self.credentials.token_uri,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                document = json.load(response)
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            code = "reconnect-required" if "invalid_grant" in body else "token-refresh-failed"
            detail = (
                "Google authorization must be reconnected."
                if code == "reconnect-required"
                else "Google authorization could not be refreshed."
            )
            raise GoogleApiError(code, detail) from error
        except (URLError, TimeoutError, OSError) as error:
            raise GoogleApiError(
                "token-refresh-failed", "Google authorization could not be refreshed."
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoogleApiError(
                "token-refresh-failed", "Google returned an invalid token response."
            ) from error
        if not isinstance(document, Mapping):
            raise GoogleApiError(
                "token-refresh-failed", "Google returned an invalid token response."
            )
        token = document.get("access_token")
        expires_in = document.get("expires_in", 3600)
        if not isinstance(token, str) or not token or not isinstance(expires_in, int):
            raise GoogleApiError(
                "token-refresh-failed", "Google returned an incomplete token response."
            )
        self._access_token = token
        self._expires_at = now + timedelta(seconds=max(60, expires_in))
        return token

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after is not None:
            try:
                return max(0.0, min(float(retry_after), 60.0))
            except ValueError:
                pass
        return min(8.0, (2**attempt) + random.random())
