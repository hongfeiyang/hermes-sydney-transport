"""Bounded authenticated transport for TfNSW GTFS and GTFS-Realtime feeds."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ...models.errors import DomainError
from ...models.metadata import USER_AGENT

TfnswApiError = DomainError


@dataclass(frozen=True, slots=True)
class BinaryResponse:
    data: bytes | None
    content_type: str | None
    last_modified: str | None
    not_modified: bool = False


class BinaryTransport(Protocol):
    def get(
        self, endpoint: str, *, if_modified_since: str | None = None
    ) -> BinaryResponse: ...


_ENDPOINTS = {
    "train_trip_updates": (
        "https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains",
        8 * 1024 * 1024,
        "application/x-google-protobuf",
    ),
    "train_vehicle_positions": (
        "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/sydneytrains",
        8 * 1024 * 1024,
        "application/x-google-protobuf",
    ),
    "train_static_schedule": (
        "https://api.transport.nsw.gov.au/v1/gtfs/schedule/sydneytrains",
        32 * 1024 * 1024,
        "application/zip",
    ),
    "bus_trip_updates": (
        "https://api.transport.nsw.gov.au/v1/gtfs/realtime/buses",
        32 * 1024 * 1024,
        "application/x-google-protobuf",
    ),
    "bus_vehicle_positions": (
        "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/buses",
        32 * 1024 * 1024,
        "application/x-google-protobuf",
    ),
    "bus_static_schedule": (
        "https://api.transport.nsw.gov.au/v1/gtfs/schedule/buses",
        128 * 1024 * 1024,
        "application/zip",
    ),
}
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class _RejectRedirects(HTTPRedirectHandler):
    """Do not forward the API key across redirects."""

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


class UrllibBinaryTransport:
    """Fetch only fixed TfNSW feed URLs with retries and hard byte limits."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
        mode: str = "train",
    ) -> None:
        if not api_key.strip():
            raise TfnswApiError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        if timeout_seconds <= 0 or max_attempts < 1:
            raise ValueError("timeout_seconds and max_attempts must be positive")
        if mode not in {"train", "bus"}:
            raise ValueError("mode must be train or bus")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._random_source = random_source
        self._mode = mode
        self._opener = build_opener(_RejectRedirects())

    def get(
        self, endpoint: str, *, if_modified_since: str | None = None
    ) -> BinaryResponse:
        try:
            url, max_bytes, accept = _ENDPOINTS[f"{self._mode}_{endpoint}"]
        except KeyError as exc:
            raise ValueError(f"TfNSW feed is not allowlisted: {endpoint}") from exc

        headers = {
            "Accept": accept,
            "Authorization": f"apikey {self._api_key}",
            "User-Agent": USER_AGENT,
        }
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since
        request = Request(url, headers=headers, method="GET")

        for attempt in range(self._max_attempts):
            try:
                with self._opener.open(
                    request, timeout=self._timeout_seconds
                ) as response:
                    raw = response.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        raise TfnswApiError(
                            "response_too_large",
                            "TfNSW returned more feed data than can be safely processed.",
                        )
                    return BinaryResponse(
                        data=raw,
                        content_type=response.headers.get("Content-Type"),
                        last_modified=response.headers.get("Last-Modified"),
                    )
            except HTTPError as exc:
                try:
                    if exc.code == 304:
                        return BinaryResponse(
                            data=None,
                            content_type=exc.headers.get("Content-Type"),
                            last_modified=exc.headers.get("Last-Modified"),
                            not_modified=True,
                        )
                    retryable = exc.code in _RETRYABLE_STATUS
                    if retryable and attempt + 1 < self._max_attempts:
                        retry_after = exc.headers.get("Retry-After")
                        self._sleeper(self._retry_delay(attempt, retry_after))
                        continue
                    message = (
                        "TfNSW rejected the API credential. Configure a current "
                        "TFNSW_API_KEY."
                        if exc.code in {401, 403}
                        else f"TfNSW feed request failed with HTTP {exc.code}."
                    )
                    raise TfnswApiError(
                        "authentication_failed"
                        if exc.code in {401, 403}
                        else "realtime_feed_unavailable",
                        message,
                        retryable=retryable,
                        http_status=exc.code,
                    ) from exc
                finally:
                    exc.close()
            except TfnswApiError:
                raise
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self._max_attempts:
                    self._sleeper(self._retry_delay(attempt, None))
                    continue
                raise TfnswApiError(
                    "realtime_feed_unavailable",
                    "TfNSW realtime data could not be reached before the deadline.",
                    retryable=True,
                ) from exc

        raise TfnswApiError(
            "realtime_feed_unavailable",
            "TfNSW realtime request attempts were exhausted.",
            retryable=True,
        )

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 5.0)
            except ValueError:
                pass
        jitter = float(self._random_source()) * 0.1
        return float(min(0.25 * (2**attempt) + jitter, 2.0))
