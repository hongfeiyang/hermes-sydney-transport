"""Composition root mapping each catalog capability to exactly one use case."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pydantic import BaseModel

from ..adapters.system_clock import SystemClock
from ..adapters.tfnsw.binary_transport import UrllibBinaryTransport
from ..adapters.tfnsw.realtime_decoder import ProtobufRealtimeDecoder
from ..adapters.tfnsw.realtime_gateway import TfnswRealtimeRepository
from ..adapters.tfnsw.static_gtfs import StaticGtfsRepository
from ..adapters.tfnsw.traffic_counts import (
    TfnswTrafficCountsAdapter,
    TrafficVolumeTransport,
)
from ..adapters.tfnsw.trip_planner import TfnswClient
from ..application.capabilities import Capability
from ..application.realtime import GetServiceStatus, GetVehiclePosition
from ..application.realtime.mode_policy import BUS_POLICY, TRAIN_POLICY
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
from .settings import Settings

Operation = Callable[[BaseModel], BaseModel]


class Container:
    """Build infrastructure once per invocation and expose closed operations."""

    def __init__(self, settings: Settings) -> None:
        clock = SystemClock()
        trip_planner = TfnswClient(settings.tfnsw_api_key)
        traffic = TfnswTrafficCountsAdapter(
            TrafficVolumeTransport(settings.tfnsw_api_key)
        )
        decoder = ProtobufRealtimeDecoder()
        train_transport = UrllibBinaryTransport(settings.tfnsw_api_key, mode="train")
        bus_transport = UrllibBinaryTransport(settings.tfnsw_api_key, mode="bus")
        train_realtime = TfnswRealtimeRepository(train_transport, decoder)
        bus_realtime = TfnswRealtimeRepository(bus_transport, decoder)
        train_static = StaticGtfsRepository(
            train_transport,
            database_path=settings.cache_directory / "train-static.sqlite3",
        )
        bus_static = StaticGtfsRepository(
            bus_transport,
            database_path=settings.cache_directory / "bus-static.sqlite3",
        )
        train_status = GetServiceStatus(
            train_realtime, trip_planner, train_static, clock, TRAIN_POLICY
        )
        train_position = GetVehiclePosition(
            train_realtime, trip_planner, train_static, clock, TRAIN_POLICY
        )
        bus_status = GetServiceStatus(
            bus_realtime, trip_planner, bus_static, clock, BUS_POLICY
        )
        bus_position = GetVehiclePosition(
            bus_realtime, trip_planner, bus_static, clock, BUS_POLICY
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
            Capability.TRAIN_SERVICE_STATUS: cast(Operation, train_status.execute),
            Capability.TRAIN_VEHICLE_POSITION: cast(Operation, train_position.execute),
            Capability.BUS_SERVICE_STATUS: cast(Operation, bus_status.execute),
            Capability.BUS_VEHICLE_POSITION: cast(Operation, bus_position.execute),
            Capability.TRAFFIC_STATIONS: cast(
                Operation, SearchTrafficStations(traffic, clock).execute
            ),
            Capability.TRAFFIC_SUMMARY: cast(
                Operation, GetTrafficSummary(traffic, clock).execute
            ),
            Capability.TRAFFIC_HOURLY: cast(
                Operation, GetHourlyTraffic(traffic, clock).execute
            ),
        }
        if set(self._operations) != set(Capability):
            raise RuntimeError("container and capability vocabulary are out of sync")
        self._closers = (train_static.close, bus_static.close)

    def execute(self, capability: Capability, request: BaseModel) -> BaseModel:
        try:
            operation = self._operations[capability]
        except KeyError as exc:
            raise DomainError(
                "internal_error", f"No use case is bound for {capability.value}."
            ) from exc
        return operation(request)

    def close(self) -> None:
        for close in self._closers:
            close()
