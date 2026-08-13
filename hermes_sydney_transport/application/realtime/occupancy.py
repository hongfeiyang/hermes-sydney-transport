"""Pure optional vehicle and carriage occupancy projection."""

from __future__ import annotations

from typing import Literal, cast

from ...models.outputs import CarriageOccupancy, OccupancyLevel, OccupancyReport
from ...ports.realtime import VehicleRecord
from .mode_policy import ModePolicy

_OCCUPANCY_LEVELS = {
    "empty",
    "many_seats_available",
    "few_seats_available",
    "standing_room_only",
    "crushed_standing_room_only",
    "full",
    "not_accepting_passengers",
    "unknown",
}


def occupancy_report(
    vehicle: VehicleRecord | None, policy: ModePolicy
) -> OccupancyReport:
    if vehicle is None:
        return OccupancyReport(
            reported=False,
            level=None,
            source="none",
            carriages=[],
            coverage_note=policy.occupancy_note,
        )
    carriages = _carriages(vehicle, policy)
    level = _level(vehicle.occupancy)
    source: Literal["none", "vehicle", "carriage", "vehicle_and_carriage"] = (
        "vehicle_and_carriage"
        if level is not None and carriages
        else "carriage"
        if carriages
        else "vehicle"
        if level is not None
        else "none"
    )
    return OccupancyReport(
        reported=source != "none",
        level=level,
        source=source,
        carriages=carriages,
        coverage_note=policy.occupancy_note,
    )


def _carriages(vehicle: VehicleRecord, policy: ModePolicy) -> list[CarriageOccupancy]:
    if not policy.supports_carriage_occupancy:
        return []
    return [
        CarriageOccupancy(
            name=item.name,
            position_in_consist=item.position_in_consist,
            occupancy=_level(item.occupancy),
            quiet_carriage=item.quiet_carriage,
            toilet=cast(
                Literal["none", "normal", "accessible", "unknown"] | None,
                item.toilet,
            ),
            luggage_rack=item.luggage_rack,
        )
        for item in vehicle.carriages
        if item.occupancy is not None
    ]


def _level(value: str | None) -> OccupancyLevel | None:
    if value is None:
        return None
    return cast(OccupancyLevel, value) if value in _OCCUPANCY_LEVELS else "unknown"
