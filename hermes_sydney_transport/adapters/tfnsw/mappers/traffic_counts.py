"""Pure Traffic Volume wire-to-canonical projections."""

from __future__ import annotations

from datetime import UTC, datetime

from ....models.outputs import Coordinates
from ....models.traffic_outputs import (
    HourlyTrafficCount,
    TrafficStation,
    TrafficVolumeSummary,
)
from ..wire.traffic_counts import (
    HourlyTrafficWire,
    TrafficStationWire,
    TrafficSummaryWire,
)


def map_station(row: TrafficStationWire) -> TrafficStation:
    coordinates = (
        Coordinates(
            latitude=row.wgs84_latitude,
            longitude=row.wgs84_longitude,
        )
        if row.wgs84_latitude is not None and row.wgs84_longitude is not None
        else None
    )
    return TrafficStation(
        station_key=row.station_key,
        station_id=row.station_id,
        name=row.name,
        road_name=row.road_name,
        suburb=row.suburb,
        post_code=row.post_code,
        coordinates=coordinates,
        permanent_station=row.permanent_station,
        vehicle_classifier=row.vehicle_classifier,
        quality_rating=row.quality_rating,
    )


def map_summary(row: TrafficSummaryWire) -> TrafficVolumeSummary:
    return TrafficVolumeSummary(
        station_key=row.station_key,
        station_id=row.station_id,
        traffic_direction_seq=row.traffic_direction_seq,
        traffic_direction_name=row.traffic_direction_name,
        cardinal_direction_seq=row.cardinal_direction_seq,
        cardinal_direction_name=row.cardinal_direction_name,
        classification_seq=row.classification_seq,
        classification_type=row.classification_type,
        count_type=row.count_type,
        year=row.year,
        period=row.period,
        partial_year=row.partial_year,
        latest_date=_utc(row.latest_date),
        traffic_count=row.traffic_count,
        data_start_date=_utc(row.data_start_date),
        data_end_date=_utc(row.data_end_date),
        data_duration=row.data_duration,
        data_availability=row.data_availability,
        data_reliability=row.data_reliability,
        data_quality_indicator=row.data_quality_indicator,
    )


def map_hourly(row: HourlyTrafficWire) -> HourlyTrafficCount:
    return HourlyTrafficCount(
        station_key=row.station_key,
        traffic_direction_seq=row.traffic_direction_seq,
        cardinal_direction_seq=row.cardinal_direction_seq,
        classification_seq=row.classification_seq,
        date=_utc_required(row.date),
        year=row.year,
        month=row.month,
        day_of_week=row.day_of_week,
        public_holiday=row.public_holiday,
        school_holiday=row.school_holiday,
        daily_total=row.daily_total,
        hourly_counts=[getattr(row, f"hour_{hour:02d}") for hour in range(24)],
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC)


def _utc_required(value: datetime) -> datetime:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC)
