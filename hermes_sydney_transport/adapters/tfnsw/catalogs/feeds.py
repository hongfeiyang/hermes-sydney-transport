"""Immutable endpoint catalog for TfNSW GTFS and GTFS-Realtime feeds."""

from __future__ import annotations

from dataclasses import dataclass

from ..platform import EndpointSpec


@dataclass(frozen=True, slots=True)
class ModeFeeds:
    """All upstream feeds required by one declarative transport-mode row."""

    alerts: tuple[EndpointSpec, ...]
    trip_updates: tuple[EndpointSpec, ...]
    vehicle_positions: tuple[EndpointSpec, ...]
    static_schedule: tuple[EndpointSpec, ...]

    def groups(self) -> tuple[tuple[EndpointSpec, ...], ...]:
        return (
            self.alerts,
            self.trip_updates,
            self.vehicle_positions,
            self.static_schedule,
        )


_PROTOBUF_TYPES = frozenset(
    {
        "application/octet-stream",
        "application/protobuf",
        "application/x-google-protobuf",
    }
)
_ZIP_TYPES = frozenset(
    {"application/octet-stream", "application/x-zip-compressed", "application/zip"}
)


def _protobuf(id: str, url: str, max_megabytes: int) -> EndpointSpec:
    return EndpointSpec(
        id=id,
        url=url,
        accept="application/x-google-protobuf",
        content_types=_PROTOBUF_TYPES,
        max_bytes=max_megabytes * 1_024 * 1_024,
        timeout_seconds=30.0,
    )


def _zip(id: str, url: str, max_megabytes: int) -> EndpointSpec:
    return EndpointSpec(
        id=id,
        url=url,
        accept="application/zip",
        content_types=_ZIP_TYPES,
        max_bytes=max_megabytes * 1_024 * 1_024,
        timeout_seconds=120.0,
        allow_not_modified=True,
    )


TRAIN_FEEDS = ModeFeeds(
    alerts=(
        _protobuf(
            "train_alerts_sydney",
            "https://api.transport.nsw.gov.au/v2/gtfs/alerts/sydneytrains",
            8,
        ),
        _protobuf(
            "train_alerts_nsw",
            "https://api.transport.nsw.gov.au/v2/gtfs/alerts/nswtrains",
            8,
        ),
    ),
    trip_updates=(
        _protobuf(
            "train_updates",
            "https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains",
            8,
        ),
    ),
    vehicle_positions=(
        _protobuf(
            "train_vehicles",
            "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/sydneytrains",
            8,
        ),
    ),
    static_schedule=(
        _zip(
            "train_schedule",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/sydneytrains",
            32,
        ),
    ),
)

BUS_FEEDS = ModeFeeds(
    alerts=(
        _protobuf(
            "bus_alerts_sydney",
            "https://api.transport.nsw.gov.au/v2/gtfs/alerts/buses",
            32,
        ),
        _protobuf(
            "bus_alerts_region",
            "https://api.transport.nsw.gov.au/v2/gtfs/alerts/regionbuses",
            16,
        ),
    ),
    trip_updates=(
        _protobuf(
            "bus_updates",
            "https://api.transport.nsw.gov.au/v1/gtfs/realtime/buses",
            32,
        ),
    ),
    vehicle_positions=(
        _protobuf(
            "bus_vehicles",
            "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/buses",
            32,
        ),
    ),
    static_schedule=(
        _zip(
            "bus_schedule",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/buses",
            128,
        ),
    ),
)

METRO_FEEDS = ModeFeeds(
    alerts=(
        _protobuf(
            "metro_alerts",
            "https://api.transport.nsw.gov.au/v2/gtfs/alerts/metro",
            8,
        ),
    ),
    trip_updates=(
        _protobuf(
            "metro_updates",
            "https://api.transport.nsw.gov.au/v2/gtfs/realtime/metro",
            8,
        ),
    ),
    vehicle_positions=(
        _protobuf(
            "metro_vehicles",
            "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/metro",
            8,
        ),
    ),
    static_schedule=(
        _zip(
            "metro_schedule",
            "https://api.transport.nsw.gov.au/v2/gtfs/schedule/metro",
            32,
        ),
    ),
)

LIGHT_RAIL_FEEDS = ModeFeeds(
    alerts=(
        _protobuf(
            "light_rail_alerts",
            "https://api.transport.nsw.gov.au/v2/gtfs/alerts/lightrail",
            8,
        ),
    ),
    trip_updates=(
        _protobuf(
            "light_rail_updates_innerwest",
            "https://api.transport.nsw.gov.au/v2/gtfs/realtime/lightrail/innerwest",
            8,
        ),
        _protobuf(
            "light_rail_updates_cse",
            "https://api.transport.nsw.gov.au/v1/gtfs/realtime/lightrail/cbdandsoutheast",
            8,
        ),
        _protobuf(
            "light_rail_updates_newcastle",
            "https://api.transport.nsw.gov.au/v1/gtfs/realtime/lightrail/newcastle",
            8,
        ),
        _protobuf(
            "light_rail_updates_parramatta",
            "https://api.transport.nsw.gov.au/v1/gtfs/realtime/lightrail/parramatta",
            8,
        ),
    ),
    vehicle_positions=(
        _protobuf(
            "light_rail_vehicles_cse",
            "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/cbdandsoutheast",
            8,
        ),
        _protobuf(
            "light_rail_vehicles_innerwest",
            "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/innerwest",
            8,
        ),
        _protobuf(
            "light_rail_vehicles_newcastle",
            "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/newcastle",
            8,
        ),
        _protobuf(
            "light_rail_vehicles_parramatta",
            "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/lightrail/parramatta",
            8,
        ),
    ),
    static_schedule=(
        _zip(
            "light_rail_schedule_cse",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/cbdandsoutheast",
            16,
        ),
        _zip(
            "light_rail_schedule_innerwest",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/innerwest",
            16,
        ),
        _zip(
            "light_rail_schedule_newcastle",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/newcastle",
            16,
        ),
        _zip(
            "light_rail_schedule_parramatta",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/lightrail/parramatta",
            16,
        ),
    ),
)

FERRY_FEEDS = ModeFeeds(
    alerts=(
        _protobuf(
            "ferry_alerts",
            "https://api.transport.nsw.gov.au/v2/gtfs/alerts/ferries",
            8,
        ),
    ),
    trip_updates=(
        _protobuf(
            "ferry_updates_sydney",
            "https://api.transport.nsw.gov.au/v1/gtfs/realtime/ferries/sydneyferries",
            8,
        ),
        _protobuf(
            "ferry_updates_mff",
            "https://api.transport.nsw.gov.au/v1/gtfs/realtime/ferries/MFF",
            8,
        ),
    ),
    vehicle_positions=(
        _protobuf(
            "ferry_vehicles_sydney",
            "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/ferries/sydneyferries",
            8,
        ),
        _protobuf(
            "ferry_vehicles_mff",
            "https://api.transport.nsw.gov.au/v1/gtfs/vehiclepos/ferries/MFF",
            8,
        ),
    ),
    static_schedule=(
        _zip(
            "ferry_schedule_sydney",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/ferries/sydneyferries",
            16,
        ),
        _zip(
            "ferry_schedule_mff",
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/ferries/MFF",
            16,
        ),
    ),
)
