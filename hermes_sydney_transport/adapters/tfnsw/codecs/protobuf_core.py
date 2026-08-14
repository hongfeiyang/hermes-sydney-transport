"""Shared bounded conversions at the GTFS-Realtime protobuf boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

from ....models.errors import DomainError
from ....ports.alerts import AlertSelector, AlertTimeRange
from ....ports.realtime import (
    CarriageRecord,
    GtfsTime,
    StopEvent,
    StopRelationship,
    TrackDirection,
    TripRelationship,
    VehicleStatus,
)


@lru_cache(maxsize=1)
def binding() -> Any:
    try:
        from ....proto import tfnsw_gtfs_realtime_pb2
    except Exception as exc:
        raise DomainError(
            "unsupported_dependency",
            "GTFS-Realtime support requires a compatible protobuf runtime.",
        ) from exc
    return tfnsw_gtfs_realtime_pb2


def protobuf_available() -> bool:
    try:
        binding()
    except DomainError:
        return False
    return True


def parse_feed(raw: bytes, pb: Any) -> Any:
    if not raw:
        raise invalid_value("empty GTFS-Realtime feed")
    feed = pb.FeedMessage()
    try:
        feed.ParseFromString(raw)
    except Exception as exc:
        raise invalid_value("GTFS-Realtime protobuf feed") from exc
    if not feed.IsInitialized():
        raise invalid_value("incomplete GTFS-Realtime protobuf feed")
    return feed


def feed_timestamp(feed: Any) -> datetime:
    if not feed.header.HasField("timestamp"):
        raise invalid_value("feed timestamp")
    return unix_timestamp(feed.header.timestamp)


def optional_text(message: Any, field: str) -> str | None:
    if not message.HasField(field):
        return None
    value = str(getattr(message, field)).strip()
    return value or None


def optional_scalar(message: Any, field: str) -> Any:
    return getattr(message, field) if message.HasField(field) else None


def optional_duration(message: Any, field: str) -> timedelta | None:
    value = optional_scalar(message, field)
    return timedelta(seconds=int(value)) if value is not None else None


def optional_timestamp(message: Any, field: str) -> datetime | None:
    value = optional_scalar(message, field)
    return unix_timestamp(value) if value is not None else None


def unix_timestamp(value: int) -> datetime:
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise invalid_value("Unix timestamp") from exc


def optional_service_date(message: Any, field: str) -> date | None:
    text = optional_text(message, field)
    if text is None:
        return None
    if len(text) != 8 or not text.isdigit():
        raise invalid_value("service date")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        raise invalid_value("service date") from exc


def optional_gtfs_time(message: Any, field: str) -> GtfsTime | None:
    text = optional_text(message, field)
    return gtfs_time(text) if text else None


def gtfs_time(text: str) -> GtfsTime:
    try:
        hour, minute, second = (int(part) for part in text.split(":"))
    except (TypeError, ValueError) as exc:
        raise invalid_value("GTFS service time") from exc
    if hour not in range(48) or minute not in range(60) or second not in range(60):
        raise invalid_value("GTFS service time")
    return GtfsTime(hour * 3_600 + minute * 60 + second)


def enum_name(enum_type: Any, value: int, default: str | None) -> str | None:
    try:
        return str(enum_type.Name(value)).lower()
    except ValueError:
        return default


def trip_relationship(enum_type: Any, value: int) -> TripRelationship:
    name = enum_name(enum_type, value, "unknown")
    normalized = "cancelled" if name == "canceled" else name
    try:
        return TripRelationship(normalized or "unknown")
    except ValueError:
        return TripRelationship.UNKNOWN


def stop_relationship(enum_type: Any, value: int) -> StopRelationship:
    try:
        return StopRelationship(enum_name(enum_type, value, "no_data") or "no_data")
    except ValueError:
        return StopRelationship.NO_DATA


def vehicle_status(enum_type: Any, value: int) -> VehicleStatus:
    try:
        return VehicleStatus(enum_name(enum_type, value, "unknown") or "unknown")
    except ValueError:
        return VehicleStatus.UNKNOWN


def track_direction(value: int, pb: Any) -> TrackDirection:
    try:
        return TrackDirection(
            enum_name(pb.TrackDirection, value, "unknown") or "unknown"
        )
    except ValueError:
        return TrackDirection.UNKNOWN


def stop_event(event: Any) -> StopEvent:
    return StopEvent(
        time=optional_timestamp(event, "time"),
        delay=optional_duration(event, "delay"),
        uncertainty=optional_duration(event, "uncertainty"),
    )


def carriage(item: Any) -> CarriageRecord:
    return CarriageRecord(
        name=optional_text(item, "name"),
        position_in_consist=int(item.position_in_consist),
        occupancy=(
            enum_name(item.OccupancyStatus, item.occupancy_status, None)
            if item.HasField("occupancy_status")
            else None
        ),
        quiet_carriage=optional_scalar(item, "quiet_carriage"),
        toilet=(
            enum_name(item.ToiletStatus, item.toilet, None)
            if item.HasField("toilet")
            else None
        ),
        luggage_rack=optional_scalar(item, "luggage_rack"),
    )


def time_range(item: Any) -> AlertTimeRange:
    return AlertTimeRange(
        start=optional_timestamp(item, "start"), end=optional_timestamp(item, "end")
    )


def alert_selector(item: Any) -> AlertSelector:
    trip = item.trip if item.HasField("trip") else None
    return AlertSelector(
        agency_id=optional_text(item, "agency_id"),
        route_id=optional_text(item, "route_id"),
        route_type=optional_scalar(item, "route_type"),
        stop_id=optional_text(item, "stop_id"),
        trip_id=optional_text(trip, "trip_id") if trip is not None else None,
        direction_id=optional_scalar(item, "direction_id"),
    )


def translated_text(message: Any, field: str) -> str:
    if not message.HasField(field):
        return ""
    return next(
        (
            text
            for item in getattr(message, field).translation
            if (text := str(item.text).strip())
        ),
        "",
    )


def invalid_value(kind: str) -> DomainError:
    return DomainError(
        "invalid_realtime_feed",
        f"TfNSW realtime feed contained an invalid {kind}.",
    )
