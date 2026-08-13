"""Immutable semantic contracts for realtime and static GTFS repositories."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from enum import StrEnum
from typing import Protocol


class TransportMode(StrEnum):
    TRAIN = "train"
    BUS = "bus"


class TripRelationship(StrEnum):
    SCHEDULED = "scheduled"
    ADDED = "added"
    UNSCHEDULED = "unscheduled"
    CANCELLED = "cancelled"
    REPLACEMENT = "replacement"
    UNKNOWN = "unknown"


class StopRelationship(StrEnum):
    SCHEDULED = "scheduled"
    SKIPPED = "skipped"
    NO_DATA = "no_data"
    UNSCHEDULED = "unscheduled"


class VehicleStatus(StrEnum):
    INCOMING_AT = "incoming_at"
    STOPPED_AT = "stopped_at"
    IN_TRANSIT_TO = "in_transit_to"
    UNKNOWN = "unknown"


class TrackDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GtfsTime:
    """A GTFS service-day time, including valid values beyond 24:00:00."""

    seconds: int

    def at(self, service_date: date, timezone: tzinfo) -> datetime:
        return datetime.combine(
            service_date, datetime.min.time(), tzinfo=timezone
        ) + timedelta(seconds=self.seconds)

    def as_text(self) -> str:
        hours, remainder = divmod(self.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True, slots=True)
class StopEvent:
    time: datetime | None
    delay: timedelta | None
    uncertainty: timedelta | None


@dataclass(frozen=True, slots=True)
class CarriageRecord:
    name: str | None
    position_in_consist: int
    occupancy: str | None
    quiet_carriage: bool | None
    toilet: str | None
    luggage_rack: bool | None


@dataclass(frozen=True, slots=True)
class TripStopUpdate:
    sequence: int | None
    stop_id: str | None
    arrival: StopEvent | None
    departure: StopEvent | None
    relationship: StopRelationship
    departure_occupancy: str | None
    predictive_carriages: tuple[CarriageRecord, ...]


@dataclass(frozen=True, slots=True)
class TripUpdateRecord:
    service_id: str
    route_id: str | None
    start_date: date | None
    start_time: GtfsTime | None
    relationship: TripRelationship
    timestamp: datetime | None
    delay: timedelta | None
    vehicle_label: str | None
    stop_updates: tuple[TripStopUpdate, ...]


@dataclass(frozen=True, slots=True)
class UpdateBundle:
    bundle_id: str
    update_sequence: int
    cancelled_trip_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class TripUpdatesFeed:
    feed_timestamp: datetime
    updates: Mapping[str, TripUpdateRecord]
    update_bundles: tuple[UpdateBundle, ...]


@dataclass(frozen=True, slots=True)
class VehicleCoordinates:
    latitude: float
    longitude: float
    bearing: float | None
    speed: float | None
    track_direction: TrackDirection


@dataclass(frozen=True, slots=True)
class VehicleDescriptorRecord:
    model: str | None
    air_conditioned: bool | None
    wheelchair_accessible: bool | None


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    service_id: str
    route_id: str | None
    start_date: date | None
    start_time: GtfsTime | None
    relationship: TripRelationship
    label: str | None
    descriptor: VehicleDescriptorRecord | None
    position: VehicleCoordinates | None
    current_stop_sequence: int | None
    reported_stop_id: str | None
    current_status: VehicleStatus
    timestamp: datetime | None
    occupancy: str | None
    carriages: tuple[CarriageRecord, ...]


@dataclass(frozen=True, slots=True)
class VehiclePositionsFeed:
    feed_timestamp: datetime
    vehicles: Mapping[str, VehicleRecord]


@dataclass(frozen=True, slots=True)
class ServiceRealtimeSnapshot:
    feed_timestamp: datetime
    update: TripUpdateRecord | None
    cancellation_bundles: tuple[UpdateBundle, ...]


@dataclass(frozen=True, slots=True)
class VehicleRealtimeSnapshot:
    feed_timestamp: datetime
    vehicle: VehicleRecord | None


@dataclass(frozen=True, slots=True)
class StaticStopTime:
    stop_id: str
    sequence: int
    arrival: GtfsTime | None
    departure: GtfsTime | None
    stop_headsign: str | None


@dataclass(frozen=True, slots=True)
class StaticTrip:
    service_id: str
    service_calendar_id: str | None
    route_id: str | None
    agency_id: str | None
    route_type: int | None
    route_short_name: str | None
    route_long_name: str | None
    headsign: str | None
    direction_id: str | None
    vehicle_category_id: str | None
    stop_times: tuple[StaticStopTime, ...]
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class StaticStopReference:
    id: str
    name: str | None
    parent_station_id: str | None
    parent_station_name: str | None
    platform: str | None


class RealtimeRepository(Protocol):
    def service_snapshot(self, service_id: str) -> ServiceRealtimeSnapshot: ...

    def vehicle_snapshot(self, service_id: str) -> VehicleRealtimeSnapshot: ...


class StaticSchedulePort(Protocol):
    def get_trip(self, service_id: str) -> StaticTrip | None: ...

    def get_stop_references(
        self, stop_ids: Collection[str]
    ) -> Mapping[str, StaticStopReference]: ...
