"""Allowlisted Traffic Volume table and projection catalog."""

from __future__ import annotations

from types import MappingProxyType

STATION_COLUMNS = (
    "station_key",
    "station_id",
    "name",
    "road_name",
    "suburb",
    "post_code",
    "wgs84_latitude",
    "wgs84_longitude",
    "permanent_station",
    "vehicle_classifier",
    "quality_rating",
)
SUMMARY_COLUMNS = (
    "station_key",
    "station_id",
    "traffic_direction_seq",
    "traffic_direction_name",
    "cardinal_direction_seq",
    "cardinal_direction_name",
    "classification_seq",
    "classification_type",
    "count_type",
    "year",
    "period",
    "partial_year",
    "latest_date",
    "traffic_count",
    "data_start_date",
    "data_end_date",
    "data_duration",
    "data_availability",
    "data_reliability",
    "data_quality_indicator",
)
HOURLY_COLUMNS = (
    "station_key",
    "traffic_direction_seq",
    "cardinal_direction_seq",
    "classification_seq",
    "date",
    "year",
    "month",
    "day_of_week",
    "public_holiday",
    "school_holiday",
    "daily_total",
    *(f"hour_{hour:02d}" for hour in range(24)),
)
HOURLY_TABLES = MappingProxyType(
    {
        "permanent": "road_traffic_counts_hourly_permanent",
        "sample": "road_traffic_counts_hourly_sample",
    }
)


def projection(columns: tuple[str, ...]) -> str:
    return ", ".join(columns)
