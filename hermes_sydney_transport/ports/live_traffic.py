"""Semantic contract for Live Traffic hazard data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models.live_traffic_inputs import HazardType
from ..models.live_traffic_outputs import LiveTrafficHazard


@dataclass(frozen=True, slots=True)
class HazardQuery:
    latitude: float | None
    longitude: float | None
    radius_metres: int | None
    suburb: str | None
    hazard_types: tuple[HazardType, ...]
    limit: int


class LiveTrafficHazardsPort(Protocol):
    """Typed boundary implemented by the Live Traffic hazards adapter."""

    def find_hazards(self, query: HazardQuery) -> tuple[LiveTrafficHazard, ...]: ...
