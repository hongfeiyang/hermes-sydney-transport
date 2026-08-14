"""Semantic Complete GTFS route-timetable boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from ..models.static_inputs import RouteTimetableInput


@dataclass(frozen=True, slots=True)
class TimetableRouteRecord:
    id: str
    agency_id: str | None
    short_name: str | None
    long_name: str | None
    description: str | None
    route_type: int | None


@dataclass(frozen=True, slots=True)
class TimetableStopRecord:
    stop_id: str
    stop_name: str | None
    sequence: int
    arrival: datetime | None
    departure: datetime | None
    pickup_type: int | None
    drop_off_type: int | None


@dataclass(frozen=True, slots=True)
class TimetableTripRecord:
    trip_id: str
    headsign: str | None
    direction_id: Literal[0, 1] | None
    wheelchair_accessibility: Literal["accessible", "not_accessible", "unknown"]
    first_departure: datetime | None
    last_arrival: datetime | None
    stop_times: tuple[TimetableStopRecord, ...]
    stop_times_truncated: bool


@dataclass(frozen=True, slots=True)
class RouteTimetableSnapshot:
    route: TimetableRouteRecord | None
    service_date: date
    trips: tuple[TimetableTripRecord, ...]
    source_updated_at: datetime | None
    cache_stale: bool


class RouteTimetablePort(Protocol):
    def get_route_timetable(
        self, request: RouteTimetableInput, service_date: date
    ) -> RouteTimetableSnapshot: ...
