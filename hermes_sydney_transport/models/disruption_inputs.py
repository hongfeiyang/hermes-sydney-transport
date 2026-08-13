"""Pydantic contracts for GTFS-Realtime route disruption queries."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt, model_validator

from .inputs import ServiceId, StopId, TimedInput

DisruptionMode = Literal["train", "bus", "metro", "light_rail", "ferry"]

AlertCause = Literal[
    "unknown_cause",
    "other_cause",
    "technical_problem",
    "strike",
    "demonstration",
    "accident",
    "holiday",
    "weather",
    "maintenance",
    "construction",
    "police_activity",
    "medical_emergency",
]
AlertEffect = Literal[
    "no_service",
    "reduced_service",
    "significant_delays",
    "detour",
    "additional_service",
    "modified_service",
    "other_effect",
    "unknown_effect",
    "stop_moved",
    "no_effect",
    "accessibility_issue",
]


def _default_modes() -> list[DisruptionMode]:
    return ["train", "bus", "metro", "light_rail", "ferry"]


class RouteDisruptionsInput(TimedInput):
    modes: list[DisruptionMode] = Field(
        default_factory=_default_modes,
        min_length=1,
        max_length=5,
        description=(
            "Transport modes to include. Supported values are train, bus, metro, "
            "light_rail, and ferry."
        ),
    )
    stop_id: StopId | None = Field(
        default=None,
        description="Optional TfNSW stop ID to keep only disruptions affecting this stop.",
    )
    route_id: ServiceId | None = Field(
        default=None,
        description="Optional GTFS route_id to keep only disruptions affecting this route.",
    )
    trip_id: ServiceId | None = Field(
        default=None,
        description="Optional GTFS trip/service ID to keep only disruptions affecting this trip.",
    )
    causes: list[AlertCause] = Field(
        default_factory=list,
        min_length=0,
        max_length=4,
        description="Optional GTFS alert causes to include.",
    )
    effects: list[AlertEffect] = Field(
        default_factory=list,
        min_length=0,
        max_length=4,
        description="Optional GTFS alert effects to include.",
    )
    limit: StrictInt = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum disruptions to return.",
    )

    @model_validator(mode="after")
    def filters_are_unique(self) -> RouteDisruptionsInput:
        if len(set(self.modes)) != len(self.modes):
            raise ValueError("modes must not contain duplicates")
        if len(set(self.causes)) != len(self.causes):
            raise ValueError("causes must not contain duplicates")
        if len(set(self.effects)) != len(self.effects):
            raise ValueError("effects must not contain duplicates")
        return self
