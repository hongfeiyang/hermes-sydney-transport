"""Semantic repository for the TfNSW Trip Planner API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ....models.errors import DomainError
from ....models.inputs import (
    AlertsInput,
    DeparturesInput,
    NearbyStopsInput,
    StationSearchInput,
    TripPlanInput,
)
from ....models.outputs import Alert, NearbyStop, Station
from ....ports.trip_planner import (
    DepartureBoard,
    JourneyBoard,
    ServiceResolution,
)
from ..catalogs.trip_planner import (
    TRIP_PLANNER_ENDPOINTS,
    alerts_params,
    departure_params,
    departure_query,
    journey_params,
    nearby_params,
    station_params,
)
from ..codecs import JsonModelCodec
from ..codecs.rich_text import normalise_alerts, normalise_journeys, plain_text
from ..mappers.time import sydney_time_required
from ..mappers.trip_alerts import map_alert
from ..mappers.trip_departures import (
    map_departure,
    service_resolution,
    transport_mode,
    trip_code,
)
from ..mappers.trip_journeys import map_journey, map_system_messages
from ..mappers.trip_locations import map_nearby, map_station
from ..platform import HttpTransport, QueryParams
from ..wire.trip_planner import (
    AlertsPayloadWire,
    DeparturesPayloadWire,
    JourneyPayloadWire,
    StopFinderPayloadWire,
    TripPlannerPayloadWire,
)


class TfnswTripPlannerRepository:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport
        self._locations = JsonModelCodec(
            StopFinderPayloadWire, source="Trip Planner locations"
        )
        self._departures = JsonModelCodec(
            DeparturesPayloadWire, source="Trip Planner departures"
        )
        self._journeys = JsonModelCodec(
            JourneyPayloadWire, source="Trip Planner journeys"
        )
        self._alerts = JsonModelCodec(AlertsPayloadWire, source="Trip Planner alerts")

    def station_candidates(self, request: StationSearchInput) -> tuple[Station, ...]:
        payload = self._decode("stop_finder", station_params(request), self._locations)
        return tuple(
            station
            for item in payload.locations
            if (station := map_station(item)) is not None
        )

    def nearby_candidates(self, request: NearbyStopsInput) -> tuple[NearbyStop, ...]:
        payload = self._decode("nearby", nearby_params(request), self._locations)
        return map_nearby(payload.locations)

    def departure_candidates(self, request: DeparturesInput) -> DepartureBoard:
        payload = self._decode(
            "departures", departure_params(request), self._departures
        )
        station = next(
            (
                mapped
                for item in payload.locations[:1]
                if (mapped := map_station(item)) is not None
            ),
            None,
        )
        return DepartureBoard(
            station=station,
            candidates=tuple(map_departure(item) for item in payload.stop_events),
        )

    def resolve_service_id(
        self,
        trip_code_value: str,
        stop_id: str,
        at: datetime,
        mode: str = "train",
    ) -> ServiceResolution:
        reference = sydney_time_required(at)
        payload = self._decode(
            "departures",
            departure_query(stop_id, reference, (mode,)),
            self._departures,
        )
        candidates = {
            resolution.service_id: resolution
            for event in payload.stop_events
            if transport_mode(event) == mode and trip_code(event) == trip_code_value
            if (resolution := service_resolution(event)) is not None
        }
        if not candidates:
            raise DomainError(
                "service_not_found",
                "No current departure matched that trip_code at the supplied stop.",
            )
        if len(candidates) == 1:
            return next(iter(candidates.values()))
        ranked = sorted(
            (
                abs((candidate.planned_time - reference).total_seconds()),
                candidate,
            )
            for candidate in candidates.values()
            if candidate.planned_time is not None
        )
        if ranked and (len(ranked) == 1 or ranked[0][0] < ranked[1][0]):
            return ranked[0][1]
        raise DomainError(
            "ambiguous_service",
            "More than one departure matched that trip_code; pass an exact service_id.",
        )

    def journey_candidates(self, request: TripPlanInput) -> JourneyBoard:
        payload = normalise_journeys(
            self._decode("journey", journey_params(request), self._journeys)
        )
        candidates = tuple(
            mapped
            for item in payload.journeys
            if (mapped := map_journey(item)) is not None
        )
        return JourneyBoard(
            candidates=candidates,
            system_messages=map_system_messages(payload.system_messages),
        )

    def alert_candidates(self, request: AlertsInput) -> tuple[Alert, ...]:
        payload = normalise_alerts(
            self._decode("alerts", alerts_params(request), self._alerts)
        )
        return (
            tuple(map_alert(item) for item in payload.infos.current)
            if payload.infos
            else ()
        )

    def _decode[PayloadT: TripPlannerPayloadWire](
        self,
        endpoint_name: str,
        params: QueryParams,
        codec: JsonModelCodec[PayloadT],
    ) -> PayloadT:
        payload = self._transport.fetch(
            TRIP_PLANNER_ENDPOINTS[endpoint_name], params=params
        )
        if payload.body is None:
            raise DomainError(
                "invalid_upstream_response",
                "TfNSW Trip Planner response did not contain a body.",
            )
        decoded = codec(payload.body)
        _raise_api_error(decoded)
        return decoded


def _raise_api_error(payload: TripPlannerPayloadWire) -> None:
    if payload.error is None:
        return
    message = (
        payload.error.message if isinstance(payload.error, BaseModel) else payload.error
    )
    raise DomainError(
        "upstream_api_error",
        plain_text(message, max_chars=500) or "TfNSW returned an API error.",
    )
