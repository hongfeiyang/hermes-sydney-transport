"""TfNSW Live Traffic hazards adapter."""

from __future__ import annotations

import json
import math
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import ValidationError

from ...models.errors import DomainError
from ...models.metadata import USER_AGENT
from ...ports.live_traffic import (
    HazardLinkRecord,
    HazardQuery,
    HazardRecord,
    HazardRoadRecord,
)
from .live_traffic_wire import FeatureCollectionWire, FeatureWire, RoadWire, WebLinkWire
from .trip_planner import html_to_plaintext

_BASE_URL = "https://api.transport.nsw.gov.au/v1/live/hazards"
_ENDPOINTS = {
    "incident": "/incident/open",
    "fire": "/fire/open",
    "flood": "/flood/open",
    "alpine": "/alpine/open",
    "major_event": "/majorevent/open",
    "roadwork": "/roadwork/open",
    "regional_lga_incident": "/regional-lga-incident/open",
}
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


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


class LiveTrafficTransport:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not api_key.strip():
            raise DomainError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._random_source = random_source
        self._opener = build_opener(_RejectRedirects())

    def get_collection(self, path: str) -> FeatureCollectionWire:
        if path not in _ENDPOINTS.values():
            raise ValueError(f"Live Traffic endpoint is not allowlisted: {path}")
        request = Request(
            f"{_BASE_URL}{path}",
            headers={
                "Accept": "application/json",
                "Authorization": f"apikey {self._api_key}",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        for attempt in range(self._max_attempts):
            try:
                with self._opener.open(
                    request, timeout=self._timeout_seconds
                ) as response:
                    raw = response.read(_MAX_RESPONSE_BYTES + 1)
                    if len(raw) > _MAX_RESPONSE_BYTES:
                        raise DomainError(
                            "response_too_large",
                            "TfNSW returned more live hazard data than can be processed safely.",
                        )
                    return _validate_collection(raw)
            except HTTPError as exc:
                try:
                    retryable = exc.code in _RETRYABLE_STATUS
                    if retryable and attempt + 1 < self._max_attempts:
                        self._sleeper(
                            _retry_delay(
                                attempt,
                                exc.headers.get("Retry-After"),
                                self._random_source,
                            )
                        )
                        continue
                    raise DomainError(
                        "authentication_failed"
                        if exc.code in {401, 403}
                        else "upstream_http_error",
                        "TfNSW rejected the API credential."
                        if exc.code in {401, 403}
                        else f"TfNSW Live Traffic request failed with HTTP {exc.code}.",
                        retryable=retryable,
                        http_status=exc.code,
                    ) from exc
                finally:
                    exc.close()
            except DomainError:
                raise
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self._max_attempts:
                    self._sleeper(_retry_delay(attempt, None, self._random_source))
                    continue
                raise DomainError(
                    "upstream_unavailable",
                    "TfNSW Live Traffic data could not be reached before the deadline.",
                    retryable=True,
                ) from exc
        raise DomainError(
            "upstream_unavailable",
            "TfNSW Live Traffic request attempts were exhausted.",
            retryable=True,
        )


class TfnswLiveTrafficAdapter:
    def __init__(
        self,
        transport: LiveTrafficTransport,
        *,
        cache_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if cache_seconds < 0 or cache_seconds > 120:
            raise ValueError("cache_seconds must be between 0 and 120")
        self._transport = transport
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, FeatureCollectionWire]] = {}

    def find_hazards(self, query: HazardQuery) -> tuple[HazardRecord, ...]:
        records: list[HazardRecord] = []
        for hazard_type in query.hazard_types:
            collection = self._collection(hazard_type)
            for feature in collection.features:
                record = _hazard_record(feature, hazard_type, query)
                if _matches(feature, record, query):
                    records.append(record)
        records.sort(key=lambda item: item.display_name)
        records.sort(
            key=lambda item: item.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        records.sort(key=lambda item: item.is_major, reverse=True)
        records.sort(
            key=lambda item: (
                item.distance_metres if item.distance_metres is not None else 10**9
            )
        )
        return tuple(records[: query.limit])

    def _collection(self, hazard_type: str) -> FeatureCollectionWire:
        with self._lock:
            now = self._monotonic()
            cached = self._cache.get(hazard_type)
            if cached is not None and now < cached[0]:
                return cached[1]
            collection = self._transport.get_collection(_ENDPOINTS[hazard_type])
            self._cache[hazard_type] = (now + self._cache_seconds, collection)
            return collection


def _validate_collection(raw: bytes) -> FeatureCollectionWire:
    try:
        payload = json.loads(raw.decode("utf-8"))
        return FeatureCollectionWire.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise DomainError(
            "invalid_upstream_response",
            "TfNSW returned an invalid Live Traffic GeoJSON response.",
        ) from exc


def _retry_delay(
    attempt: int, retry_after: str | None, random_source: Callable[[], float]
) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), 5.0)
        except ValueError:
            pass
    return float(min(0.25 * (2**attempt) + random_source() * 0.1, 2.0))


def _hazard_record(
    feature: FeatureWire, hazard_type: str, query: HazardQuery
) -> HazardRecord:
    latitude, longitude = _coordinates(feature)
    props = feature.properties
    return HazardRecord(
        id=str(feature.id),
        hazard_type=hazard_type,
        incident_kind=_clean(props.incidentKind).lower() or "unknown",
        display_name=_clean(props.displayName)
        or _clean(props.headline)
        or "Traffic hazard",
        headline=_clean(props.headline) or None,
        main_category=_clean(props.mainCategory) or None,
        advice=tuple(
            text
            for text in (
                _clean(props.adviceA),
                _clean(props.adviceB),
                _clean(props.adviceC),
            )
            if text
        ),
        other_advice=html_to_plaintext(props.otherAdvice, max_chars=1200),
        public_transport=html_to_plaintext(props.publicTransport, max_chars=1200),
        impacting_network=props.impactingNetwork,
        ended=props.ended,
        is_major=props.isMajor,
        expected_delay_minutes=_positive_int(props.expectedDelay),
        speed_limit_kmh=_positive_int(props.speedLimit),
        updated_at=_unix_millis(props.lastUpdated),
        start_at=_unix_millis(props.start),
        end_at=_unix_millis(props.end),
        latitude=latitude,
        longitude=longitude,
        distance_metres=_distance_metres(latitude, longitude, query),
        roads=tuple(_road_record(road) for road in props.roads[:3]),
        links=tuple(
            link for link in (_link_record(item) for item in props.webLinks[:3]) if link
        ),
    )


def _matches(feature: FeatureWire, record: HazardRecord, query: HazardQuery) -> bool:
    if query.suburb is not None:
        target = query.suburb.casefold()
        return any(
            _clean(road.suburb).casefold() == target
            for road in feature.properties.roads
        )
    if query.radius_metres is None:
        return True
    return (
        record.distance_metres is not None
        and record.distance_metres <= query.radius_metres
    )


def _coordinates(feature: FeatureWire) -> tuple[float, float]:
    longitude = float(feature.geometry.coordinates[0])
    latitude = float(feature.geometry.coordinates[1])
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise DomainError(
            "invalid_upstream_response",
            "TfNSW returned a Live Traffic coordinate outside WGS84 bounds.",
        )
    return latitude, longitude


def _road_record(item: RoadWire) -> HazardRoadRecord:
    return HazardRoadRecord(
        main_street=_clean(item.mainStreet) or None,
        cross_street=_clean(item.crossStreet) or None,
        location_qualifier=_clean(item.locationQualifier) or None,
        second_location=_clean(item.secondLocation) or None,
        suburb=_clean(item.suburb) or None,
        region=_clean(item.region) or None,
        traffic_volume=_clean(item.trafficVolume) or None,
        delay=_clean(item.delay) or None,
        queue_length_km=_non_negative_float(item.queueLength),
    )


def _link_record(item: WebLinkWire) -> HazardLinkRecord | None:
    text = _clean(item.linkText)
    url = _safe_url(_clean(item.linkURL))
    return HazardLinkRecord(text=text, url=url) if text and url else None


def _clean(value: str | None) -> str:
    return " ".join(value.split()) if value else ""


def _positive_int(value: int | None) -> int | None:
    return value if value is not None and value > 0 else None


def _non_negative_float(value: float | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if parsed >= 0 else None


def _unix_millis(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, tz=UTC) if value and value > 0 else None


def _distance_metres(
    latitude: float, longitude: float, query: HazardQuery
) -> int | None:
    if query.latitude is None or query.longitude is None:
        return None
    lat1 = math.radians(query.latitude)
    lon1 = math.radians(query.longitude)
    lat2 = math.radians(latitude)
    lon2 = math.radians(longitude)
    arc = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return round(2 * 6371000 * math.asin(min(1.0, math.sqrt(arc))))


def _safe_url(value: str) -> str | None:
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
