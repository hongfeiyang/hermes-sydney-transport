"""Pydantic contracts for the NSW Traffic Volume Counts tools."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .inputs import PluginInput, _collapse_whitespace

TrafficStationId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$"),
    BeforeValidator(_collapse_whitespace),
]
TrafficStationKey = Annotated[
    str,
    StringConstraints(min_length=1, max_length=20, pattern=r"^\d+$"),
    BeforeValidator(_collapse_whitespace),
]
TrafficSearchText = Annotated[
    str,
    StringConstraints(min_length=2, max_length=100),
    BeforeValidator(_collapse_whitespace),
]
_DATE_TEXT: TypeAdapter[str] = TypeAdapter(
    Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
)


def _parse_date(value: object) -> object:
    if isinstance(value, date):
        return value
    text = _DATE_TEXT.validate_python(value, strict=True)
    return date.fromisoformat(text)


TrafficDate = Annotated[date, BeforeValidator(_parse_date)]


class TrafficStationSearchInput(PluginInput):
    query: TrafficSearchText | None = Field(
        default=None,
        description="Road, suburb, site name, or partial text to search.",
    )
    station_id: TrafficStationId | None = Field(
        default=None,
        description="Exact published traffic-count station ID.",
    )
    permanent_only: StrictBool = Field(
        default=False,
        description="Only return permanent counting stations.",
    )
    limit: StrictInt = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def has_search_term(self) -> TrafficStationSearchInput:
        if self.query is None and self.station_id is None:
            raise ValueError("provide query or station_id")
        return self


class TrafficVolumeSummaryInput(PluginInput):
    station_id: TrafficStationId
    year: StrictInt | None = Field(default=None, ge=2006, le=2100)
    limit: StrictInt = Field(default=50, ge=1, le=100)


class TrafficVolumeHourlyInput(PluginInput):
    station_key: TrafficStationKey = Field(
        description="Internal station_key returned by nsw_traffic_count_stations."
    )
    dataset: Literal["permanent", "sample"] = Field(
        description="Use permanent for continuous counters or sample for surveys."
    )
    start_date: TrafficDate
    end_date: TrafficDate
    traffic_direction_seq: StrictInt | None = Field(default=None, ge=0, le=99)
    classification_seq: StrictInt | None = Field(default=None, ge=0, le=99)
    limit: StrictInt = Field(default=100, ge=1, le=500)

    @field_validator(
        "start_date", "end_date", mode="before", json_schema_input_type=date
    )
    @classmethod
    def parse_iso_date(cls, value: object) -> object:
        return _parse_date(value)

    @model_validator(mode="after")
    def date_window_is_bounded(self) -> TrafficVolumeHourlyInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.end_date - self.start_date > timedelta(days=31):
            raise ValueError("date range must not exceed 31 days")
        return self
