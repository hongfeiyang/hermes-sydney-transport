"""Pydantic contracts for Live Traffic hazard lookups."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt, model_validator

from .inputs import PluginInput, _collapse_whitespace

HazardType = Literal[
    "incident",
    "fire",
    "flood",
    "alpine",
    "major_event",
    "roadwork",
    "regional_lga_incident",
]


def _default_hazard_types() -> list[HazardType]:
    return [
        "incident",
        "fire",
        "flood",
        "alpine",
        "major_event",
        "roadwork",
    ]


class LiveTrafficHazardsInput(PluginInput):
    latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        allow_inf_nan=False,
        description="Latitude in WGS84/EPSG:4326.",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180,
        allow_inf_nan=False,
        description="Longitude in WGS84/EPSG:4326.",
    )
    suburb: str | None = Field(
        default=None,
        min_length=2,
        max_length=80,
        description="Exact suburb name to filter hazards by affected road suburb.",
    )
    radius_metres: StrictInt | None = Field(
        default=10000,
        ge=100,
        le=50000,
        description="Radius around the coordinate query. Ignored when suburb is used.",
    )
    hazard_types: list[HazardType] = Field(
        default_factory=_default_hazard_types,
        min_length=1,
        max_length=7,
        description="Hazard categories to include from the Live Traffic open feeds.",
    )
    limit: StrictInt = Field(default=10, ge=1, le=20)

    @model_validator(mode="before")
    @classmethod
    def collapse_suburb(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("suburb"), str):
            data = dict(value)
            data["suburb"] = _collapse_whitespace(data["suburb"])
            return data
        return value

    @model_validator(mode="after")
    def location_selector_is_unambiguous(self) -> LiveTrafficHazardsInput:
        has_coordinates = self.latitude is not None or self.longitude is not None
        if has_coordinates and (self.latitude is None or self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        if has_coordinates == (self.suburb is not None):
            raise ValueError("provide either coordinates or suburb")
        if len(set(self.hazard_types)) != len(self.hazard_types):
            raise ValueError("hazard_types must not contain duplicates")
        if self.suburb is not None:
            self.radius_metres = None
        return self
