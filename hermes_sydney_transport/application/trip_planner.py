"""Trip Planner business policy and canonical result construction."""

from __future__ import annotations

from datetime import UTC, datetime

from ..models.inputs import (
    AlertsInput,
    DeparturesInput,
    NearbyStopsInput,
    StationSearchInput,
    TripPlanInput,
)
from ..models.metadata import ATTRIBUTION
from ..models.outputs import (
    AlertsResult,
    DeparturesResult,
    NearbyQuery,
    NearbyStopsResult,
    StationSearchResult,
    TripPlanResult,
)
from ..ports.clock import Clock
from ..ports.trip_planner import (
    TripPlannerPort,
)
from .trip_planner_policy import (
    alert_priority_rank,
    deduplicate_alerts,
    departure_from_candidate,
    journey_from_candidate,
)

_SOURCE = "TfNSW Trip Planner API"
_MODE_CODES = {"train": 1, "metro": 2, "light_rail": 4, "bus": 5, "ferry": 9}


class SearchStops:
    def __init__(self, port: TripPlannerPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: StationSearchInput) -> StationSearchResult:
        allowed = {_MODE_CODES[mode] for mode in request.modes}
        candidates = [
            station
            for station in self._port.station_candidates(request)
            if allowed.intersection(station.modes)
        ]
        candidates.sort(
            key=lambda station: (
                not station.is_best,
                -station.match_quality,
                station.name,
            )
        )
        stations = candidates[: request.limit]
        return StationSearchResult(
            fetched_at=self._clock.now(),
            source=_SOURCE,
            attribution=ATTRIBUTION,
            query=request.query,
            requested_modes=request.modes,
            stations=stations,
            count=len(stations),
        )


class FindNearbyStops:
    def __init__(self, port: TripPlannerPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: NearbyStopsInput) -> NearbyStopsResult:
        stops = list(self._port.nearby_candidates(request)[: request.limit])
        return NearbyStopsResult(
            fetched_at=self._clock.now(),
            source=_SOURCE,
            attribution=ATTRIBUTION,
            query=NearbyQuery(
                latitude=request.latitude,
                longitude=request.longitude,
                radius_metres=request.radius_metres,
            ),
            stops=stops,
            count=len(stops),
            mode_note=(
                "The TfNSW coordinate endpoint does not identify transport mode "
                "reliably. Results are public-transport stops and are not all "
                "guaranteed to be train stations."
            ),
        )


class GetDepartures:
    def __init__(self, port: TripPlannerPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: DeparturesInput) -> DeparturesResult:
        now = self._clock.now()
        effective = request.model_copy(update={"at": request.at or now})
        if effective.at is None:
            raise RuntimeError("effective departure time was not set")
        board = self._port.departure_candidates(effective)
        departures = [
            departure_from_candidate(candidate)
            for candidate in board.candidates
            if candidate.mode in request.modes
        ]
        departures.sort(
            key=lambda item: (
                item.estimated_time
                or item.planned_time
                or datetime.max.replace(tzinfo=UTC)
            )
        )
        departures = departures[: request.limit]
        return DeparturesResult(
            fetched_at=now,
            source=_SOURCE,
            attribution=ATTRIBUTION,
            stop_id=request.stop_id,
            requested_modes=request.modes,
            station=board.station,
            requested_at=effective.at,
            departures=departures,
            count=len(departures),
            realtime_note=(
                "A status of unknown means TfNSW did not supply enough realtime "
                "information; it does not mean the service is on time."
            ),
        )


class PlanJourney:
    def __init__(self, port: TripPlannerPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: TripPlanInput) -> TripPlanResult:
        now = self._clock.now()
        effective = request.model_copy(update={"at": request.at or now})
        if effective.at is None:
            raise RuntimeError("effective journey time was not set")
        board = self._port.journey_candidates(effective)
        journeys = [
            journey_from_candidate(candidate)
            for candidate in board.candidates[: request.limit]
        ]
        return TripPlanResult(
            fetched_at=now,
            source=_SOURCE,
            attribution=ATTRIBUTION,
            origin_stop_id=request.origin_stop_id,
            destination_stop_id=request.destination_stop_id,
            requested_at=effective.at,
            time_mode=request.time_mode,
            wheelchair_requested=request.wheelchair,
            requested_modes=request.modes,
            journeys=journeys,
            count=len(journeys),
            system_messages=list(board.system_messages),
            mode_note=(
                "TfNSW was restricted to the requested public-transport modes; walking "
                "interchanges can still appear between public-transport legs."
            ),
        )


class GetAlerts:
    def __init__(self, port: TripPlannerPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: AlertsInput) -> AlertsResult:
        alerts = deduplicate_alerts(self._port.alert_candidates(request))
        alerts.sort(key=lambda item: item.id or "")
        alerts.sort(
            key=lambda item: item.last_modified or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        alerts.sort(key=lambda item: alert_priority_rank(item.priority), reverse=True)
        alerts = alerts[: request.limit]
        return AlertsResult.model_validate(
            {
                "fetched_at": self._clock.now(),
                "source": _SOURCE,
                "attribution": ATTRIBUTION,
                "scope": {"stop_id": request.stop_id}
                if request.stop_id
                else {"network": "tfnsw_" + "_".join(request.modes) + "_modes"},
                "requested_modes": request.modes,
                "alerts": alerts,
                "count": len(alerts),
                "remote_content_is_untrusted": True,
            }
        )
