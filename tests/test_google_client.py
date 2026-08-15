from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from mission_control.builtin_plugins.google.client import (
    AuthorizedUserCredentials,
    GoogleApiError,
    GoogleHttpClient,
)


class JsonResponse(BytesIO):
    def __init__(self, document: object) -> None:
        super().__init__(json.dumps(document).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()


def credentials() -> AuthorizedUserCredentials:
    return AuthorizedUserCredentials("client", "secret", "refresh")


def test_authorization_fingerprint_changes_without_exposing_credentials():
    first = credentials().source_fingerprint()
    second = AuthorizedUserCredentials("client", "secret", "other").source_fingerprint()

    assert first != second
    assert "refresh" not in first
    assert len(first) == 64


def test_calendar_events_are_paginated_with_bounded_expansion_parameters():
    urls: list[str] = []
    pages = iter(
        [
            {"items": [{"id": "first"}], "nextPageToken": "next page"},
            {"items": [{"id": "second"}]},
        ]
    )

    def opener(request, *, timeout):
        assert timeout == 9
        urls.append(request.full_url)
        assert request.get_header("Authorization") == "Bearer access"
        return JsonResponse(next(pages))

    client = GoogleHttpClient(credentials(), timeout_seconds=9, opener=opener)
    client._access_token = "access"
    client._expires_at = datetime.now(UTC) + timedelta(hours=1)

    events = client.events(
        "family/calendar",
        starts_at=datetime(2026, 8, 14, tzinfo=UTC),
        ends_at=datetime(2026, 8, 22, tzinfo=UTC),
    )

    assert [item["id"] for item in events] == ["first", "second"]
    assert "/family%2Fcalendar/events" in urls[0]
    first_query = parse_qs(urlparse(urls[0]).query)
    assert first_query == {
        "maxResults": ["2500"],
        "orderBy": ["startTime"],
        "showDeleted": ["false"],
        "singleEvents": ["true"],
        "timeMax": ["2026-08-22T00:00:00Z"],
        "timeMin": ["2026-08-14T00:00:00Z"],
    }
    assert parse_qs(urlparse(urls[1]).query)["pageToken"] == ["next page"]


def test_one_unauthorized_response_refreshes_in_memory_token_once():
    api_headers: list[str] = []
    token_requests = 0

    def opener(request, *, timeout):
        nonlocal token_requests
        assert timeout == 15
        if request.full_url == "https://oauth2.googleapis.com/token":
            token_requests += 1
            assert b"refresh_token=refresh" in request.data
            return JsonResponse({"access_token": "new-access", "expires_in": 3600})
        api_headers.append(request.get_header("Authorization"))
        if len(api_headers) == 1:
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {},
                BytesIO(b"{}"),
            )
        return JsonResponse({"items": []})

    client = GoogleHttpClient(credentials(), opener=opener)
    client._access_token = "old-access"
    client._expires_at = datetime.now(UTC) + timedelta(hours=1)

    assert client.task_lists() == ()
    assert api_headers == ["Bearer old-access", "Bearer new-access"]
    assert token_requests == 1


def test_authorized_user_file_rejects_broad_posix_permissions(tmp_path):
    credential = tmp_path / "oauth.json"
    credential.write_text(
        json.dumps(
            {
                "client_id": "client",
                "client_secret": "secret",
                "refresh_token": "refresh",
            }
        ),
        encoding="utf-8",
    )
    credential.chmod(0o640)

    with pytest.raises(GoogleApiError, match="must not be accessible"):
        AuthorizedUserCredentials.load(credential)


def test_authorized_user_file_rejects_non_google_token_endpoint(tmp_path):
    credential = tmp_path / "oauth.json"
    credential.write_text(
        json.dumps(
            {
                "client_id": "client",
                "client_secret": "secret",
                "refresh_token": "refresh",
                "token_uri": "https://example.invalid/token",
            }
        ),
        encoding="utf-8",
    )
    credential.chmod(0o600)

    with pytest.raises(GoogleApiError, match="Google's token endpoint"):
        AuthorizedUserCredentials.load(credential)
