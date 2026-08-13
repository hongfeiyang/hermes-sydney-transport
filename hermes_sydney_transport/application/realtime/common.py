"""Shared typed time, metadata, and static-schedule operations."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ...models.errors import DomainError
from ...models.outputs import RealtimeStop, ServiceDescription
from ...ports.realtime import (
    GtfsTime,
    StaticSchedulePort,
    StaticStopReference,
    StaticTrip,
    TripRelationship,
)
from .mode_policy import ModePolicy

SYDNEY_TZ = ZoneInfo("Australia/Sydney")
STALE_AFTER_SECONDS = 120
VERY_STALE_AFTER_SECONDS = 300


def sydney_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SYDNEY_TZ)
    return value.astimezone(SYDNEY_TZ)


def age_seconds(now: datetime, observed: datetime | None) -> int | None:
    if observed is None:
        return None
    return max(0, int((now.astimezone(UTC) - observed.astimezone(UTC)).total_seconds()))


def choose_service_date(
    realtime_date: date | None,
    static_trip: StaticTrip | None,
    reference: datetime,
) -> date:
    if realtime_date is not None:
        return realtime_date
    local_reference = sydney_time(reference)
    rows = static_trip.stop_times if static_trip else ()
    times = tuple(
        value
        for row in rows
        for value in (row.arrival, row.departure)
        if value is not None
    )
    if not times:
        return local_reference.date()
    candidates = tuple(
        local_reference.date() + timedelta(days=offset) for offset in (-1, 0, 1)
    )

    def distance(candidate: date) -> float:
        start = times[0].at(candidate, SYDNEY_TZ)
        end = times[-1].at(candidate, SYDNEY_TZ)
        if start <= local_reference <= end:
            return 0.0
        return min(
            abs((local_reference - start).total_seconds()),
            abs((local_reference - end).total_seconds()),
        )

    return min(candidates, key=distance)


def load_static_trip(
    repository: StaticSchedulePort, service_id: str, warnings: list[str]
) -> StaticTrip | None:
    try:
        trip = repository.get_trip(service_id)
    except DomainError as exc:
        if exc.code not in {
            "static_data_unavailable",
            "static_data_invalid",
            "realtime_feed_unavailable",
            "response_too_large",
        }:
            raise
        warnings.append(f"Static GTFS join unavailable: {exc.message}")
        return None
    if trip is None:
        warnings.append(
            "Service was not found in static GTFS; it may be added or non-timetabled."
        )
    return trip


def load_stop_references(
    repository: StaticSchedulePort,
    stop_ids: Collection[str],
) -> Mapping[str, StaticStopReference]:
    try:
        return repository.get_stop_references(stop_ids)
    except DomainError:
        return {}


def stop_reference(
    stop_id: str, references: Mapping[str, StaticStopReference]
) -> RealtimeStop:
    record = references.get(stop_id)
    return RealtimeStop(
        id=stop_id,
        name=record.name if record else None,
        parent_station_id=record.parent_station_id if record else None,
        parent_station_name=record.parent_station_name if record else None,
        platform=record.platform if record else None,
    )


def service_description(
    *,
    service_id: str,
    route_id: str | None,
    start_time: GtfsTime | None,
    relationship: TripRelationship,
    static_trip: StaticTrip | None,
    service_date: date,
    policy: ModePolicy,
) -> ServiceDescription:
    first_departure = (
        static_trip.stop_times[0].departure
        if static_trip and static_trip.stop_times
        else None
    )
    effective_start = start_time or first_departure
    return ServiceDescription(
        mode=policy.mode.value,
        service_id=service_id,
        route_id=route_id or (static_trip.route_id if static_trip else None),
        agency_id=static_trip.agency_id if static_trip else None,
        route_type=static_trip.route_type if static_trip else None,
        route_short_name=static_trip.route_short_name if static_trip else None,
        route_long_name=static_trip.route_long_name if static_trip else None,
        headsign=static_trip.headsign if static_trip else None,
        start_date=service_date.isoformat(),
        start_time=effective_start.as_text() if effective_start else None,
        schedule_relationship=relationship.value,
    )
