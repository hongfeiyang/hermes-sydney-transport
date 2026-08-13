"""Map TfNSW protobuf messages into immutable dependency-neutral records."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from ...models.errors import DomainError
from ...ports.alerts import AlertRecord, AlertSelector, AlertTimeRange
from ...ports.realtime import (
    CarriageRecord,
    GtfsTime,
    StopEvent,
    StopRelationship,
    TrackDirection,
    TransportMode,
    TripRelationship,
    TripStopUpdate,
    TripUpdateRecord,
    TripUpdatesFeed,
    UpdateBundle,
    VehicleCoordinates,
    VehicleDescriptorRecord,
    VehiclePositionsFeed,
    VehicleRecord,
    VehicleStatus,
)

TfnswApiError = DomainError


class ProtobufRealtimeDecoder:
    def trip_updates(self, raw: bytes) -> TripUpdatesFeed:
        return decode_trip_updates(raw)

    def vehicle_positions(self, raw: bytes) -> VehiclePositionsFeed:
        return decode_vehicle_positions(raw)

    def alerts(
        self, raw: bytes, mode: TransportMode, source_feed: str | None = None
    ) -> tuple[AlertRecord, ...]:
        return decode_alerts(raw, mode, source_feed)


@lru_cache(maxsize=1)
def _binding() -> Any:
    try:
        from ...proto import tfnsw_gtfs_realtime_pb2
    except Exception as exc:
        raise TfnswApiError(
            "unsupported_dependency",
            "GTFS-Realtime support requires a compatible protobuf runtime.",
        ) from exc
    return tfnsw_gtfs_realtime_pb2


def protobuf_available() -> bool:
    try:
        _binding()
    except TfnswApiError:
        return False
    return True


def decode_trip_updates(raw: bytes) -> TripUpdatesFeed:
    pb = _binding()
    feed = _parse_feed(raw, pb)
    updates: dict[str, TripUpdateRecord] = {}
    bundles: list[UpdateBundle] = []
    for entity in feed.entity:
        if entity.HasExtension(pb.update):
            bundle = entity.Extensions[pb.update]
            bundles.append(
                UpdateBundle(
                    bundle_id=str(bundle.GTFSStaticBundle).strip(),
                    update_sequence=int(bundle.update_sequence),
                    cancelled_trip_ids=frozenset(
                        text
                        for item in bundle.cancelled_trip
                        if (text := str(item).strip())
                    ),
                )
            )
        if not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        service_id = _optional_text(update.trip, "trip_id")
        if not service_id:
            continue
        stops = tuple(_trip_stop(stop, pb) for stop in update.stop_time_update)
        updates[service_id] = TripUpdateRecord(
            service_id=service_id,
            route_id=_optional_text(update.trip, "route_id"),
            start_date=_optional_service_date(update.trip, "start_date"),
            start_time=_optional_gtfs_time(update.trip, "start_time"),
            relationship=_trip_relationship(
                update.trip.ScheduleRelationship,
                update.trip.schedule_relationship,
            ),
            timestamp=_optional_timestamp(update, "timestamp"),
            delay=_optional_duration(update, "delay"),
            vehicle_label=(
                _optional_text(update.vehicle, "label")
                if update.HasField("vehicle")
                else None
            ),
            stop_updates=stops,
        )
    return TripUpdatesFeed(
        feed_timestamp=_feed_timestamp(feed),
        updates=MappingProxyType(updates),
        update_bundles=tuple(bundles),
    )


def decode_vehicle_positions(raw: bytes) -> VehiclePositionsFeed:
    pb = _binding()
    feed = _parse_feed(raw, pb)
    vehicles: dict[str, VehicleRecord] = {}
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        if not vehicle.HasField("trip"):
            continue
        service_id = _optional_text(vehicle.trip, "trip_id")
        if not service_id:
            continue
        vehicles[service_id] = _vehicle_record(vehicle, service_id, pb)
    return VehiclePositionsFeed(
        feed_timestamp=_feed_timestamp(feed),
        vehicles=MappingProxyType(vehicles),
    )


def decode_alerts(
    raw: bytes, mode: TransportMode, source_feed: str | None = None
) -> tuple[AlertRecord, ...]:
    pb = _binding()
    feed = _parse_feed(raw, pb)
    feed_name = source_feed or mode.value
    records: list[AlertRecord] = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        selectors = tuple(_alert_selector(item) for item in alert.informed_entity)
        route_ids = tuple(
            sorted(
                {
                    selector.route_id
                    for selector in selectors
                    if selector.route_id is not None
                }
            )
        )
        stop_ids = tuple(
            sorted(
                {
                    selector.stop_id
                    for selector in selectors
                    if selector.stop_id is not None
                }
            )
        )
        trip_ids = tuple(
            sorted(
                {
                    selector.trip_id
                    for selector in selectors
                    if selector.trip_id is not None
                }
            )
        )
        title = _translated_text(alert, "header_text")
        description = _translated_text(alert, "description_text")
        records.append(
            AlertRecord(
                id=str(entity.id).strip() or title or description or "unknown-alert",
                mode=mode,
                source_feed=feed_name,
                title=title or description or "Service disruption",
                description=description,
                cause=_enum_name(alert.Cause, alert.cause, "unknown_cause")
                or "unknown_cause",
                effect=_enum_name(alert.Effect, alert.effect, "unknown_effect")
                or "unknown_effect",
                severity=(
                    _enum_name(
                        alert.SeverityLevel,
                        alert.severity_level,
                        "unknown_severity",
                    )
                    if alert.HasField("severity_level")
                    else "unknown_severity"
                )
                or "unknown_severity",
                url=_translated_text(alert, "url") or None,
                active_periods=tuple(_time_range(item) for item in alert.active_period),
                selectors=selectors,
                route_ids=route_ids,
                stop_ids=stop_ids,
                trip_ids=trip_ids,
            )
        )
    return tuple(records)


def _trip_stop(stop: Any, pb: Any) -> TripStopUpdate:
    return TripStopUpdate(
        sequence=_optional_scalar(stop, "stop_sequence"),
        stop_id=_optional_text(stop, "stop_id"),
        arrival=_stop_event(stop.arrival) if stop.HasField("arrival") else None,
        departure=_stop_event(stop.departure) if stop.HasField("departure") else None,
        relationship=_stop_relationship(
            stop.ScheduleRelationship, stop.schedule_relationship
        ),
        departure_occupancy=(
            _enum_name(stop.OccupancyStatus, stop.departure_occupancy_status, None)
            if stop.HasField("departure_occupancy_status")
            else None
        ),
        predictive_carriages=tuple(
            _carriage(item)
            for item in stop.Extensions[pb.carriage_seq_predictive_occupancy]
        ),
    )


def _vehicle_record(vehicle: Any, service_id: str, pb: Any) -> VehicleRecord:
    position = None
    if vehicle.HasField("position"):
        raw = vehicle.position
        direction = (
            _track_direction(raw.Extensions[pb.track_direction], pb)
            if raw.HasExtension(pb.track_direction)
            else TrackDirection.UNKNOWN
        )
        position = VehicleCoordinates(
            latitude=float(raw.latitude),
            longitude=float(raw.longitude),
            bearing=_optional_scalar(raw, "bearing"),
            speed=_optional_scalar(raw, "speed"),
            track_direction=direction,
        )
    descriptor = None
    label = None
    if vehicle.HasField("vehicle"):
        label = _optional_text(vehicle.vehicle, "label")
        if vehicle.vehicle.HasExtension(pb.tfnsw_vehicle_descriptor):
            detail = vehicle.vehicle.Extensions[pb.tfnsw_vehicle_descriptor]
            descriptor = VehicleDescriptorRecord(
                model=_optional_text(detail, "vehicle_model"),
                air_conditioned=_optional_scalar(detail, "air_conditioned"),
                wheelchair_accessible=_wheelchair_accessible(detail),
            )
    return VehicleRecord(
        service_id=service_id,
        route_id=_optional_text(vehicle.trip, "route_id"),
        start_date=_optional_service_date(vehicle.trip, "start_date"),
        start_time=_optional_gtfs_time(vehicle.trip, "start_time"),
        relationship=_trip_relationship(
            vehicle.trip.ScheduleRelationship, vehicle.trip.schedule_relationship
        ),
        label=label,
        descriptor=descriptor,
        position=position,
        current_stop_sequence=_optional_scalar(vehicle, "current_stop_sequence"),
        reported_stop_id=_optional_text(vehicle, "stop_id"),
        current_status=_vehicle_status(
            vehicle.VehicleStopStatus, vehicle.current_status
        ),
        timestamp=_optional_timestamp(vehicle, "timestamp"),
        occupancy=(
            _enum_name(vehicle.OccupancyStatus, vehicle.occupancy_status, None)
            if vehicle.HasField("occupancy_status")
            else None
        ),
        carriages=tuple(_carriage(item) for item in vehicle.Extensions[pb.consist]),
    )


def _parse_feed(raw: bytes, pb: Any) -> Any:
    if not raw:
        raise TfnswApiError(
            "invalid_realtime_feed", "TfNSW returned an empty GTFS-Realtime feed."
        )
    feed = pb.FeedMessage()
    try:
        feed.ParseFromString(raw)
    except Exception as exc:
        raise TfnswApiError(
            "invalid_realtime_feed",
            "TfNSW returned an invalid GTFS-Realtime protobuf feed.",
        ) from exc
    if not feed.IsInitialized():
        raise TfnswApiError(
            "invalid_realtime_feed",
            "TfNSW returned an incomplete GTFS-Realtime protobuf feed.",
        )
    return feed


def _feed_timestamp(feed: Any) -> datetime:
    if not feed.header.HasField("timestamp"):
        raise TfnswApiError(
            "invalid_realtime_feed",
            "TfNSW realtime feed did not provide a feed timestamp.",
        )
    return _unix_timestamp(feed.header.timestamp)


def _stop_event(event: Any) -> StopEvent:
    return StopEvent(
        time=_optional_timestamp(event, "time"),
        delay=_optional_duration(event, "delay"),
        uncertainty=_optional_duration(event, "uncertainty"),
    )


def _carriage(item: Any) -> CarriageRecord:
    return CarriageRecord(
        name=_optional_text(item, "name"),
        position_in_consist=int(item.position_in_consist),
        occupancy=(
            _enum_name(item.OccupancyStatus, item.occupancy_status, None)
            if item.HasField("occupancy_status")
            else None
        ),
        quiet_carriage=_optional_scalar(item, "quiet_carriage"),
        toilet=(
            _enum_name(item.ToiletStatus, item.toilet, None)
            if item.HasField("toilet")
            else None
        ),
        luggage_rack=_optional_scalar(item, "luggage_rack"),
    )


def _optional_text(message: Any, field: str) -> str | None:
    if not message.HasField(field):
        return None
    value = str(getattr(message, field)).strip()
    return value or None


def _optional_service_date(message: Any, field: str) -> date | None:
    text = _optional_text(message, field)
    if text is None:
        return None
    if len(text) != 8 or not text.isdigit():
        raise _invalid_value("service date")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        raise _invalid_value("service date") from exc


def _optional_gtfs_time(message: Any, field: str) -> GtfsTime | None:
    text = _optional_text(message, field)
    return _gtfs_time(text) if text else None


def _gtfs_time(text: str) -> GtfsTime:
    try:
        hour, minute, second = (int(part) for part in text.split(":"))
    except (TypeError, ValueError) as exc:
        raise _invalid_value("GTFS service time") from exc
    if hour < 0 or hour > 47 or minute not in range(60) or second not in range(60):
        raise _invalid_value("GTFS service time")
    return GtfsTime(hour * 3600 + minute * 60 + second)


def _wheelchair_accessible(descriptor: Any) -> bool | None:
    if not descriptor.HasField("wheelchair_accessible"):
        return None
    value = int(descriptor.wheelchair_accessible)
    return False if value == 0 else True if value == 1 else None


def _optional_scalar(message: Any, field: str) -> Any:
    return getattr(message, field) if message.HasField(field) else None


def _optional_duration(message: Any, field: str) -> timedelta | None:
    value = _optional_scalar(message, field)
    return timedelta(seconds=int(value)) if value is not None else None


def _optional_timestamp(message: Any, field: str) -> datetime | None:
    value = _optional_scalar(message, field)
    return _unix_timestamp(value) if value is not None else None


def _unix_timestamp(value: int) -> datetime:
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise _invalid_value("Unix timestamp") from exc


def _trip_relationship(enum_type: Any, value: int) -> TripRelationship:
    name = _enum_name(enum_type, value, "unknown")
    name = "cancelled" if name == "canceled" else name
    try:
        return TripRelationship(name or "unknown")
    except ValueError:
        return TripRelationship.UNKNOWN


def _stop_relationship(enum_type: Any, value: int) -> StopRelationship:
    name = _enum_name(enum_type, value, "no_data")
    try:
        return StopRelationship(name or "no_data")
    except ValueError:
        return StopRelationship.NO_DATA


def _vehicle_status(enum_type: Any, value: int) -> VehicleStatus:
    name = _enum_name(enum_type, value, "unknown")
    try:
        return VehicleStatus(name or "unknown")
    except ValueError:
        return VehicleStatus.UNKNOWN


def _track_direction(value: int, pb: Any) -> TrackDirection:
    name = _enum_name(pb.TrackDirection, value, "unknown")
    try:
        return TrackDirection(name or "unknown")
    except ValueError:
        return TrackDirection.UNKNOWN


def _time_range(item: Any) -> AlertTimeRange:
    return AlertTimeRange(
        start=_optional_timestamp(item, "start"),
        end=_optional_timestamp(item, "end"),
    )


def _alert_selector(item: Any) -> AlertSelector:
    trip = item.trip if item.HasField("trip") else None
    return AlertSelector(
        agency_id=_optional_text(item, "agency_id"),
        route_id=_optional_text(item, "route_id"),
        route_type=_optional_scalar(item, "route_type"),
        stop_id=_optional_text(item, "stop_id"),
        trip_id=_optional_text(trip, "trip_id") if trip is not None else None,
        direction_id=_optional_scalar(item, "direction_id"),
    )


def _translated_text(message: Any, field: str) -> str:
    if not message.HasField(field):
        return ""
    translated = getattr(message, field)
    for item in translated.translation:
        text = str(item.text).strip()
        if text:
            return text
    return ""


def _enum_name(enum_type: Any, value: int, default: str | None) -> str | None:
    try:
        return str(enum_type.Name(value)).lower()
    except ValueError:
        return default


def _invalid_value(kind: str) -> TfnswApiError:
    return TfnswApiError(
        "invalid_realtime_feed",
        f"TfNSW realtime feed contained an invalid {kind}.",
    )
