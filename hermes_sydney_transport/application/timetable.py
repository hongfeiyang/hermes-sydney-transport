"""Route timetable policy over the indexed TfNSW Complete GTFS bundle."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from ..models.errors import DomainError
from ..models.metadata import ATTRIBUTION
from ..models.static_inputs import RouteTimetableInput
from ..models.static_outputs import RouteTimetableResult
from ..ports.clock import Clock
from ..ports.timetable import (
    RouteTimetablePort,
    TimetableStopRecord,
    TimetableTripRecord,
)

_SYDNEY = ZoneInfo("Australia/Sydney")
_SOURCE = "TfNSW Complete GTFS"
_IDENTIFIER_LIMITATION = (
    "Route, trip, and stop IDs are from the Complete GTFS namespace and must not be "
    "used as identifiers for mode-specific realtime feeds."
)
_SCHEDULE_LIMITATION = (
    "Times are published static schedule data, not live predictions or evidence that "
    "a service is operating. GTFS times after 24:00 belong to the requested service "
    "date and are returned on the following civil day."
)


class GetRouteTimetable:
    def __init__(self, port: RouteTimetablePort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: RouteTimetableInput) -> RouteTimetableResult:
        now = self._clock.now()
        service_date = request.service_date or now.astimezone(_SYDNEY).date()
        snapshot = self._port.get_route_timetable(request, service_date)
        if snapshot.route is None:
            raise DomainError(
                "service_not_found",
                "No exact route_id match was found in TfNSW Complete GTFS.",
            )
        limitations = [_IDENTIFIER_LIMITATION, _SCHEDULE_LIMITATION]
        if snapshot.cache_stale:
            limitations.append(
                "The latest Complete GTFS refresh failed, so the last valid cache "
                "was used."
            )
        if any(trip.stop_times_truncated for trip in snapshot.trips):
            limitations.append(
                "At least one trip exceeded the per-trip stop-time limit and was "
                "truncated."
            )
        route = snapshot.route
        trips = [_trip_output(trip) for trip in snapshot.trips]
        return RouteTimetableResult.model_validate(
            {
                "fetched_at": now,
                "source": _SOURCE,
                "attribution": ATTRIBUTION,
                "identifier_namespace": "complete_gtfs",
                "identifiers_match_realtime_feeds": False,
                "route": {
                    "id": route.id,
                    "agency_id": route.agency_id,
                    "short_name": route.short_name,
                    "long_name": route.long_name,
                    "description": route.description,
                    "route_type": route.route_type,
                },
                "service_date": snapshot.service_date,
                "direction_id": request.direction_id,
                "stop_id": request.stop_id,
                "trips": trips,
                "count": len(trips),
                "static_source_updated_at": snapshot.source_updated_at,
                "static_cache_stale": snapshot.cache_stale,
                "limitations": limitations,
            }
        )


def _trip_output(item: TimetableTripRecord) -> dict[str, object]:
    return {
        "complete_gtfs_trip_id": item.trip_id,
        "headsign": item.headsign,
        "direction_id": item.direction_id,
        "wheelchair_accessibility": item.wheelchair_accessibility,
        "first_departure": item.first_departure,
        "last_arrival": item.last_arrival,
        "stop_times": [_stop_output(stop) for stop in item.stop_times],
        "stop_count": len(item.stop_times),
        "stop_times_truncated": item.stop_times_truncated,
    }


def _stop_output(item: TimetableStopRecord) -> dict[str, object]:
    return {
        "stop_id": item.stop_id,
        "stop_name": item.stop_name,
        "sequence": item.sequence,
        "arrival": item.arrival,
        "departure": item.departure,
        "pickup_type": item.pickup_type,
        "drop_off_type": item.drop_off_type,
    }
