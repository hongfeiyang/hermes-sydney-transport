"""Streaming transport for a closed set of official TfNSW static resources."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ...models.errors import DomainError
from ...models.metadata import USER_AGENT

_CHUNK_BYTES = 128 * 1024
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_RESOURCES = {
    "complete_gtfs": (
        "https://api.transport.nsw.gov.au/v1/publictransport/timetables/complete/gtfs",
        384 * 1024 * 1024,
        "application/octet-stream",
        True,
    ),
    "location_facilities": (
        (
            "https://opendata.transport.nsw.gov.au/data/dataset/"
            "25f006fd-d0fb-4a8e-bfda-7ea4033c1aeb/resource/"
            "e9d94351-f22d-46ea-b64d-10e7e238368a/download/locationfacilitydata.csv"
        ),
        4 * 1024 * 1024,
        "text/csv",
        False,
    ),
    "interchange_lifts": (
        (
            "https://opendata.transport.nsw.gov.au/data/dataset/"
            "5ac00c2d-c5fb-48e1-b45a-b4d49be815f3/resource/"
            "c9b79c0f-4403-4f41-af0f-1fe8deaa6a33/download/"
            "interchange-facilities-lifts_may-2025.xlsx"
        ),
        8 * 1024 * 1024,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        False,
    ),
}


@dataclass(frozen=True, slots=True)
class StaticDownload:
    not_modified: bool
    last_modified: datetime | None


class StaticResourceTransport(Protocol):
    def download(
        self,
        resource: str,
        destination: Path,
        *,
        if_modified_since: datetime | None = None,
    ) -> StaticDownload: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class UrllibStaticResourceTransport:
    """Download only allowlisted resources, with bounded streaming and no redirects."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 60.0,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not api_key.strip():
            raise DomainError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        if timeout_seconds <= 0 or max_attempts < 1:
            raise ValueError("timeout_seconds and max_attempts must be positive")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._random_source = random_source
        self._opener = build_opener(_RejectRedirects())

    def download(
        self,
        resource: str,
        destination: Path,
        *,
        if_modified_since: datetime | None = None,
    ) -> StaticDownload:
        try:
            url, max_bytes, accept, authenticated = _RESOURCES[resource]
        except KeyError as exc:
            raise ValueError(
                f"TfNSW static resource is not allowlisted: {resource}"
            ) from exc
        headers = {"Accept": accept, "User-Agent": USER_AGENT}
        if authenticated:
            headers["Authorization"] = f"apikey {self._api_key}"
        if if_modified_since is not None:
            headers["If-Modified-Since"] = format_datetime(
                if_modified_since.astimezone(UTC), usegmt=True
            )
        request = Request(url, headers=headers, method="GET")
        destination.unlink(missing_ok=True)

        for attempt in range(self._max_attempts):
            try:
                with self._opener.open(
                    request, timeout=self._timeout_seconds
                ) as response:
                    declared = response.headers.get("Content-Length")
                    if declared and int(declared) > max_bytes:
                        raise DomainError(
                            "response_too_large",
                            "TfNSW static resource exceeds its download limit.",
                        )
                    total = 0
                    with destination.open("wb") as output:
                        while chunk := response.read(_CHUNK_BYTES):
                            total += len(chunk)
                            if total > max_bytes:
                                raise DomainError(
                                    "response_too_large",
                                    "TfNSW static resource exceeds its download limit.",
                                )
                            output.write(chunk)
                    return StaticDownload(
                        not_modified=False,
                        last_modified=_http_datetime(
                            response.headers.get("Last-Modified")
                        ),
                    )
            except HTTPError as exc:
                try:
                    if exc.code == 304:
                        return StaticDownload(
                            not_modified=True,
                            last_modified=_http_datetime(
                                exc.headers.get("Last-Modified")
                            ),
                        )
                    retryable = exc.code in _RETRYABLE_STATUS
                    if retryable and attempt + 1 < self._max_attempts:
                        self._sleeper(self._retry_delay(attempt))
                        continue
                    raise DomainError(
                        "authentication_failed"
                        if exc.code in {401, 403}
                        else "static_data_unavailable",
                        "TfNSW rejected the API credential."
                        if exc.code in {401, 403}
                        else f"TfNSW static resource failed with HTTP {exc.code}.",
                        retryable=retryable,
                        http_status=exc.code,
                    ) from exc
                finally:
                    exc.close()
            except DomainError:
                destination.unlink(missing_ok=True)
                raise
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                destination.unlink(missing_ok=True)
                if attempt + 1 < self._max_attempts:
                    self._sleeper(self._retry_delay(attempt))
                    continue
                raise DomainError(
                    "static_data_unavailable",
                    "TfNSW static data could not be reached before the deadline.",
                    retryable=True,
                ) from exc
        raise DomainError(
            "static_data_unavailable",
            "TfNSW static resource attempts were exhausted.",
            retryable=True,
        )

    def _retry_delay(self, attempt: int) -> float:
        return float(min(0.25 * (2**attempt) + float(self._random_source()) * 0.1, 2.0))


def _http_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
