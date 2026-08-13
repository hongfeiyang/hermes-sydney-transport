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
from ...ports.realtime import TransportMode

TfnswApiError = DomainError


@dataclass(frozen=True, slots=True)
class BinaryResponse:
    data: bytes | None
    content_type: str | None
    last_modified: str | None
    not_modified: bool = False


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    url: str
    max_bytes: int
    accept: str


class BinaryTransport(Protocol):
    def get(
        self, endpoint: str, *, if_modified_since: str | None = None
    ) -> BinaryResponse: ...

    def get_all(
        self, endpoint: str, *, if_modified_since: str | None = None
    ) -> tuple[BinaryResponse, ...]: ...


_PROTOBUF = "application/x-google-protobuf"
_ZIP = "application/zip"
_MODE_ENDPOINTS: dict[TransportMode, dict[str, tuple[EndpointSpec, ...]]] = {
    TransportMode.TRAIN: {
        "alerts": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/alerts/sydneytrains",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/alerts/nswtrains",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "trip_updates": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "vehicle_positions": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/sydneytrains",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "static_schedule": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/sydneytrains",
                32 * 1024 * 1024,
                _ZIP,
            ),
        ),
    },
    TransportMode.BUS: {
        "alerts": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/alerts/buses",
                32 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/alerts/regionbuses",
                16 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "trip_updates": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/realtime/buses",
                32 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "vehicle_positions": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/buses",
                32 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "static_schedule": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/buses",
                128 * 1024 * 1024,
                _ZIP,
            ),
        ),
    },
    TransportMode.METRO: {
        "alerts": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/alerts/metro",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "trip_updates": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/realtime/metro",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "vehicle_positions": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/metro",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "static_schedule": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/schedule/metro",
                32 * 1024 * 1024,
                _ZIP,
            ),
        ),
    },
    TransportMode.LIGHT_RAIL: {
        "alerts": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/alerts/lightrail",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "trip_updates": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/realtime/lightrail/innerwest",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/realtime/lightrail/cbdandsoutheast",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/realtime/lightrail/newcastle",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/realtime/lightrail/parramatta",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "vehicle_positions": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/cbdandsoutheast",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/innerwest",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/newcastle",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/parramatta",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "static_schedule": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/cbdandsoutheast",
                16 * 1024 * 1024,
                _ZIP,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/innerwest",
                16 * 1024 * 1024,
                _ZIP,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/newcastle",
                16 * 1024 * 1024,
                _ZIP,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/parramatta",
                16 * 1024 * 1024,
                _ZIP,
            ),
        ),
    },
    TransportMode.FERRY: {
        "alerts": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v2/gtfs/alerts/ferries",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "trip_updates": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/realtime/ferries/sydneyferries",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/realtime/ferries/MFF",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "vehicle_positions": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/ferries/sydneyferries",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/ferries/MFF",
                8 * 1024 * 1024,
                _PROTOBUF,
            ),
        ),
        "static_schedule": (
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/ferries/sydneyferries",
                16 * 1024 * 1024,
                _ZIP,
            ),
            EndpointSpec(
                "https://api.transport.nsw.gov.au/v1/gtfs/schedule/ferries/MFF",
                16 * 1024 * 1024,
                _ZIP,
            ),
        ),
    },
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
        mode: TransportMode | str = TransportMode.TRAIN,
    ) -> None:
        if not api_key.strip():
            raise TfnswApiError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        if timeout_seconds <= 0 or max_attempts < 1:
            raise ValueError("timeout_seconds and max_attempts must be positive")
        mode_value = TransportMode(mode)
        if mode_value not in _MODE_ENDPOINTS:
            raise ValueError(f"unsupported transport mode: {mode}")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._random_source = random_source
        self._mode = mode_value
        self._opener = build_opener(_RejectRedirects())

    def get(
        self, endpoint: str, *, if_modified_since: str | None = None
    ) -> BinaryResponse:
        try:
            specs = _MODE_ENDPOINTS[self._mode][endpoint]
        except KeyError as exc:
            raise ValueError(f"TfNSW feed is not allowlisted: {endpoint}") from exc
        if len(specs) != 1:
            raise ValueError(
                f"TfNSW feed {endpoint!r} for mode {self._mode.value!r} requires "
                "get_all() because it maps to multiple upstream feeds."
            )
        return self._fetch(specs[0], if_modified_since)

    def get_all(
        self, endpoint: str, *, if_modified_since: str | None = None
    ) -> tuple[BinaryResponse, ...]:
        try:
            specs = _MODE_ENDPOINTS[self._mode][endpoint]
        except KeyError as exc:
            raise ValueError(f"TfNSW feed is not allowlisted: {endpoint}") from exc
        return tuple(self._fetch(spec, if_modified_since) for spec in specs)

    def _fetch(
        self, spec: EndpointSpec, if_modified_since: str | None
    ) -> BinaryResponse:
        headers = {
            "Accept": spec.accept,
            "Authorization": f"apikey {self._api_key}",
            "User-Agent": USER_AGENT,
        }
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since
        request = Request(spec.url, headers=headers, method="GET")

        for attempt in range(self._max_attempts):
            try:
                with self._opener.open(
                    request, timeout=self._timeout_seconds
                ) as response:
                    raw = response.read(spec.max_bytes + 1)
                    if len(raw) > spec.max_bytes:
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
