"""Normalized output contracts for GTFS-Realtime route disruptions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .outputs import PluginOutput, ResultMetadata, Timestamp


class DisruptionQuery(PluginOutput):
    requested_modes: list[Literal["train", "bus", "metro", "light_rail", "ferry"]]
    stop_id: str | None
    route_id: str | None
    trip_id: str | None
    requested_at: Timestamp
    causes: list[str]
    effects: list[str]


class DisruptionTimeRange(PluginOutput):
    start: Timestamp | None
    end: Timestamp | None


class DisruptionSelector(PluginOutput):
    agency_id: str | None
    route_id: str | None
    route_type: int | None
    stop_id: str | None
    trip_id: str | None
    direction_id: int | None


class RouteDisruption(PluginOutput):
    id: str
    mode: Literal["train", "bus", "metro", "light_rail", "ferry"]
    source_feed: Literal[
        "sydneytrains",
        "nswtrains",
        "buses",
        "regionbuses",
        "metro",
        "lightrail",
        "ferries",
    ]
    title: str
    description: str
    cause: str
    effect: str
    severity: str
    url: str | None
    active_periods: list[DisruptionTimeRange]
    selectors: list[DisruptionSelector]
    route_ids: list[str]
    stop_ids: list[str]
    trip_ids: list[str]


class RouteDisruptionsResult(ResultMetadata):
    query: DisruptionQuery
    disruptions: list[RouteDisruption]
    count: int = Field(ge=0)
    remote_content_is_untrusted: Literal[True]

    @model_validator(mode="after")
    def count_matches(self) -> RouteDisruptionsResult:
        if self.count != len(self.disruptions):
            raise ValueError("count must equal the number of disruptions")
        return self
