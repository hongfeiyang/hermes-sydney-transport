"""Pure vehicle stop-context and occupancy projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ...models.outputs import (
    Coordinates,
    PositionReport,
    VehicleDetails,
    VehicleStopContext,
)
from ...ports.realtime import (
    StaticStopReference,
    StaticTrip,
    VehicleRecord,
    VehicleStatus,
)
from .common import stop_reference


@dataclass(frozen=True, slots=True)
class VehicleProjection:
    details: VehicleDetails | None
    position: PositionReport | None
    stop_context: VehicleStopContext
    observation_time: datetime | None
    used_inference: bool
    warnings: tuple[str, ...]


def collect_vehicle_stop_ids(
    vehicle: VehicleRecord | None, static_trip: StaticTrip | None
) -> tuple[str, ...]:
    ids = [row.stop_id for row in static_trip.stop_times] if static_trip else []
    if vehicle and vehicle.reported_stop_id:
        ids.append(vehicle.reported_stop_id)
    return tuple(dict.fromkeys(ids))


def vehicle_stop_context(
    vehicle: VehicleRecord,
    static_trip: StaticTrip | None,
    references: Mapping[str, StaticStopReference],
) -> VehicleStopContext:
    rows = static_trip.stop_times if static_trip else ()
    sequence = vehicle.current_stop_sequence
    index = (
        next((i for i, row in enumerate(rows) if row.sequence == sequence), None)
        if sequence is not None
        else None
    )
    if index is not None:
        target = stop_reference(rows[index].stop_id, references)
        previous = (
            stop_reference(rows[index - 1].stop_id, references) if index > 0 else None
        )
        following = (
            stop_reference(rows[index + 1].stop_id, references)
            if index + 1 < len(rows)
            else None
        )
        if vehicle.current_status is VehicleStatus.STOPPED_AT:
            return VehicleStopContext(
                at_stop=target,
                last_passed_stop=previous,
                target_stop=following,
                inferred=True,
            )
        return VehicleStopContext(
            at_stop=None,
            last_passed_stop=previous,
            target_stop=target,
            inferred=True,
        )
    if vehicle.reported_stop_id:
        reported = stop_reference(vehicle.reported_stop_id, references)
        if vehicle.current_status is VehicleStatus.STOPPED_AT:
            return VehicleStopContext(
                at_stop=reported,
                last_passed_stop=None,
                target_stop=None,
                inferred=False,
            )
        return VehicleStopContext(
            at_stop=None,
            last_passed_stop=None,
            target_stop=reported,
            inferred=False,
        )
    return empty_stop_context()


def project_vehicle(
    vehicle: VehicleRecord | None,
    static_trip: StaticTrip | None,
    references: Mapping[str, StaticStopReference],
    feed_timestamp: datetime,
) -> VehicleProjection:
    if vehicle is None:
        return VehicleProjection(
            details=None,
            position=None,
            stop_context=empty_stop_context(),
            observation_time=None,
            used_inference=False,
            warnings=(
                "No matching vehicle entity is currently published; coverage is incomplete.",
            ),
        )
    position, observed, inferred, warning = _position(vehicle, feed_timestamp)
    warnings: tuple[str, ...] = (warning,) if warning else ()
    if position is None:
        warnings += ("The matching vehicle entity did not contain coordinates.",)
    context = vehicle_stop_context(vehicle, static_trip, references)
    return VehicleProjection(
        details=_vehicle_details(vehicle),
        position=position,
        stop_context=context,
        observation_time=observed,
        used_inference=inferred or context.inferred,
        warnings=warnings,
    )


def empty_stop_context() -> VehicleStopContext:
    return VehicleStopContext(
        at_stop=None,
        last_passed_stop=None,
        target_stop=None,
        inferred=False,
    )


def _vehicle_details(vehicle: VehicleRecord) -> VehicleDetails:
    descriptor = vehicle.descriptor
    if descriptor is None:
        return VehicleDetails(
            label=vehicle.label,
            model=None,
            air_conditioned=None,
            wheelchair_accessible=None,
        )
    return VehicleDetails(
        label=vehicle.label,
        model=descriptor.model,
        air_conditioned=descriptor.air_conditioned,
        wheelchair_accessible=descriptor.wheelchair_accessible,
    )


def _position(
    vehicle: VehicleRecord, feed_timestamp: datetime
) -> tuple[PositionReport | None, datetime | None, bool, str | None]:
    raw = vehicle.position
    if raw is None:
        return None, vehicle.timestamp, False, None
    observed = vehicle.timestamp or feed_timestamp
    inferred = vehicle.timestamp is None
    warning = (
        "Vehicle entity omitted its own timestamp; feed time was used."
        if inferred
        else None
    )
    return (
        PositionReport(
            coordinates=Coordinates(latitude=raw.latitude, longitude=raw.longitude),
            bearing_degrees=raw.bearing,
            speed_metres_per_second=raw.speed,
            track_direction=raw.track_direction.value,
            reported_at=observed,
        ),
        observed,
        inferred,
        warning,
    )
