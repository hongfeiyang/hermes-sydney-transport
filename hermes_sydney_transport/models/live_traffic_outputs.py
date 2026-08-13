"""Normalized output contracts for Live Traffic hazards."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .outputs import Coordinates, PluginOutput, ResultMetadata, Timestamp


class LiveTrafficHazardsQuery(PluginOutput):
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    suburb: str | None
    radius_metres: int | None = Field(default=None, ge=100, le=50000)
    hazard_types: list[str]


class LiveTrafficRoad(PluginOutput):
    main_street: str | None
    cross_street: str | None
    location_qualifier: str | None
    second_location: str | None
    suburb: str | None
    region: str | None
    traffic_volume: str | None
    delay: str | None
    queue_length_km: float | None = Field(default=None, ge=0)


class LiveTrafficLink(PluginOutput):
    text: str
    url: str


class LiveTrafficHazard(PluginOutput):
    id: str
    hazard_type: Literal[
        "incident",
        "fire",
        "flood",
        "alpine",
        "major_event",
        "roadwork",
        "regional_lga_incident",
    ]
    incident_kind: str
    display_name: str
    headline: str | None
    main_category: str | None
    advice: list[str]
    other_advice: str
    public_transport: str
    impacting_network: bool
    ended: bool
    is_major: bool
    expected_delay_minutes: int | None
    speed_limit_kmh: int | None
    updated_at: Timestamp | None
    start_at: Timestamp | None
    end_at: Timestamp | None
    distance_metres: int | None = Field(default=None, ge=0)
    coordinates: Coordinates
    roads: list[LiveTrafficRoad]
    links: list[LiveTrafficLink]


class LiveTrafficHazardsResult(ResultMetadata):
    query: LiveTrafficHazardsQuery
    hazards: list[LiveTrafficHazard]
    count: int = Field(ge=0)
    quality_note: str
    remote_content_is_untrusted: Literal[True]

    @model_validator(mode="after")
    def count_matches(self) -> LiveTrafficHazardsResult:
        if self.count != len(self.hazards):
            raise ValueError("count must equal the number of hazards")
        return self
