"""GTFS-Realtime Trip Updates and Vehicle Positions protobuf projection."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from ....ports.realtime import (
    TrackDirection,
    TripStopUpdate,
    TripUpdateRecord,
    TripUpdatesFeed,
    UpdateBundle,
    VehicleCoordinates,
    VehicleDescriptorRecord,
    VehiclePositionsFeed,
    VehicleRecord,
)
from .protobuf_core import (
    binding,
    carriage,
    enum_name,
    feed_timestamp,
    optional_duration,
    optional_gtfs_time,
    optional_scalar,
    optional_service_date,
    optional_text,
    optional_timestamp,
    parse_feed,
    stop_event,
    stop_relationship,
    track_direction,
    trip_relationship,
    vehicle_status,
)


def decode_trip_updates(raw: bytes) -> TripUpdatesFeed:
    pb = binding()
    feed = parse_feed(raw, pb)
    updates = {
        record.service_id: record
        for entity in feed.entity
        if (record := _trip_update(entity, pb)) is not None
    }
    bundles = tuple(
        bundle
        for entity in feed.entity
        if (bundle := _update_bundle(entity, pb)) is not None
    )
    return TripUpdatesFeed(
        feed_timestamp=feed_timestamp(feed),
        updates=MappingProxyType(updates),
        update_bundles=bundles,
    )


def decode_vehicle_positions(raw: bytes) -> VehiclePositionsFeed:
    pb = binding()
    feed = parse_feed(raw, pb)
    records = (
        record
        for entity in feed.entity
        if (record := _vehicle_entity(entity, pb)) is not None
    )
    return VehiclePositionsFeed(
        feed_timestamp=feed_timestamp(feed),
        vehicles=MappingProxyType({record.service_id: record for record in records}),
    )


def _update_bundle(entity: Any, pb: Any) -> UpdateBundle | None:
    if not entity.HasExtension(pb.update):
        return None
    bundle = entity.Extensions[pb.update]
    return UpdateBundle(
        bundle_id=str(bundle.GTFSStaticBundle).strip(),
        update_sequence=int(bundle.update_sequence),
        cancelled_trip_ids=frozenset(
            text for item in bundle.cancelled_trip if (text := str(item).strip())
        ),
    )


def _trip_update(entity: Any, pb: Any) -> TripUpdateRecord | None:
    if not entity.HasField("trip_update"):
        return None
    update = entity.trip_update
    service_id = optional_text(update.trip, "trip_id")
    if not service_id:
        return None
    return TripUpdateRecord(
        service_id=service_id,
        route_id=optional_text(update.trip, "route_id"),
        start_date=optional_service_date(update.trip, "start_date"),
        start_time=optional_gtfs_time(update.trip, "start_time"),
        relationship=trip_relationship(
            update.trip.ScheduleRelationship, update.trip.schedule_relationship
        ),
        timestamp=optional_timestamp(update, "timestamp"),
        delay=optional_duration(update, "delay"),
        vehicle_label=(
            optional_text(update.vehicle, "label")
            if update.HasField("vehicle")
            else None
        ),
        stop_updates=tuple(_trip_stop(stop, pb) for stop in update.stop_time_update),
    )


def _trip_stop(stop: Any, pb: Any) -> TripStopUpdate:
    return TripStopUpdate(
        sequence=optional_scalar(stop, "stop_sequence"),
        stop_id=optional_text(stop, "stop_id"),
        arrival=stop_event(stop.arrival) if stop.HasField("arrival") else None,
        departure=stop_event(stop.departure) if stop.HasField("departure") else None,
        relationship=stop_relationship(
            stop.ScheduleRelationship, stop.schedule_relationship
        ),
        departure_occupancy=(
            enum_name(stop.OccupancyStatus, stop.departure_occupancy_status, None)
            if stop.HasField("departure_occupancy_status")
            else None
        ),
        predictive_carriages=tuple(
            carriage(item)
            for item in stop.Extensions[pb.carriage_seq_predictive_occupancy]
        ),
    )


def _vehicle_entity(entity: Any, pb: Any) -> VehicleRecord | None:
    if not entity.HasField("vehicle") or not entity.vehicle.HasField("trip"):
        return None
    vehicle = entity.vehicle
    service_id = optional_text(vehicle.trip, "trip_id")
    return _vehicle_record(vehicle, service_id, pb) if service_id else None


def _vehicle_record(vehicle: Any, service_id: str, pb: Any) -> VehicleRecord:
    return VehicleRecord(
        service_id=service_id,
        route_id=optional_text(vehicle.trip, "route_id"),
        start_date=optional_service_date(vehicle.trip, "start_date"),
        start_time=optional_gtfs_time(vehicle.trip, "start_time"),
        relationship=trip_relationship(
            vehicle.trip.ScheduleRelationship, vehicle.trip.schedule_relationship
        ),
        label=_vehicle_label(vehicle),
        descriptor=_vehicle_descriptor(vehicle, pb),
        position=_vehicle_position(vehicle, pb),
        current_stop_sequence=optional_scalar(vehicle, "current_stop_sequence"),
        reported_stop_id=optional_text(vehicle, "stop_id"),
        current_status=vehicle_status(
            vehicle.VehicleStopStatus, vehicle.current_status
        ),
        timestamp=optional_timestamp(vehicle, "timestamp"),
        occupancy=(
            enum_name(vehicle.OccupancyStatus, vehicle.occupancy_status, None)
            if vehicle.HasField("occupancy_status")
            else None
        ),
        carriages=tuple(carriage(item) for item in vehicle.Extensions[pb.consist]),
    )


def _vehicle_position(vehicle: Any, pb: Any) -> VehicleCoordinates | None:
    if not vehicle.HasField("position"):
        return None
    raw = vehicle.position
    direction = (
        track_direction(raw.Extensions[pb.track_direction], pb)
        if raw.HasExtension(pb.track_direction)
        else TrackDirection.UNKNOWN
    )
    return VehicleCoordinates(
        latitude=float(raw.latitude),
        longitude=float(raw.longitude),
        bearing=optional_scalar(raw, "bearing"),
        speed=optional_scalar(raw, "speed"),
        track_direction=direction,
    )


def _vehicle_label(vehicle: Any) -> str | None:
    return (
        optional_text(vehicle.vehicle, "label") if vehicle.HasField("vehicle") else None
    )


def _vehicle_descriptor(vehicle: Any, pb: Any) -> VehicleDescriptorRecord | None:
    if not vehicle.HasField("vehicle"):
        return None
    detail = vehicle.vehicle
    if not detail.HasExtension(pb.tfnsw_vehicle_descriptor):
        return None
    descriptor = detail.Extensions[pb.tfnsw_vehicle_descriptor]
    value = optional_scalar(descriptor, "wheelchair_accessible")
    wheelchair = False if value == 0 else True if value == 1 else None
    return VehicleDescriptorRecord(
        model=optional_text(descriptor, "vehicle_model"),
        air_conditioned=optional_scalar(descriptor, "air_conditioned"),
        wheelchair_accessible=wheelchair,
    )
