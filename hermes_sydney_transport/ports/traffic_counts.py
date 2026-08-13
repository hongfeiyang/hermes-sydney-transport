"""Application-facing contract for NSW road traffic-count data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from ..models.traffic_outputs import (
    HourlyTrafficCount,
    TrafficStation,
    TrafficVolumeSummary,
)


@dataclass(frozen=True, slots=True)
class Page[RecordT]:
    """A bounded collection plus the upstream count, when supplied."""

    records: tuple[RecordT, ...]
    total_rows: int | None


@dataclass(frozen=True, slots=True)
class StationQuery:
    text: str | None
    station_id: str | None
    permanent_only: bool
    limit: int


@dataclass(frozen=True, slots=True)
class SummaryQuery:
    station_id: str
    year: int | None
    limit: int


@dataclass(frozen=True, slots=True)
class HourlyQuery:
    station_key: str
    dataset: Literal["permanent", "sample"]
    start_date: date
    end_date: date
    traffic_direction_seq: int | None
    classification_seq: int | None
    limit: int


class TrafficCountsPort(Protocol):
    """Typed boundary implemented by a TfNSW adapter."""

    def search_stations(self, query: StationQuery) -> Page[TrafficStation]: ...

    def summaries(self, query: SummaryQuery) -> Page[TrafficVolumeSummary]: ...

    def hourly(self, query: HourlyQuery) -> Page[HourlyTrafficCount]: ...
