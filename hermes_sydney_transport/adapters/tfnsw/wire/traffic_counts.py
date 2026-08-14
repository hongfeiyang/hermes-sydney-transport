"""Typed wire contracts for the NSW Traffic Volume Counts JSON API."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .base import (
    NullableBool,
    NullableFloat,
    NullableInt,
    NullableText,
    ShortText,
    WireModel,
)
from .timestamps import NullableTimestamp, WireTimestamp


class FieldDescriptionWire(WireModel):
    type: ShortText | None = None


class TrafficResponseWire[RowT](WireModel):
    rows: Annotated[tuple[RowT, ...], Field(max_length=10_000)]
    fields: Annotated[
        dict[str, FieldDescriptionWire], Field(min_length=1, max_length=200)
    ]
    total_rows: NullableInt = None


class TrafficStationWire(WireModel):
    station_key: Annotated[str, Field(strict=False, max_length=100)]
    station_id: Annotated[str, Field(strict=False, max_length=100)]
    name: NullableText = None
    road_name: NullableText = None
    suburb: NullableText = None
    post_code: NullableText = None
    wgs84_latitude: NullableFloat = None
    wgs84_longitude: NullableFloat = None
    permanent_station: NullableBool = None
    vehicle_classifier: NullableBool = None
    quality_rating: NullableFloat = None


class TrafficSummaryWire(WireModel):
    station_key: Annotated[str, Field(strict=False, max_length=100)]
    station_id: Annotated[str, Field(strict=False, max_length=100)]
    traffic_direction_seq: NullableInt = None
    traffic_direction_name: NullableText = None
    cardinal_direction_seq: NullableInt = None
    cardinal_direction_name: NullableText = None
    classification_seq: NullableInt = None
    classification_type: NullableText = None
    count_type: NullableText = None
    year: Annotated[int, Field(strict=False, ge=1900, le=2200)]
    period: NullableText = None
    partial_year: NullableBool = None
    latest_date: NullableTimestamp = None
    traffic_count: NullableFloat = None
    data_start_date: NullableTimestamp = None
    data_end_date: NullableTimestamp = None
    data_duration: NullableFloat = None
    data_availability: NullableFloat = None
    data_reliability: NullableFloat = None
    data_quality_indicator: NullableFloat = None


class HourlyTrafficWire(WireModel):
    station_key: Annotated[str, Field(strict=False, max_length=100)]
    traffic_direction_seq: NullableInt = None
    cardinal_direction_seq: NullableInt = None
    classification_seq: NullableInt = None
    date: WireTimestamp
    year: Annotated[int, Field(strict=False, ge=1900, le=2200)]
    month: Annotated[int, Field(strict=False, ge=1, le=12)]
    day_of_week: NullableInt = None
    public_holiday: NullableBool = None
    school_holiday: NullableBool = None
    daily_total: NullableFloat = None
    hour_00: NullableFloat = None
    hour_01: NullableFloat = None
    hour_02: NullableFloat = None
    hour_03: NullableFloat = None
    hour_04: NullableFloat = None
    hour_05: NullableFloat = None
    hour_06: NullableFloat = None
    hour_07: NullableFloat = None
    hour_08: NullableFloat = None
    hour_09: NullableFloat = None
    hour_10: NullableFloat = None
    hour_11: NullableFloat = None
    hour_12: NullableFloat = None
    hour_13: NullableFloat = None
    hour_14: NullableFloat = None
    hour_15: NullableFloat = None
    hour_16: NullableFloat = None
    hour_17: NullableFloat = None
    hour_18: NullableFloat = None
    hour_19: NullableFloat = None
    hour_20: NullableFloat = None
    hour_21: NullableFloat = None
    hour_22: NullableFloat = None
    hour_23: NullableFloat = None
