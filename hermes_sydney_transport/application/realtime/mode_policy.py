"""Data-only train and bus capability differences for one realtime pipeline."""

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
