"""TfNSW transport and normalization behind Pydantic contracts."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from ...models.errors import DomainError
from ...models.inputs import (
    AlertsInput,
    DeparturesInput,
    NearbyStopsInput,
    StationSearchInput,
    TripPlanInput,
)
from ...models.metadata import USER_AGENT
from ...models.outputs import (
    Alert,
    NearbyStop,
    Route,
    Station,
    SystemMessage,
    TripLeg,
)
from ...ports.trip_planner import (
    DepartureBoard,
    DepartureCandidate,
    JourneyBoard,
    JourneyCandidate,
    ServiceResolution,
)

API_BASE_URL = "https://api.transport.nsw.gov.au/v1/tp"
SYDNEY_TZ = ZoneInfo("Australia/Sydney")
_ALLOWED_PATHS = frozenset(
    {"/stop_finder", "/departure_mon", "/add_info", "/coord", "/trip"}
)
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_MAX_ALERT_TEXT = 2_000
_MOT_CODES = {
    "train": 1,
    "metro": 2,
    "light_rail": 4,
    "bus": 5,
    "ferry": 9,
}
_EXCLUDABLE_MOT_CODES = (1, 2, 4, 5, 7, 9, 11)


TfnswApiError = DomainError


class _PlainTextExtractor(HTMLParser):
    """Convert the small HTML subset in TfNSW alert text to bounded plaintext."""

    _BREAK_TAGS = frozenset({"br", "div", "li", "p", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class _RejectRedirects(HTTPRedirectHandler):
    """Keep the API credential pinned to the configured TfNSW origin."""

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


def html_to_plaintext(value: object, *, max_chars: int = _MAX_ALERT_TEXT) -> str:
    if not isinstance(value, str) or not value:
        return ""
    parser = _PlainTextExtractor()
    parser.feed(value)
    parser.close()
    text = " ".join("".join(parser.parts).split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


class UrllibJsonTransport:
    """Allowlisted HTTPS transport with bounded retries and response sizes."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not api_key.strip():
            raise TfnswApiError(
                "missing_configuration",
                "TFNSW_API_KEY is not configured.",
            )
        if timeout_seconds <= 0 or max_attempts < 1:
            raise ValueError("timeout_seconds and max_attempts must be positive")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._random_source = random_source
        self._opener = build_opener(_RejectRedirects())

    def get_json(
        self,
        path: str,
        params: Sequence[tuple[str, str]],
    ) -> Mapping[str, Any]:
        if path not in _ALLOWED_PATHS:
            raise ValueError(f"TfNSW endpoint is not allowlisted: {path}")
        url = f"{API_BASE_URL}{path}?{urlencode(params, doseq=True)}"
        request = Request(
            url,
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
                        raise TfnswApiError(
                            "response_too_large",
                            "TfNSW returned more data than this tool can safely process.",
                        )
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise TfnswApiError(
                            "invalid_upstream_response",
                            "TfNSW returned an invalid JSON response.",
                        ) from exc
                    if not isinstance(payload, Mapping):
                        raise TfnswApiError(
                            "invalid_upstream_response",
                            "TfNSW returned an unexpected response shape.",
                        )
                    return payload
            except HTTPError as exc:
                try:
                    retryable = exc.code in _RETRYABLE_STATUS
                    if retryable and attempt + 1 < self._max_attempts:
                        retry_after = (
                            exc.headers.get("Retry-After")
                            if exc.headers is not None
                            else None
                        )
                        self._sleeper(self._retry_delay(attempt, retry_after))
                        continue
                    message = (
                        "TfNSW rejected the API credential. Configure a current "
                        "TFNSW_API_KEY."
                        if exc.code in {401, 403}
                        else f"TfNSW request failed with HTTP {exc.code}."
                    )
                    raise TfnswApiError(
                        "authentication_failed"
                        if exc.code in {401, 403}
                        else "upstream_http_error",
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
                    "upstream_unavailable",
                    "TfNSW could not be reached before the request deadline.",
                    retryable=True,
                ) from exc

        raise TfnswApiError(
            "upstream_unavailable", "TfNSW request attempts were exhausted.", True
        )

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 5.0)
            except ValueError:
                pass
        jitter = float(self._random_source()) * 0.1
        return float(min(0.25 * (2**attempt) + jitter, 2.0))


class _JsonTransport(Protocol):
    def get_json(
        self, path: str, params: Sequence[tuple[str, str]]
    ) -> Mapping[str, Any]: ...


class TfnswClient:
    """Translate typed semantic queries to and from the TfNSW wire protocol."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: _JsonTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise TfnswApiError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        self._transport = transport or UrllibJsonTransport(api_key)

    def station_candidates(self, request: StationSearchInput) -> tuple[Station, ...]:
        payload = self._transport.get_json(
            "/stop_finder",
            [
                ("outputFormat", "rapidJSON"),
                ("coordOutputFormat", "EPSG:4326"),
                # The current TfNSW engine rejects type_sf=stop with BROKER
                # -2000. Search all location types, then apply the requested-mode
                # allowlist while normalising the response.
                ("type_sf", "any"),
                ("name_sf", request.query),
                ("TfNSWSF", "true"),
            ],
        )
        _raise_payload_error(payload)
        raw_locations = payload.get("locations")
        locations = raw_locations if isinstance(raw_locations, list) else []
        stations: list[Station] = []
        for item in locations:
            if not isinstance(item, Mapping):
                continue
            station = _normalise_station(item)
            if station is not None:
                stations.append(Station.model_validate(station))
        return tuple(stations)

    def nearby_candidates(self, request: NearbyStopsInput) -> tuple[NearbyStop, ...]:
        payload = self._transport.get_json(
            "/coord",
            [
                ("outputFormat", "rapidJSON"),
                (
                    "coord",
                    f"{request.longitude:.6f}:{request.latitude:.6f}:EPSG:4326",
                ),
                ("coordOutputFormat", "EPSG:4326"),
                ("inclFilter", "1"),
                ("type_1", "BUS_POINT"),
                ("radius_1", str(request.radius_metres)),
                ("PoisOnMapMacro", "true"),
            ],
        )
        _raise_payload_error(payload)
        raw_locations = payload.get("locations")
        locations = raw_locations if isinstance(raw_locations, list) else []
        return tuple(
            NearbyStop.model_validate(stop)
            for stop in _normalise_nearby_stops(locations)
        )

    def departure_candidates(self, request: DeparturesInput) -> DepartureBoard:
        if request.at is None:
            raise ValueError("application must supply an effective departure time")
        query_time = request.at
        payload = self._transport.get_json(
            "/departure_mon",
            _departure_params(request.stop_id, query_time, request.modes),
        )
        _raise_payload_error(payload)
        raw_events = payload.get("stopEvents")
        events = raw_events if isinstance(raw_events, list) else []
        candidates = [
            _normalise_departure(event)
            for event in events
            if isinstance(event, Mapping)
        ]
        locations = payload.get("locations")
        station = None
        if (
            isinstance(locations, list)
            and locations
            and isinstance(locations[0], Mapping)
        ):
            raw_station = _normalise_station(locations[0])
            station = Station.model_validate(raw_station) if raw_station else None
        return DepartureBoard(
            station=station,
            candidates=tuple(candidate for candidate in candidates if candidate),
        )

    def resolve_service_id(
        self,
        trip_code: str,
        stop_id: str,
        at: datetime,
        mode: str = "train",
    ) -> ServiceResolution:
        """Resolve an opaque Trip Planner code to the exact GTFS-R trip identity."""

        query_time = _ensure_sydney_time(at)
        payload = self._transport.get_json(
            "/departure_mon", _departure_params(stop_id, query_time, [mode])
        )
        _raise_payload_error(payload)
        raw_events = payload.get("stopEvents")
        events = raw_events if isinstance(raw_events, list) else []
        candidates: dict[str, ServiceResolution] = {}
        for event in events:
            if not isinstance(event, Mapping) or not _is_requested_departure(
                event, [mode]
            ):
                continue
            transport = event.get("transportation")
            transport = transport if isinstance(transport, Mapping) else {}
            transport_properties = transport.get("properties")
            transport_properties = (
                transport_properties
                if isinstance(transport_properties, Mapping)
                else {}
            )
            if _string(transport_properties.get("tripCode"), 100) != trip_code:
                continue
            event_properties = event.get("properties")
            event_properties = (
                event_properties if isinstance(event_properties, Mapping) else {}
            )
            service_id = _string(event_properties.get("RealtimeTripId"), 160)
            if not service_id:
                continue
            candidates[service_id] = ServiceResolution(
                service_id=service_id,
                planned_time=_normalise_timestamp(
                    _first_string(event, "departureTimePlanned", "plannedDepartureTime")
                ),
            )
        if not candidates:
            raise TfnswApiError(
                "service_not_found",
                "No current departure matched that trip_code at the supplied stop. "
                "Pass service_id from departures, or include the planned departure time.",
            )
        if len(candidates) == 1:
            return next(iter(candidates.values()))

        ranked: list[tuple[float, ServiceResolution]] = []
        for candidate in candidates.values():
            planned = candidate.planned_time
            if planned is None:
                continue
            try:
                planned_time = datetime.fromisoformat(planned)
            except ValueError:
                continue
            ranked.append(
                (
                    abs(
                        (
                            planned_time - at.astimezone(planned_time.tzinfo)
                        ).total_seconds()
                    ),
                    candidate,
                )
            )
        ranked.sort(key=lambda item: item[0])
        if ranked and (len(ranked) == 1 or ranked[0][0] < ranked[1][0]):
            return ranked[0][1]
        raise TfnswApiError(
            "ambiguous_service",
            "More than one departure matched that trip_code. Pass service_id from "
            "departures or provide the exact planned departure time.",
        )

    def journey_candidates(self, request: TripPlanInput) -> JourneyBoard:
        if request.at is None:
            raise ValueError("application must supply an effective journey time")
        query_time = request.at
        params = [
            ("outputFormat", "rapidJSON"),
            ("coordOutputFormat", "EPSG:4326"),
            ("depArrMacro", "dep" if request.time_mode == "depart" else "arr"),
            ("itdDate", query_time.strftime("%Y%m%d")),
            ("itdTime", query_time.strftime("%H%M")),
            ("type_origin", "any"),
            ("name_origin", request.origin_stop_id),
            ("type_destination", "any"),
            ("name_destination", request.destination_stop_id),
            ("calcNumberOfTrips", str(request.limit)),
            ("excludedMeans", "checkbox"),
        ]
        included = {_MOT_CODES[mode] for mode in request.modes}
        for mode_code in _EXCLUDABLE_MOT_CODES:
            if mode_code not in included:
                params.append((f"exclMOT_{mode_code}", "1"))
        if request.wheelchair:
            params.append(("wheelchair", "on"))
        params.append(("TfNSWTR", "true"))
        payload = self._transport.get_json("/trip", params)
        _raise_payload_error(payload)
        raw_journeys = payload.get("journeys")
        journeys = raw_journeys if isinstance(raw_journeys, list) else []
        normalised = [
            result
            for item in journeys
            if isinstance(item, Mapping)
            for result in [_normalise_journey(item)]
            if result is not None
        ]
        return JourneyBoard(
            candidates=tuple(normalised),
            system_messages=tuple(
                SystemMessage.model_validate(message)
                for message in _normalise_system_messages(payload.get("systemMessages"))
            ),
        )

    def alert_candidates(self, request: AlertsInput) -> tuple[Alert, ...]:
        params = [
            ("outputFormat", "rapidJSON"),
            ("filterPublicationStatus", "current"),
        ]
        for mode in request.modes:
            params.append(("filterMOTType", str(_MOT_CODES[mode])))
        if request.stop_id:
            params.append(("itdLPxx_selStop", request.stop_id))
        payload = self._transport.get_json("/add_info", params)
        _raise_payload_error(payload)
        infos = payload.get("infos")
        current = infos.get("current") if isinstance(infos, Mapping) else []
        alerts = [
            _normalise_alert(item)
            for item in current or []
            if isinstance(item, Mapping)
        ]
        return tuple(Alert.model_validate(alert) for alert in alerts)


def _ensure_sydney_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SYDNEY_TZ)
    return value.astimezone(SYDNEY_TZ)


def _raise_payload_error(payload: Mapping[str, Any]) -> None:
    error = payload.get("error")
    if not error:
        return
    message = error.get("message") if isinstance(error, Mapping) else None
    raise TfnswApiError(
        "upstream_api_error",
        html_to_plaintext(message) or "TfNSW returned an API error.",
    )


def _normalise_station(
    item: Mapping[str, Any],
) -> dict[str, Any] | None:
    station_id = _string(item.get("id"), 64)
    name = _string(item.get("name"), 300)
    if not station_id or not name or item.get("type") not in {None, "stop", "platform"}:
        return None
    modes = _integer_list(item.get("modes"))
    coord = item.get("coord")
    coordinates = None
    if (
        isinstance(coord, list)
        and len(coord) >= 2
        and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in coord[:2]
        )
    ):
        coordinates = {"latitude": coord[0], "longitude": coord[1]}
    parent = item.get("parent")
    return {
        "id": station_id,
        "name": name,
        "short_name": _string(item.get("disassembledName"), 200),
        "parent_name": _string(parent.get("name"), 300)
        if isinstance(parent, Mapping)
        else None,
        "modes": modes,
        "match_quality": _integer(item.get("matchQuality"), default=0),
        "is_best": bool(item.get("isBest", False)),
        "coordinates": coordinates,
    }


def _normalise_nearby_stops(
    locations: Sequence[object],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in locations[:1000]:
        if not isinstance(item, Mapping):
            continue
        properties = item.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        stop_id = _string(properties.get("STOP_GLOBAL_ID") or item.get("id"), 128)
        name = _string(
            properties.get("STOP_NAME_WITH_PLACE")
            or properties.get("STOP_NAME")
            or item.get("name"),
            300,
        )
        if not stop_id or not name:
            continue
        distance = _integer(properties.get("distance"), default=None)
        coord = item.get("coord")
        coordinates = None
        if (
            isinstance(coord, list)
            and len(coord) >= 2
            and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in coord[:2]
            )
        ):
            coordinates = {"latitude": coord[0], "longitude": coord[1]}
        platform = _string(
            properties.get("STOP_POINT_LONGNAME")
            or (
                item.get("disassembledName") if item.get("type") == "platform" else None
            ),
            120,
        )
        location_type = _string(item.get("type"), 40)
        existing = by_id.get(stop_id)
        if existing is None:
            existing = {
                "id": stop_id,
                "name": name,
                "distance_metres": distance,
                "coordinates": coordinates,
                "location_types": [],
                "platforms": [],
            }
            by_id[stop_id] = existing
        elif distance is not None and (
            existing["distance_metres"] is None
            or distance < existing["distance_metres"]
        ):
            existing["distance_metres"] = distance
            existing["coordinates"] = coordinates or existing["coordinates"]
        if location_type and location_type not in existing["location_types"]:
            existing["location_types"].append(location_type)
        if platform and platform not in existing["platforms"]:
            existing["platforms"].append(platform)
    stops = list(by_id.values())
    for stop in stops:
        stop["platforms"] = stop["platforms"][:30]
        stop["platform_count"] = len(stop["platforms"])
    stops.sort(
        key=lambda stop: (
            stop["distance_metres"] is None,
            stop["distance_metres"] or 0,
            stop["name"],
        )
    )
    return stops


def _transport_mode(event: Mapping[str, Any]) -> str | None:
    transport = event.get("transportation")
    if not isinstance(transport, Mapping):
        return None
    product = transport.get("product")
    if not isinstance(product, Mapping) or product.get("class") is None:
        return None
    product_class = _integer(product.get("class"), default=-1)
    return next(
        (mode for mode, code in _MOT_CODES.items() if code == product_class), None
    )


def _is_requested_departure(event: Mapping[str, Any], modes: Sequence[str]) -> bool:
    return _transport_mode(event) in modes


def _departure_params(
    stop_id: str, query_time: datetime, modes: Sequence[str]
) -> list[tuple[str, str]]:
    params = [
        ("outputFormat", "rapidJSON"),
        ("coordOutputFormat", "EPSG:4326"),
        ("mode", "direct"),
        ("type_dm", "stop"),
        ("name_dm", stop_id),
        ("itdDate", query_time.strftime("%Y%m%d")),
        ("itdTime", query_time.strftime("%H%M")),
        ("departureMonitorMacro", "true"),
        ("TfNSWDM", "true"),
        ("excludedMeans", "checkbox"),
    ]
    included = {_MOT_CODES[mode] for mode in modes}
    for mode_code in _EXCLUDABLE_MOT_CODES:
        if mode_code not in included:
            params.append((f"exclMOT_{mode_code}", "1"))
    return params


def _normalise_departure(event: Mapping[str, Any]) -> DepartureCandidate | None:
    transport = event.get("transportation")
    transport = transport if isinstance(transport, Mapping) else {}
    location = event.get("location")
    location = location if isinstance(location, Mapping) else {}
    properties = event.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    transport_properties = transport.get("properties")
    transport_properties = (
        transport_properties if isinstance(transport_properties, Mapping) else {}
    )

    planned = _first_string(event, "departureTimePlanned", "plannedDepartureTime")
    estimated = _first_string(event, "departureTimeEstimated", "estimatedDepartureTime")
    cancelled = _optional_flag(
        event.get("isCancelled"),
        properties.get("isCancelled"),
        transport_properties.get("isCancelled"),
    )
    destination = transport.get("destination")
    operator = transport.get("operator")
    product = transport.get("product")
    raw_infos = event.get("infos")
    infos = raw_infos if isinstance(raw_infos, list) else []
    route = Route(
        id=_string(transport.get("id"), 128),
        number=_string(transport.get("number"), 80),
        name=_string(transport.get("name"), 300),
        icon_id=_integer(transport.get("iconId"), default=None),
        product_class=(
            _integer(product.get("class"), default=None)
            if isinstance(product, Mapping)
            else None
        ),
    )
    return DepartureCandidate(
        mode=_transport_mode(event),
        planned_time=_source_timestamp(planned),
        estimated_time=_source_timestamp(estimated),
        cancelled=cancelled,
        platform=_string(location.get("disassembledName") or location.get("name"), 200),
        route=route,
        destination=_string(destination.get("name"), 300)
        if isinstance(destination, Mapping)
        else None,
        operator=_string(operator.get("name"), 200)
        if isinstance(operator, Mapping)
        else None,
        trip_code=_string(transport_properties.get("tripCode"), 100),
        service_id=_string(properties.get("RealtimeTripId"), 160),
        alert_ids=tuple(
            alert_id
            for info in infos[:20]
            if isinstance(info, Mapping)
            for alert_id in [_string(info.get("id"), 128)]
            if alert_id
        ),
    )


def _normalise_journey(item: Mapping[str, Any]) -> JourneyCandidate | None:
    raw_legs = item.get("legs")
    legs = [
        _normalise_trip_leg(leg)
        for leg in (raw_legs if isinstance(raw_legs, list) else [])[:12]
        if isinstance(leg, Mapping)
    ]
    if not legs:
        return None
    return JourneyCandidate(
        legs=tuple(TripLeg.model_validate(leg) for leg in legs),
        declared_interchanges=_integer(item.get("interchanges"), default=None),
        rating=_integer(item.get("rating"), default=None),
    )


def _normalise_trip_leg(item: Mapping[str, Any]) -> dict[str, Any]:
    origin = item.get("origin")
    destination = item.get("destination")
    transport = item.get("transportation")
    transport = transport if isinstance(transport, Mapping) else {}
    product = transport.get("product")
    product = product if isinstance(product, Mapping) else {}
    operator = transport.get("operator")
    operator = operator if isinstance(operator, Mapping) else {}
    service_destination = transport.get("destination")
    service_destination = (
        service_destination if isinstance(service_destination, Mapping) else {}
    )
    properties = item.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    product_class = _integer(product.get("class"), default=None)
    mode = (
        "train"
        if product_class == 1
        else "metro"
        if product_class == 2
        else "light_rail"
        if product_class == 4
        else "bus"
        if product_class == 5
        else "ferry"
        if product_class == 9
        else "walk"
        if product_class in {99, 100} or not transport
        else f"mode_{product_class}"
        if product_class is not None
        else "unknown"
    )
    raw_sequence = item.get("stopSequence")
    sequence = raw_sequence if isinstance(raw_sequence, list) else []
    stops = [
        _normalise_trip_stop(stop)
        for stop in sequence[:30]
        if isinstance(stop, Mapping)
    ]
    raw_infos = item.get("infos")
    infos = raw_infos if isinstance(raw_infos, list) else []
    raw_hints = item.get("hints")
    hints = raw_hints if isinstance(raw_hints, list) else []
    cancelled = _optional_flag(
        item.get("isCancelled"),
        properties.get("isCancelled"),
        transport.get("isCancelled"),
    )
    duration_seconds = _nonnegative_integer(item.get("duration"))
    return {
        "mode": mode,
        "duration_seconds": duration_seconds,
        "duration_minutes": (
            round(duration_seconds / 60) if duration_seconds is not None else None
        ),
        "distance_metres": _nonnegative_integer(item.get("distance")),
        "is_realtime_controlled": _optional_flag(item.get("isRealtimeControlled")),
        "realtime_status": _string(item.get("realtimeStatus"), 40),
        "cancelled": cancelled,
        "origin": _normalise_trip_stop(origin if isinstance(origin, Mapping) else {}),
        "destination": _normalise_trip_stop(
            destination if isinstance(destination, Mapping) else {}
        ),
        "route": {
            "id": _string(transport.get("id"), 128),
            "number": _string(transport.get("number"), 120),
            "name": _string(transport.get("name"), 300),
            "description": _string(transport.get("description"), 500),
            "product_class": product_class,
        },
        "operator": _string(operator.get("name"), 200),
        "service_destination": _string(service_destination.get("name"), 300),
        "stop_count": len(stops),
        "stops": stops,
        "alert_ids": [
            alert_id
            for info in infos[:30]
            if isinstance(info, Mapping)
            for alert_id in [_string(info.get("id"), 128)]
            if alert_id
        ],
        "hints": [
            text
            for hint in hints[:10]
            if isinstance(hint, Mapping)
            for text in [html_to_plaintext(hint.get("infoText"), max_chars=300)]
            if text
        ],
    }


def _normalise_trip_stop(item: Mapping[str, Any]) -> dict[str, Any]:
    properties = item.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    parent = item.get("parent")
    parent = parent if isinstance(parent, Mapping) else {}
    coord = item.get("coord")
    coordinates = None
    if (
        isinstance(coord, list)
        and len(coord) >= 2
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in coord[:2]
        )
    ):
        coordinates = {"latitude": coord[0], "longitude": coord[1]}
    wheelchair = properties.get("WheelchairAccess")
    return {
        "id": _string(item.get("id"), 128),
        "name": _string(item.get("name"), 300),
        "short_name": _string(item.get("disassembledName"), 200),
        "parent_id": _string(parent.get("id"), 128),
        "platform": _string(
            properties.get("platformName")
            or properties.get("plannedPlatformName")
            or properties.get("stoppingPointPlanned"),
            120,
        ),
        "departure_time_planned": _normalise_timestamp(
            item.get("departureTimePlanned")
        ),
        "departure_time_estimated": _normalise_timestamp(
            item.get("departureTimeEstimated")
        ),
        "arrival_time_planned": _normalise_timestamp(item.get("arrivalTimePlanned")),
        "arrival_time_estimated": _normalise_timestamp(
            item.get("arrivalTimeEstimated")
        ),
        "wheelchair_accessible": (
            _truthy(wheelchair) if wheelchair is not None else None
        ),
        "coordinates": coordinates,
    }


def _normalise_alert(item: Mapping[str, Any]) -> dict[str, Any]:
    affected = item.get("affected")
    affected = affected if isinstance(affected, Mapping) else {}
    timestamps = item.get("timestamps")
    timestamps = timestamps if isinstance(timestamps, Mapping) else {}
    properties = item.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    source = properties.get("source")
    url = _safe_url(item.get("url"))
    return {
        "id": _string(item.get("id"), 128),
        "version": _integer(item.get("version"), default=None),
        "priority": _string(item.get("priority"), 30) or "unknown",
        "type": _string(item.get("type"), 50),
        "title": html_to_plaintext(item.get("subtitle"), max_chars=500),
        "content": html_to_plaintext(item.get("content")),
        "sms_summary": html_to_plaintext(properties.get("smsText"), max_chars=500),
        "affected_lines": _normalise_affected(affected.get("lines")),
        "affected_stops": _normalise_affected(affected.get("stops")),
        "created_at": _normalise_timestamp(timestamps.get("creation")),
        "last_modified": _normalise_timestamp(timestamps.get("lastModification")),
        "validity": _normalise_ranges(timestamps.get("validity")),
        "availability": _normalise_ranges(timestamps.get("availability")),
        "provider": _string(properties.get("providerCode"), 100),
        "source_name": _string(source.get("name"), 200)
        if isinstance(source, Mapping)
        else None,
        "url": url,
        "url_text": html_to_plaintext(item.get("urlText"), max_chars=200),
    }


def _normalise_affected(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:20]:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "id": _string(item.get("id"), 128),
                "name": _string(item.get("name"), 300),
                "number": _string(item.get("number"), 80),
            }
        )
    return result


def _normalise_ranges(value: object) -> list[dict[str, str | None]]:
    ranges = (
        value
        if isinstance(value, list)
        else ([value] if isinstance(value, Mapping) else [])
    )
    return [
        {
            "from": _normalise_timestamp(item.get("from")),
            "to": _normalise_timestamp(item.get("to")),
        }
        for item in ranges[:10]
        if isinstance(item, Mapping)
    ]


def _normalise_timestamp(value: object) -> str | None:
    text = _string(value, 64)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SYDNEY_TZ)
        return parsed.astimezone(SYDNEY_TZ).isoformat()
    except ValueError:
        return text


def _source_timestamp(value: str | None) -> datetime | None:
    normalised = _normalise_timestamp(value)
    if normalised is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise DomainError(
            "invalid_upstream_response",
            "TfNSW returned an invalid Trip Planner timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SYDNEY_TZ)
    return parsed.astimezone(SYDNEY_TZ)


def _normalise_system_messages(value: object) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        value = value.get("responseMessages")
    messages = value if isinstance(value, list) else []
    return [
        {
            "type": _string(item.get("type"), 40),
            "code": _integer(item.get("code"), default=None),
            "message": html_to_plaintext(
                item.get("error") or item.get("text"), max_chars=500
            ),
            "module": _string(item.get("module") or item.get("subType"), 80),
        }
        for item in messages[:10]
        if isinstance(item, Mapping)
    ]


def _first_string(item: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _string(item.get(key), 64)
        if value:
            return value
    return None


def _integer(value: object, *, default: int | None) -> int | None:
    if isinstance(value, bool):
        return default
    try:
        if isinstance(value, (str, int, float)):
            return int(value)
    except (TypeError, ValueError):
        pass
    return default


def _integer_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value[:20]:
        converted = _integer(item, default=None)
        if converted is not None:
            result.append(converted)
    return result


def _string(value: object, max_chars: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _truthy(value: object) -> bool:
    return value is True or (
        isinstance(value, str) and value.lower() in {"1", "true", "yes"}
    )


def _optional_flag(*values: object) -> bool | None:
    present = [value for value in values if value is not None]
    return any(_truthy(value) for value in present) if present else None


def _nonnegative_integer(value: object) -> int | None:
    converted = _integer(value, default=None)
    return converted if converted is not None and converted >= 0 else None


def _safe_url(value: object) -> str | None:
    url = _string(value, 500)
    if not url:
        return None
    parts = urlsplit(url)
    return url if parts.scheme in {"http", "https"} and bool(parts.netloc) else None
