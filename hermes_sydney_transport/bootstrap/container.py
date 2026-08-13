"""Composition root mapping each catalog capability to exactly one use case."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pydantic import BaseModel

from ..adapters.system_clock import SystemClock
from ..adapters.tfnsw.alerts import TfnswAlertsAdapter
from ..adapters.tfnsw.binary_transport import UrllibBinaryTransport
from ..adapters.tfnsw.complete_gtfs import CompleteGtfsTimetableAdapter
from ..adapters.tfnsw.facilities import TfnswFacilitiesAdapter
from ..adapters.tfnsw.live_traffic import LiveTrafficTransport, TfnswLiveTrafficAdapter
from ..adapters.tfnsw.realtime_decoder import ProtobufRealtimeDecoder
from ..adapters.tfnsw.realtime_gateway import TfnswRealtimeRepository
from ..adapters.tfnsw.static_gtfs import StaticGtfsRepository
from ..adapters.tfnsw.static_resources import UrllibStaticResourceTransport
from ..adapters.tfnsw.traffic_counts import (
    TfnswTrafficCountsAdapter,
    TrafficVolumeTransport,
)
from ..adapters.tfnsw.trip_planner import TfnswClient
from ..application.accessibility import GetStopAccessibility
from ..application.alerts import GetRouteDisruptions
from ..application.capabilities import Capability
from ..application.live_traffic import GetLiveTrafficHazards
from ..application.realtime import GetServiceStatus, GetVehiclePosition
from ..application.realtime.mode_policy import (
    BUS_POLICY,
    FERRY_POLICY,
    LIGHT_RAIL_POLICY,
    METRO_POLICY,
    TRAIN_POLICY,
)
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
from ..ports.realtime import TransportMode
from .settings import Settings

Operation = Callable[[BaseModel], BaseModel]


class Container:
    """Build infrastructure once per invocation and expose closed operations."""

    def __init__(self, settings: Settings) -> None:
        clock = SystemClock()
        trip_planner = TfnswClient(settings.tfnsw_api_key)
        static_transport = UrllibStaticResourceTransport(settings.tfnsw_api_key)
        facilities = TfnswFacilitiesAdapter(
            static_transport,
            database_path=settings.cache_directory / "facilities.sqlite3",
        )
        complete_timetable = CompleteGtfsTimetableAdapter(
            static_transport,
            database_path=settings.cache_directory / "complete-gtfs.sqlite3",
        )
        traffic = TfnswTrafficCountsAdapter(
            TrafficVolumeTransport(settings.tfnsw_api_key)
        )
        live_traffic = TfnswLiveTrafficAdapter(
            LiveTrafficTransport(settings.tfnsw_api_key)
        )
        decoder = ProtobufRealtimeDecoder()
        train_transport = UrllibBinaryTransport(settings.tfnsw_api_key, mode="train")
        bus_transport = UrllibBinaryTransport(settings.tfnsw_api_key, mode="bus")
        metro_transport = UrllibBinaryTransport(settings.tfnsw_api_key, mode="metro")
        light_rail_transport = UrllibBinaryTransport(
            settings.tfnsw_api_key, mode="light_rail"
        )
        ferry_transport = UrllibBinaryTransport(settings.tfnsw_api_key, mode="ferry")
        alerts = TfnswAlertsAdapter(
            {
                TransportMode.TRAIN: train_transport,
                TransportMode.BUS: bus_transport,
                TransportMode.METRO: metro_transport,
                TransportMode.LIGHT_RAIL: light_rail_transport,
                TransportMode.FERRY: ferry_transport,
            },
            decoder,
        )
        train_realtime = TfnswRealtimeRepository(train_transport, decoder)
        bus_realtime = TfnswRealtimeRepository(bus_transport, decoder)
        metro_realtime = TfnswRealtimeRepository(metro_transport, decoder)
        light_rail_realtime = TfnswRealtimeRepository(light_rail_transport, decoder)
        ferry_realtime = TfnswRealtimeRepository(ferry_transport, decoder)
        train_static = StaticGtfsRepository(
            train_transport,
            database_path=settings.cache_directory / "train-static.sqlite3",
        )
        bus_static = StaticGtfsRepository(
            bus_transport,
            database_path=settings.cache_directory / "bus-static.sqlite3",
        )
        metro_static = StaticGtfsRepository(
            metro_transport,
            database_path=settings.cache_directory / "metro-static.sqlite3",
        )
        light_rail_static = StaticGtfsRepository(
            light_rail_transport,
            database_path=settings.cache_directory / "light-rail-static.sqlite3",
        )
        ferry_static = StaticGtfsRepository(
            ferry_transport,
            database_path=settings.cache_directory / "ferry-static.sqlite3",
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
        metro_status = GetServiceStatus(
            metro_realtime, trip_planner, metro_static, clock, METRO_POLICY
        )
        metro_position = GetVehiclePosition(
            metro_realtime, trip_planner, metro_static, clock, METRO_POLICY
        )
        light_rail_status = GetServiceStatus(
            light_rail_realtime,
            trip_planner,
            light_rail_static,
            clock,
            LIGHT_RAIL_POLICY,
        )
        light_rail_position = GetVehiclePosition(
            light_rail_realtime,
            trip_planner,
            light_rail_static,
            clock,
            LIGHT_RAIL_POLICY,
        )
        ferry_status = GetServiceStatus(
            ferry_realtime, trip_planner, ferry_static, clock, FERRY_POLICY
        )
        ferry_position = GetVehiclePosition(
            ferry_realtime, trip_planner, ferry_static, clock, FERRY_POLICY
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
            Capability.TRAIN_SERVICE_STATUS: cast(Operation, train_status.execute),
            Capability.TRAIN_VEHICLE_POSITION: cast(Operation, train_position.execute),
            Capability.BUS_SERVICE_STATUS: cast(Operation, bus_status.execute),
            Capability.BUS_VEHICLE_POSITION: cast(Operation, bus_position.execute),
            Capability.METRO_SERVICE_STATUS: cast(Operation, metro_status.execute),
            Capability.METRO_VEHICLE_POSITION: cast(Operation, metro_position.execute),
            Capability.LIGHT_RAIL_SERVICE_STATUS: cast(
                Operation, light_rail_status.execute
            ),
            Capability.LIGHT_RAIL_VEHICLE_POSITION: cast(
                Operation, light_rail_position.execute
            ),
            Capability.FERRY_SERVICE_STATUS: cast(Operation, ferry_status.execute),
            Capability.FERRY_VEHICLE_POSITION: cast(Operation, ferry_position.execute),
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
        }
        if set(self._operations) != set(Capability):
            raise RuntimeError("container and capability vocabulary are out of sync")
        self._closers = (
            train_static.close,
            bus_static.close,
            metro_static.close,
            light_rail_static.close,
            ferry_static.close,
            facilities.close,
            complete_timetable.close,
        )

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
