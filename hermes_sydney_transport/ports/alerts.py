"""Semantic contract for GTFS-Realtime alerts consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .realtime import TransportMode


@dataclass(frozen=True, slots=True)
class AlertTimeRange:
    start: datetime | None
    end: datetime | None


@dataclass(frozen=True, slots=True)
class AlertSelector:
    agency_id: str | None
    route_id: str | None
    route_type: int | None
    stop_id: str | None
    trip_id: str | None
    direction_id: int | None


@dataclass(frozen=True, slots=True)
class AlertRecord:
    id: str
    mode: TransportMode
    source_feed: str
    title: str
    description: str
    cause: str
    effect: str
    severity: str
    url: str | None
    active_periods: tuple[AlertTimeRange, ...]
    selectors: tuple[AlertSelector, ...]
    route_ids: tuple[str, ...]
    stop_ids: tuple[str, ...]
    trip_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlertQuery:
    modes: tuple[TransportMode, ...]
    stop_id: str | None
    route_id: str | None
    trip_id: str | None
    causes: tuple[str, ...]
    effects: tuple[str, ...]
    active_at: datetime | None


class AlertsPort(Protocol):
    """Typed boundary implemented by GTFS-Realtime alerts adapters."""

    def find_alerts(self, query: AlertQuery) -> tuple[AlertRecord, ...]: ...
