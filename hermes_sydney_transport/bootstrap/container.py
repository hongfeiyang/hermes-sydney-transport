"""Composition root mapping each catalog capability to exactly one use case."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from ..adapters.system_clock import SystemClock
from ..adapters.tfnsw.codecs import ProtobufRealtimeDecoder
from ..adapters.tfnsw.platform import TfnswHttpClient
from ..adapters.tfnsw.repositories import (
    TfnswAlertsRepository,
    TfnswLiveTrafficRepository,
    TfnswRealtimeRepository,
    TfnswStaticResourceRepository,
    TfnswTrafficCountsRepository,
    TfnswTripPlannerRepository,
)
from ..adapters.tfnsw.repositories.complete_gtfs import CompleteGtfsTimetableAdapter
from ..adapters.tfnsw.repositories.facilities import TfnswFacilitiesAdapter
from ..adapters.tfnsw.repositories.static_gtfs import StaticGtfsRepository
from ..application.accessibility import GetStopAccessibility
from ..application.alerts import GetRouteDisruptions
from ..application.capabilities import Capability
from ..application.live_traffic import GetLiveTrafficHazards
from ..application.realtime import GetServiceStatus, GetVehiclePosition
from ..application.timetable import GetRouteTimetable
from ..application.traffic_counts import (
    GetHourlyTraffic,
    GetTrafficSummary,
    SearchTrafficStations,
)
from ..application.trip_planner import (
    FindNearbyStops,
    GetAlerts,
    GetDepartures,
    PlanJourney,
    SearchStops,
)
from ..models.errors import DomainError
from .modes import MODE_SPECS
from .settings import Settings

Operation = Callable[[BaseModel], BaseModel]


class Container:
    """Build infrastructure once per invocation and expose closed operations."""

    def __init__(self, settings: Settings) -> None:
        clock = SystemClock()
        tfnsw_http = TfnswHttpClient(settings.tfnsw_api_key)
        trip_planner = TfnswTripPlannerRepository(tfnsw_http)
        static_transport = TfnswStaticResourceRepository(tfnsw_http)
        facilities = TfnswFacilitiesAdapter(
            static_transport,
            database_path=settings.cache_directory / "facilities.sqlite3",
        )
        complete_timetable = CompleteGtfsTimetableAdapter(
            static_transport,
            database_path=settings.cache_directory / "complete-gtfs.sqlite3",
        )
        traffic = TfnswTrafficCountsRepository(tfnsw_http)
        live_traffic = TfnswLiveTrafficRepository(tfnsw_http)
        decoder = ProtobufRealtimeDecoder()
        alerts = TfnswAlertsRepository(
            tfnsw_http,
            decoder,
            endpoints={spec.mode: spec.feeds.alerts for spec in MODE_SPECS},
            sources={spec.mode: spec.alert_sources for spec in MODE_SPECS},
        )
        mode_operations, static_closers = _bind_realtime_modes(
            tfnsw_http,
            decoder,
            trip_planner,
            clock,
            settings.cache_directory,
        )
        self._operations: dict[Capability, Operation] = {
            Capability.SEARCH_STOPS: cast(
                Operation, SearchStops(trip_planner, clock).execute
            ),
            Capability.NEARBY_STOPS: cast(
                Operation, FindNearbyStops(trip_planner, clock).execute
            ),
            Capability.DEPARTURES: cast(
                Operation, GetDepartures(trip_planner, clock).execute
            ),
            Capability.PLAN_TRIP: cast(
                Operation, PlanJourney(trip_planner, clock).execute
            ),
            Capability.ALERTS: cast(Operation, GetAlerts(trip_planner, clock).execute),
            Capability.ROUTE_DISRUPTIONS: cast(
                Operation, GetRouteDisruptions(alerts, clock).execute
            ),
            Capability.STOP_ACCESSIBILITY: cast(
                Operation,
                GetStopAccessibility(facilities, alerts, clock).execute,
            ),
            Capability.ROUTE_TIMETABLE: cast(
                Operation, GetRouteTimetable(complete_timetable, clock).execute
            ),
            Capability.LIVE_TRAFFIC_HAZARDS: cast(
                Operation, GetLiveTrafficHazards(live_traffic, clock).execute
            ),
            Capability.TRAFFIC_STATIONS: cast(
                Operation, SearchTrafficStations(traffic, clock).execute
            ),
            Capability.TRAFFIC_SUMMARY: cast(
                Operation, GetTrafficSummary(traffic, clock).execute
            ),
            Capability.TRAFFIC_HOURLY: cast(
                Operation, GetHourlyTraffic(traffic, clock).execute
            ),
            **mode_operations,
        }
        if set(self._operations) != set(Capability):
            raise RuntimeError("container and capability vocabulary are out of sync")
        self._closers = (
            *static_closers,
            facilities.close,
            complete_timetable.close,
            tfnsw_http.close,
        )

    def execute(self, capability: Capability, request: BaseModel) -> BaseModel:
        operation = self._operations.get(capability)
        if operation is None:
            raise DomainError(
                "internal_error", f"No use case is bound for {capability.value}."
            )
        return operation(request)

    def close(self) -> None:
        for close in self._closers:
            close()


def _bind_realtime_modes(
    http: TfnswHttpClient,
    decoder: ProtobufRealtimeDecoder,
    trip_planner: TfnswTripPlannerRepository,
    clock: SystemClock,
    cache_directory: Path,
) -> tuple[dict[Capability, Operation], tuple[Callable[[], None], ...]]:
    operations: dict[Capability, Operation] = {}
    closers: list[Callable[[], None]] = []
    for spec in MODE_SPECS:
        realtime = TfnswRealtimeRepository(http, decoder, feeds=spec.feeds)
        static = StaticGtfsRepository(
            http,
            endpoints=spec.feeds.static_schedule,
            database_path=cache_directory / f"{spec.cache_slug}-static.sqlite3",
        )
        status = GetServiceStatus(realtime, trip_planner, static, clock, spec.policy)
        position = GetVehiclePosition(
            realtime, trip_planner, static, clock, spec.policy
        )
        operations[spec.service_status] = cast(Operation, status.execute)
        operations[spec.vehicle_position] = cast(Operation, position.execute)
        closers.append(static.close)
    return operations, tuple(closers)
