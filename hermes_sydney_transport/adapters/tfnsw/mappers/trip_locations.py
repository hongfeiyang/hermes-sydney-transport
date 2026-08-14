"""Pure Trip Planner location projections."""

from dataclasses import dataclass, field

from ....models.outputs import Coordinates, NearbyStop, Station, TripStop
from ..wire.trip_planner import LocationWire
from .time import sydney_time


def map_station(item: LocationWire) -> Station | None:
    if not item.id or not item.name or item.type not in {None, "stop", "platform"}:
        return None
    return Station(
        id=item.id,
        name=item.name,
        short_name=item.disassembled_name,
        parent_name=item.parent.name if item.parent else None,
        modes=list(item.modes),
        match_quality=item.match_quality or 0,
        is_best=item.is_best or False,
        coordinates=_coordinates(item),
    )


def map_trip_stop(item: LocationWire | None) -> TripStop:
    location = item or LocationWire()
    properties = location.properties
    return TripStop(
        id=location.id,
        name=location.name,
        short_name=location.disassembled_name,
        parent_id=location.parent.id if location.parent else None,
        platform=(
            properties.platform_name
            or properties.planned_platform_name
            or properties.stopping_point_planned
        ),
        departure_time_planned=sydney_time(location.departure_time_planned),
        departure_time_estimated=sydney_time(location.departure_time_estimated),
        arrival_time_planned=sydney_time(location.arrival_time_planned),
        arrival_time_estimated=sydney_time(location.arrival_time_estimated),
        wheelchair_accessible=properties.wheelchair_access,
        coordinates=_coordinates(location),
    )


@dataclass(slots=True)
class _NearbyAccumulator:
    id: str
    name: str
    distance: int | None
    coordinates: Coordinates | None
    location_types: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)

    def merge(self, item: LocationWire) -> None:
        candidate = item.properties.distance
        if candidate is not None and (
            self.distance is None or candidate < self.distance
        ):
            self.distance = candidate
            self.coordinates = _coordinates(item) or self.coordinates
        _append_unique(self.location_types, item.type, 20)
        _append_unique(self.platforms, _platform(item), 30)

    def result(self) -> NearbyStop:
        return NearbyStop(
            id=self.id,
            name=self.name,
            distance_metres=self.distance,
            coordinates=self.coordinates,
            location_types=self.location_types,
            platforms=self.platforms,
            platform_count=len(self.platforms),
        )


def map_nearby(locations: tuple[LocationWire, ...]) -> tuple[NearbyStop, ...]:
    by_id: dict[str, _NearbyAccumulator] = {}
    for item in locations[:1_000]:
        stop_id = item.properties.stop_global_id or item.id
        name = (
            item.properties.stop_name_with_place
            or item.properties.stop_name
            or item.name
        )
        if not stop_id or not name:
            continue
        accumulator = by_id.setdefault(
            stop_id,
            _NearbyAccumulator(
                stop_id, name, item.properties.distance, _coordinates(item)
            ),
        )
        accumulator.merge(item)
    return tuple(sorted(map(_NearbyAccumulator.result, by_id.values()), key=_sort_key))


def _coordinates(item: LocationWire) -> Coordinates | None:
    return (
        Coordinates(latitude=item.coord[0], longitude=item.coord[1])
        if item.coord is not None
        else None
    )


def _platform(item: LocationWire) -> str | None:
    return item.properties.stop_point_long_name or (
        item.disassembled_name if item.type == "platform" else None
    )


def _append_unique(values: list[str], value: str | None, limit: int) -> None:
    if value and value not in values and len(values) < limit:
        values.append(value)


def _sort_key(item: NearbyStop) -> tuple[bool, int, str]:
    return item.distance_metres is None, item.distance_metres or 0, item.name
