"""Declarative Trip Planner endpoints and query construction."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from types import MappingProxyType

from ....models.inputs import (
    AlertsInput,
    DeparturesInput,
    NearbyStopsInput,
    StationSearchInput,
    TripPlanInput,
)
from ..platform import EndpointSpec, QueryParams, QueryScalar

MODE_CODES = {"train": 1, "metro": 2, "light_rail": 4, "bus": 5, "ferry": 9}
_EXCLUDABLE_MODE_CODES = (1, 2, 4, 5, 7, 9, 11)
_BASE = "https://api.transport.nsw.gov.au/v1/tp"
_JSON_TYPES = frozenset({"application/json"})

TRIP_PLANNER_ENDPOINTS = MappingProxyType(
    {
        name: EndpointSpec(
            id=f"trip_planner_{name}",
            url=f"{_BASE}/{path}",
            accept="application/json",
            content_types=_JSON_TYPES,
            max_bytes=5 * 1_024 * 1_024,
            timeout_seconds=10.0,
        )
        for name, path in {
            "stop_finder": "stop_finder",
            "nearby": "coord",
            "departures": "departure_mon",
            "journey": "trip",
            "alerts": "add_info",
        }.items()
    }
)


def station_params(request: StationSearchInput) -> QueryParams:
    return [
        ("outputFormat", "rapidJSON"),
        ("coordOutputFormat", "EPSG:4326"),
        ("type_sf", "any"),
        ("name_sf", request.query),
        ("TfNSWSF", "true"),
    ]


def nearby_params(request: NearbyStopsInput) -> QueryParams:
    return [
        ("outputFormat", "rapidJSON"),
        ("coord", f"{request.longitude:.6f}:{request.latitude:.6f}:EPSG:4326"),
        ("coordOutputFormat", "EPSG:4326"),
        ("inclFilter", "1"),
        ("type_1", "BUS_POINT"),
        ("radius_1", str(request.radius_metres)),
        ("PoisOnMapMacro", "true"),
    ]


def departure_params(request: DeparturesInput) -> QueryParams:
    if request.at is None:
        raise ValueError("application must supply an effective departure time")
    return departure_query(request.stop_id, request.at, request.modes)


def departure_query(stop_id: str, at: datetime, modes: Collection[str]) -> QueryParams:
    params: list[tuple[str, QueryScalar]] = [
        ("outputFormat", "rapidJSON"),
        ("coordOutputFormat", "EPSG:4326"),
        ("mode", "direct"),
        ("type_dm", "stop"),
        ("name_dm", stop_id),
        ("itdDate", at.strftime("%Y%m%d")),
        ("itdTime", at.strftime("%H%M")),
        ("departureMonitorMacro", "true"),
        ("TfNSWDM", "true"),
        ("excludedMeans", "checkbox"),
    ]
    return [*params, *_excluded_modes(modes)]


def journey_params(request: TripPlanInput) -> QueryParams:
    if request.at is None:
        raise ValueError("application must supply an effective journey time")
    params: list[tuple[str, QueryScalar]] = [
        ("outputFormat", "rapidJSON"),
        ("coordOutputFormat", "EPSG:4326"),
        ("depArrMacro", "dep" if request.time_mode == "depart" else "arr"),
        ("itdDate", request.at.strftime("%Y%m%d")),
        ("itdTime", request.at.strftime("%H%M")),
        ("type_origin", "any"),
        ("name_origin", request.origin_stop_id),
        ("type_destination", "any"),
        ("name_destination", request.destination_stop_id),
        ("calcNumberOfTrips", str(request.limit)),
        ("excludedMeans", "checkbox"),
        *_excluded_modes(request.modes),
        *_optional_pair("wheelchair", "on", request.wheelchair),
        ("TfNSWTR", "true"),
    ]
    return params


def alerts_params(request: AlertsInput) -> QueryParams:
    return [
        ("outputFormat", "rapidJSON"),
        ("filterPublicationStatus", "current"),
        *(("filterMOTType", str(MODE_CODES[mode])) for mode in request.modes),
        *_optional_pair(
            "itdLPxx_selStop", request.stop_id, request.stop_id is not None
        ),
    ]


def _excluded_modes(modes: Collection[str]) -> list[tuple[str, str]]:
    included = {MODE_CODES[mode] for mode in modes}
    return [
        (f"exclMOT_{code}", "1")
        for code in _EXCLUDABLE_MODE_CODES
        if code not in included
    ]


def _optional_pair(
    name: str, value: str | None, included: bool
) -> tuple[tuple[str, str], ...]:
    return ((name, value),) if included and value is not None else ()
