"""Semantic port for static TfNSW stop-facility information."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

AccessibilityClassification = Literal[
    "independent_access", "assisted_access", "not_accessible", "unknown"
]


@dataclass(frozen=True, slots=True)
class FacilityCoordinates:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class FacilityRecord:
    name: str
    efa_id: str
    tsn: str
    address: str | None
    phone: str | None
    coordinates: FacilityCoordinates | None
    transport_modes: tuple[str, ...]
    accessibility_classification: AccessibilityClassification
    accessibility_features: tuple[str, ...]
    facilities: tuple[str, ...]
    morning_staffed_hours: str | None
    afternoon_staffed_hours: str | None
    short_platform: bool | None


@dataclass(frozen=True, slots=True)
class LiftRecord:
    functional_location_code: str | None
    description: str | None
    inventory_record_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class FacilitySnapshot:
    matched_by: Literal["efa_id", "tsn", "none"]
    facility: FacilityRecord | None
    lifts: tuple[LiftRecord, ...]
    source_updated_at: datetime | None
    cache_stale: bool


class FacilitiesPort(Protocol):
    def get_facility(self, stop_id: str) -> FacilitySnapshot: ...
