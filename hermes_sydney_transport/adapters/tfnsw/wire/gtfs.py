"""Declarative row contracts for both realtime-static and Complete GTFS CSVs."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from .base import WireModel

_MAX_TEXT = 8_192


def _optional_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("GTFS text must be a string")  # noqa: TRY004
    return value


def _integer(value: object) -> int:
    if not isinstance(value, str) or not value or not value.isascii():
        raise ValueError("GTFS integer must be decimal text")
    return int(value)


def _optional_integer(value: object) -> int | None:
    return None if value is None or value == "" else _integer(value)


def _time(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("GTFS time must be text")  # noqa: TRY004
    parts = value.split(":")
    if len(parts) != 3 or any(not part.isdecimal() for part in parts):
        raise ValueError("GTFS time has invalid shape")
    hour, minute, second = map(int, parts)
    if hour not in range(48) or minute not in range(60) or second not in range(60):
        raise ValueError("GTFS time is outside the supported service day")
    return value


def _optional_time(value: object) -> str | None:
    return None if value is None or value == "" else _time(value)


def _date_text(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 8
        or not value.isascii()
        or not value.isdecimal()
    ):
        raise ValueError("GTFS date has invalid shape")
    parsed = date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return parsed.strftime("%Y%m%d")


RequiredText = Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
BoundedText = Annotated[str, Field(max_length=_MAX_TEXT)]
OptionalText = Annotated[
    BoundedText | None,
    BeforeValidator(_optional_text),
]
OptionalInteger = Annotated[int | None, BeforeValidator(_optional_integer)]
GtfsTimeText = Annotated[str, BeforeValidator(_time)]
OptionalGtfsTimeText = Annotated[str | None, BeforeValidator(_optional_time)]
GtfsDateText = Annotated[str, BeforeValidator(_date_text)]
BinaryInteger = Annotated[Literal[0, 1], BeforeValidator(_integer)]
DirectionInteger = Annotated[Literal[0, 1] | None, BeforeValidator(_optional_integer)]
ChoiceInteger = Annotated[
    Literal[0, 1, 2, 3] | None, BeforeValidator(_optional_integer)
]
WheelchairInteger = Annotated[
    Literal[0, 1, 2] | None, BeforeValidator(_optional_integer)
]


class GtfsRow(WireModel):
    """Shared declaration base for GTFS CSV rows."""


class RouteRow(GtfsRow):
    route_id: RequiredText
    agency_id: OptionalText = None
    route_type: Annotated[
        int | None, BeforeValidator(_optional_integer), Field(ge=0, le=2_000)
    ] = None
    route_short_name: OptionalText = None
    route_long_name: OptionalText = None
    route_desc: OptionalText = None


class StopRow(GtfsRow):
    stop_id: RequiredText
    stop_name: OptionalText = None
    parent_station: OptionalText = None
    platform_code: OptionalText = None


class TripRow(GtfsRow):
    trip_id: RequiredText
    service_id: RequiredText
    route_id: RequiredText
    trip_headsign: OptionalText = None
    direction_id: DirectionInteger = None
    vehicle_category_id: OptionalText = None
    wheelchair_accessible: WheelchairInteger = None


class StopTimeRow(GtfsRow):
    trip_id: RequiredText
    stop_id: RequiredText
    stop_sequence: Annotated[int, BeforeValidator(_integer), Field(ge=0, le=10_000)]
    arrival_time: OptionalGtfsTimeText = None
    departure_time: OptionalGtfsTimeText = None
    stop_headsign: OptionalText = None
    pickup_type: ChoiceInteger = None
    drop_off_type: ChoiceInteger = None

    @model_validator(mode="after")
    def has_an_event_time(self) -> StopTimeRow:
        if self.arrival_time is None and self.departure_time is None:
            raise ValueError("stop time requires arrival or departure")
        return self


class CalendarRow(GtfsRow):
    service_id: RequiredText
    monday: BinaryInteger
    tuesday: BinaryInteger
    wednesday: BinaryInteger
    thursday: BinaryInteger
    friday: BinaryInteger
    saturday: BinaryInteger
    sunday: BinaryInteger
    start_date: GtfsDateText
    end_date: GtfsDateText

    @model_validator(mode="after")
    def date_range_is_ordered(self) -> CalendarRow:
        if self.start_date > self.end_date:
            raise ValueError("calendar start date follows its end date")
        return self


class CalendarDateRow(GtfsRow):
    service_id: RequiredText
    date: GtfsDateText
    exception_type: Annotated[Literal[1, 2], BeforeValidator(_integer)]
