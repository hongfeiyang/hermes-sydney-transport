"""Typed application contract for TfNSW Trip Planner source data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..models.inputs import (
    AlertsInput,
    DeparturesInput,
    NearbyStopsInput,
    StationSearchInput,
    TripPlanInput,
)
from ..models.outputs import (
    Alert,
    NearbyStop,
    Route,
    Station,
    SystemMessage,
    TripLeg,
)


@dataclass(frozen=True, slots=True)
class DepartureCandidate:
    mode: str | None
    planned_time: datetime | None
    estimated_time: datetime | None
    cancelled: bool | None
    platform: str | None
    route: Route
    destination: str | None
    operator: str | None
    trip_code: str | None
    service_id: str | None
    alert_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DepartureBoard:
    station: Station | None
    candidates: tuple[DepartureCandidate, ...]


@dataclass(frozen=True, slots=True)
class JourneyCandidate:
    legs: tuple[TripLeg, ...]
    declared_interchanges: int | None
    rating: int | None


@dataclass(frozen=True, slots=True)
class JourneyBoard:
    candidates: tuple[JourneyCandidate, ...]
    system_messages: tuple[SystemMessage, ...]


@dataclass(frozen=True, slots=True)
class ServiceResolution:
    service_id: str
    planned_time: datetime | None


class TripPlannerPort(Protocol):
    """Semantic source operations implemented by the TfNSW adapter."""

    def station_candidates(
        self, request: StationSearchInput
    ) -> tuple[Station, ...]: ...

    def nearby_candidates(
        self, request: NearbyStopsInput
    ) -> tuple[NearbyStop, ...]: ...

    def departure_candidates(self, request: DeparturesInput) -> DepartureBoard: ...

    def journey_candidates(self, request: TripPlanInput) -> JourneyBoard: ...

    def alert_candidates(self, request: AlertsInput) -> tuple[Alert, ...]: ...

    def resolve_service_id(
        self,
        trip_code: str,
        stop_id: str,
        at: datetime,
        mode: str = "train",
    ) -> ServiceResolution: ...
