"""Semantic contract for Live Traffic hazard data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HazardQuery:
    latitude: float | None
    longitude: float | None
    radius_metres: int | None
    suburb: str | None
    hazard_types: tuple[str, ...]
    limit: int


@dataclass(frozen=True, slots=True)
class HazardRoadRecord:
    main_street: str | None
    cross_street: str | None
    location_qualifier: str | None
    second_location: str | None
    suburb: str | None
    region: str | None
    traffic_volume: str | None
    delay: str | None
    queue_length_km: float | None


@dataclass(frozen=True, slots=True)
class HazardLinkRecord:
    text: str
    url: str


@dataclass(frozen=True, slots=True)
class HazardRecord:
    id: str
    hazard_type: str
    incident_kind: str
    display_name: str
    headline: str | None
    main_category: str | None
    advice: tuple[str, ...]
    other_advice: str
    public_transport: str
    impacting_network: bool
    ended: bool
    is_major: bool
    expected_delay_minutes: int | None
    speed_limit_kmh: int | None
    updated_at: datetime | None
    start_at: datetime | None
    end_at: datetime | None
    latitude: float
    longitude: float
    distance_metres: int | None
    roads: tuple[HazardRoadRecord, ...]
    links: tuple[HazardLinkRecord, ...]


class LiveTrafficHazardsPort(Protocol):
    """Typed boundary implemented by the Live Traffic hazards adapter."""

    def find_hazards(self, query: HazardQuery) -> tuple[HazardRecord, ...]: ...
