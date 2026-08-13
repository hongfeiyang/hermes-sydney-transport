"""Normalized output contracts for NSW road traffic-volume data."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .outputs import Coordinates, PluginOutput, ResultMetadata, Timestamp


class TrafficStation(PluginOutput):
    station_key: str
    station_id: str
    name: str | None
    road_name: str | None
    suburb: str | None
    post_code: str | None
    coordinates: Coordinates | None
    permanent_station: bool | None
    vehicle_classifier: bool | None
    quality_rating: float | None = Field(default=None, ge=0)


class TrafficStationSearchResult(ResultMetadata):
    query: str | None
    station_id: str | None
    permanent_only: bool
    stations: list[TrafficStation]
    count: int = Field(ge=0)
    upstream_total_rows: int | None = Field(default=None, ge=0)
    quality_note: str

    @model_validator(mode="after")
    def count_matches(self) -> TrafficStationSearchResult:
        if self.count != len(self.stations):
            raise ValueError("count must equal the number of stations")
        return self


class TrafficVolumeSummary(PluginOutput):
    station_key: str
    station_id: str
    traffic_direction_seq: int | None
    traffic_direction_name: str | None
    cardinal_direction_seq: int | None
    cardinal_direction_name: str | None
    classification_seq: int | None
    classification_type: str | None
    count_type: str | None
    year: int
    period: str | None
    partial_year: bool | None
    latest_date: Timestamp | None
    traffic_count: float | None = Field(default=None, ge=0)
    data_start_date: Timestamp | None
    data_end_date: Timestamp | None
    data_duration: float | None
    data_availability: float | None
    data_reliability: float | None
    data_quality_indicator: float | None


class TrafficVolumeSummaryResult(ResultMetadata):
    station_id: str
    requested_year: int | None
    summaries: list[TrafficVolumeSummary]
    count: int = Field(ge=0)
    upstream_total_rows: int | None = Field(default=None, ge=0)
    quality_note: str

    @model_validator(mode="after")
    def count_matches(self) -> TrafficVolumeSummaryResult:
        if self.count != len(self.summaries):
            raise ValueError("count must equal the number of summaries")
        return self


class HourlyTrafficCount(PluginOutput):
    station_key: str
    traffic_direction_seq: int | None
    cardinal_direction_seq: int | None
    classification_seq: int | None
    date: Timestamp
    year: int
    month: int = Field(ge=1, le=12)
    day_of_week: int | None = Field(default=None, ge=0, le=7)
    public_holiday: bool | None
    school_holiday: bool | None
    daily_total: float | None = Field(default=None, ge=0)
    hourly_counts: list[float | None] = Field(min_length=24, max_length=24)


class TrafficVolumeHourlyResult(ResultMetadata):
    station_key: str
    dataset: Literal["permanent", "sample"]
    start_date: str
    end_date: str
    rows: list[HourlyTrafficCount]
    count: int = Field(ge=0)
    upstream_total_rows: int | None = Field(default=None, ge=0)
    quality_note: str

    @model_validator(mode="after")
    def count_matches(self) -> TrafficVolumeHourlyResult:
        if self.count != len(self.rows):
            raise ValueError("count must equal the number of rows")
        return self
