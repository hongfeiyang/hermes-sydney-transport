"""The single declarative extension registry for realtime transport modes."""

from __future__ import annotations

from dataclasses import dataclass

from ..adapters.tfnsw.catalogs.feeds import (
    BUS_FEEDS,
    FERRY_FEEDS,
    LIGHT_RAIL_FEEDS,
    METRO_FEEDS,
    TRAIN_FEEDS,
    ModeFeeds,
)
from ..application.capabilities import Capability
from ..application.realtime.mode_policy import ModePolicy
from ..ports.realtime import TransportMode


@dataclass(frozen=True, slots=True)
class ModeSpec:
    mode: TransportMode
    cache_slug: str
    service_status: Capability
    vehicle_position: Capability
    alert_sources: tuple[str, ...]
    feeds: ModeFeeds
    policy: ModePolicy


MODE_SPECS = (
    ModeSpec(
        TransportMode.TRAIN,
        "train",
        Capability.TRAIN_SERVICE_STATUS,
        Capability.TRAIN_VEHICLE_POSITION,
        ("sydneytrains", "nswtrains"),
        TRAIN_FEEDS,
        ModePolicy(
            mode=TransportMode.TRAIN,
            supports_trip_delay=True,
            supports_update_bundles=True,
            supports_carriage_occupancy=True,
            occupancy_note=(
                "Passenger-load data is optional and is mainly available for supported "
                "Waratah A/B sets. Missing occupancy means unreported, not empty."
            ),
            position_coverage_note=(
                "Vehicle positions have incomplete network and fleet coverage. "
                "Coordinates are reported observations, not a guarantee that every "
                "active train is represented."
            ),
        ),
    ),
    ModeSpec(
        TransportMode.BUS,
        "bus",
        Capability.BUS_SERVICE_STATUS,
        Capability.BUS_VEHICLE_POSITION,
        ("buses", "regionbuses"),
        BUS_FEEDS,
        ModePolicy(
            mode=TransportMode.BUS,
            supports_trip_delay=False,
            supports_update_bundles=False,
            supports_carriage_occupancy=False,
            occupancy_note=(
                "Bus passenger-load data is optional and only available for some "
                "operators and vehicles. Missing occupancy means unreported, not empty."
            ),
            position_coverage_note=(
                "Bus vehicle positions have incomplete operator and fleet coverage. "
                "Coordinates are reported observations, not proof that every active "
                "bus is represented."
            ),
        ),
    ),
    ModeSpec(
        TransportMode.METRO,
        "metro",
        Capability.METRO_SERVICE_STATUS,
        Capability.METRO_VEHICLE_POSITION,
        ("metro",),
        METRO_FEEDS,
        ModePolicy(
            mode=TransportMode.METRO,
            supports_trip_delay=False,
            supports_update_bundles=False,
            supports_carriage_occupancy=False,
            occupancy_note=(
                "Metro passenger-load data is optional. Missing occupancy means "
                "unreported, not empty."
            ),
            position_coverage_note=(
                "Metro vehicle positions can be unavailable or incomplete. Coordinates "
                "are reported observations, not a guarantee that every active metro "
                "service is represented."
            ),
        ),
    ),
    ModeSpec(
        TransportMode.LIGHT_RAIL,
        "light-rail",
        Capability.LIGHT_RAIL_SERVICE_STATUS,
        Capability.LIGHT_RAIL_VEHICLE_POSITION,
        ("lightrail",),
        LIGHT_RAIL_FEEDS,
        ModePolicy(
            mode=TransportMode.LIGHT_RAIL,
            supports_trip_delay=False,
            supports_update_bundles=False,
            supports_carriage_occupancy=False,
            occupancy_note=(
                "Light rail passenger-load data is optional. Missing occupancy means "
                "unreported, not empty."
            ),
            position_coverage_note=(
                "Light rail vehicle positions can be unavailable or incomplete. "
                "Coordinates are reported observations, not a guarantee that every "
                "active light rail service is represented."
            ),
        ),
    ),
    ModeSpec(
        TransportMode.FERRY,
        "ferry",
        Capability.FERRY_SERVICE_STATUS,
        Capability.FERRY_VEHICLE_POSITION,
        ("ferries",),
        FERRY_FEEDS,
        ModePolicy(
            mode=TransportMode.FERRY,
            supports_trip_delay=False,
            supports_update_bundles=False,
            supports_carriage_occupancy=False,
            occupancy_note=(
                "Ferry passenger-load data is optional. Missing occupancy means "
                "unreported, not empty."
            ),
            position_coverage_note=(
                "Ferry vehicle positions can be unavailable or incomplete. Coordinates "
                "are reported observations, not a guarantee that every active ferry "
                "service is represented."
            ),
        ),
    ),
)
