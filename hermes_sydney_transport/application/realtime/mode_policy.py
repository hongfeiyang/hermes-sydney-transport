"""Data-only capability differences for one realtime pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from ...ports.realtime import TransportMode


@dataclass(frozen=True, slots=True)
class ModePolicy:
    mode: TransportMode
    supports_trip_delay: bool
    supports_update_bundles: bool
    supports_carriage_occupancy: bool
    occupancy_note: str
    position_coverage_note: str


TRAIN_POLICY = ModePolicy(
    mode=TransportMode.TRAIN,
    supports_trip_delay=True,
    supports_update_bundles=True,
    supports_carriage_occupancy=True,
    occupancy_note=(
        "Passenger-load data is optional and is mainly available for supported "
        "Waratah A/B sets. Missing occupancy means unreported, not empty."
    ),
    position_coverage_note=(
        "Vehicle positions have incomplete network and fleet coverage. Coordinates "
        "are reported observations, not a guarantee that every active train is represented."
    ),
)

BUS_POLICY = ModePolicy(
    mode=TransportMode.BUS,
    supports_trip_delay=False,
    supports_update_bundles=False,
    supports_carriage_occupancy=False,
    occupancy_note=(
        "Bus passenger-load data is optional and only available for some operators "
        "and vehicles. Missing occupancy means unreported, not empty."
    ),
    position_coverage_note=(
        "Bus vehicle positions have incomplete operator and fleet coverage. Coordinates "
        "are reported observations, not proof that every active bus is represented."
    ),
)

METRO_POLICY = ModePolicy(
    mode=TransportMode.METRO,
    supports_trip_delay=False,
    supports_update_bundles=False,
    supports_carriage_occupancy=False,
    occupancy_note=(
        "Metro passenger-load data is optional. Missing occupancy means unreported, "
        "not empty."
    ),
    position_coverage_note=(
        "Metro vehicle positions can be unavailable or incomplete. Coordinates are "
        "reported observations, not a guarantee that every active metro service is represented."
    ),
)

LIGHT_RAIL_POLICY = ModePolicy(
    mode=TransportMode.LIGHT_RAIL,
    supports_trip_delay=False,
    supports_update_bundles=False,
    supports_carriage_occupancy=False,
    occupancy_note=(
        "Light rail passenger-load data is optional. Missing occupancy means "
        "unreported, not empty."
    ),
    position_coverage_note=(
        "Light rail vehicle positions can be unavailable or incomplete. Coordinates "
        "are reported observations, not a guarantee that every active light rail service is represented."
    ),
)

FERRY_POLICY = ModePolicy(
    mode=TransportMode.FERRY,
    supports_trip_delay=False,
    supports_update_bundles=False,
    supports_carriage_occupancy=False,
    occupancy_note=(
        "Ferry passenger-load data is optional. Missing occupancy means unreported, "
        "not empty."
    ),
    position_coverage_note=(
        "Ferry vehicle positions can be unavailable or incomplete. Coordinates are "
        "reported observations, not a guarantee that every active ferry service is represented."
    ),
)

MODE_POLICIES = {
    policy.mode: policy
    for policy in (
        TRAIN_POLICY,
        BUS_POLICY,
        METRO_POLICY,
        LIGHT_RAIL_POLICY,
        FERRY_POLICY,
    )
}
