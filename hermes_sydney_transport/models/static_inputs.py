"""Strict inputs for static TfNSW facilities and Complete GTFS tools."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

from .inputs import PluginInput, StopId, _collapse_whitespace

_DATE_ADAPTER = TypeAdapter(date)
_DATE_TEXT_ADAPTER: TypeAdapter[str] = TypeAdapter(
    Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
)

CompleteGtfsRouteId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:+-]+$",
    ),
    BeforeValidator(_collapse_whitespace),
]


class StopAccessibilityInput(PluginInput):
    """Look up one exact TfNSW stop in static accessibility sources."""

    stop_id: StopId = Field(
        description=(
            "Exact TfNSW stop ID returned by sydney_transport_search_stops. The "
            "adapter matches EFA_ID first and TSN second; names are not fuzzy matched."
        )
    )
    include_current_warnings: StrictBool = Field(
        default=True,
        description=(
            "When true, also check current TfNSW accessibility alerts for this exact "
            "stop. No warning does not prove lifts or other facilities are operating."
        ),
    )
    warning_limit: StrictInt = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum current accessibility warnings to return.",
    )


class RouteTimetableInput(PluginInput):
    """Query one exact route in the Complete GTFS identifier namespace."""

    route_id: CompleteGtfsRouteId = Field(
        description=(
            "Exact route_id from TfNSW Complete GTFS. Complete GTFS identifiers do "
            "not match realtime-feed identifiers."
        )
    )
    service_date: date | None = Field(
        default=None,
        ge=date(2000, 1, 1),
        le=date(2100, 12, 30),
        description=(
            "Optional service date in YYYY-MM-DD form. Defaults to today's date in "
            "Australia/Sydney."
        ),
    )
    direction_id: Literal[0, 1] | None = Field(
        default=None,
        description="Optional exact GTFS direction_id filter.",
    )
    stop_id: StopId | None = Field(
        default=None,
        description=(
            "Optional exact Complete GTFS stop_id. When supplied, only trips serving "
            "that stop are returned."
        ),
    )
    limit: StrictInt = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum scheduled trips to return.",
    )

    @field_validator("service_date", mode="before", json_schema_input_type=date | None)
    @classmethod
    def parse_service_date(cls, value: object) -> object:
        if value is None or isinstance(value, date):
            return value
        text = _DATE_TEXT_ADAPTER.validate_python(value, strict=True)
        return _DATE_ADAPTER.validate_python(text, strict=False)
