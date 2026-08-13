"""Linear static/realtime stop alignment and prediction projection."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from ...models.outputs import StopPrediction
from ...ports.realtime import (
    GtfsTime,
    StaticStopReference,
    StaticStopTime,
    StaticTrip,
    StopEvent,
    StopRelationship,
    TripStopUpdate,
    TripUpdateRecord,
)
from .common import SYDNEY_TZ, stop_reference
from .mode_policy import ModePolicy


class PredictionSource(StrEnum):
    UNAVAILABLE = "unavailable"
    SCHEDULE = "schedule"
    TRIP_DELAY = "trip_delay"
    STOP_DELAY = "stop_delay"
    ABSOLUTE_TIME = "absolute_time"


@dataclass(frozen=True, slots=True)
class AlignedStop:
    realtime: TripStopUpdate
    static: StaticStopTime | None


@dataclass(frozen=True, slots=True)
class Timeline:
    stops: tuple[StopPrediction, ...]
    used_prediction: bool
    used_inference: bool


def collect_stop_ids(
    update: TripUpdateRecord, static_trip: StaticTrip | None
) -> tuple[str, ...]:
    ids = [row.stop_id for row in update.stop_updates if row.stop_id]
    if static_trip:
        ids.extend(row.stop_id for row in static_trip.stop_times)
    return tuple(dict.fromkeys(ids))


def build_timeline(
    update: TripUpdateRecord,
    static_trip: StaticTrip | None,
    references: Mapping[str, StaticStopReference],
    service_date: date,
    policy: ModePolicy,
) -> Timeline:
    aligned, alignment_inferred = align_stops(update, static_trip)
    trip_delay = update.delay if policy.supports_trip_delay else None
    stops = tuple(
        _prediction(row, references, service_date, trip_delay) for row in aligned
    )
    used_prediction = any(
        stop.prediction_source in {"absolute_time", "stop_delay", "trip_delay"}
        for stop in stops
    )
    return Timeline(
        stops=stops,
        used_prediction=used_prediction,
        used_inference=alignment_inferred,
    )


def align_stops(
    update: TripUpdateRecord, static_trip: StaticTrip | None
) -> tuple[tuple[AlignedStop, ...], bool]:
    static_rows = static_trip.stop_times if static_trip else ()
    realtime_rows = update.stop_updates or tuple(
        _scheduled_row(row) for row in static_rows
    )
    by_sequence = {row.sequence: row for row in static_rows}
    by_stop: dict[str, deque[tuple[int, StaticStopTime]]] = defaultdict(deque)
    for index, row in enumerate(static_rows):
        by_stop[row.stop_id].append((index, row))
    equal_lengths = len(realtime_rows) == len(static_rows)
    cursor = 0
    inferred = not update.stop_updates and bool(static_rows)
    aligned: list[AlignedStop] = []
    for index, realtime in enumerate(realtime_rows[:300]):
        static, guessed, cursor = _find_static_row(
            realtime,
            index,
            cursor,
            static_rows,
            by_sequence,
            by_stop,
            equal_lengths,
        )
        inferred = inferred or guessed
        aligned.append(AlignedStop(realtime=realtime, static=static))
    return tuple(aligned), inferred


def _find_static_row(
    realtime: TripStopUpdate,
    index: int,
    cursor: int,
    static_rows: tuple[StaticStopTime, ...],
    by_sequence: Mapping[int, StaticStopTime],
    by_stop: Mapping[str, deque[tuple[int, StaticStopTime]]],
    equal_lengths: bool,
) -> tuple[StaticStopTime | None, bool, int]:
    if realtime.sequence is not None and realtime.sequence in by_sequence:
        return by_sequence[realtime.sequence], False, cursor
    if equal_lengths and index < len(static_rows):
        return static_rows[index], True, max(cursor, index + 1)
    candidates = by_stop.get(realtime.stop_id or "")
    if not candidates:
        return None, False, cursor
    while candidates and candidates[0][0] < cursor:
        candidates.popleft()
    if not candidates:
        return None, False, cursor
    matched_index, matched = candidates.popleft()
    return matched, True, matched_index + 1


def _scheduled_row(row: StaticStopTime) -> TripStopUpdate:
    return TripStopUpdate(
        sequence=row.sequence,
        stop_id=row.stop_id,
        arrival=None,
        departure=None,
        relationship=StopRelationship.SCHEDULED,
        departure_occupancy=None,
        predictive_carriages=(),
    )


def _prediction(
    aligned: AlignedStop,
    references: Mapping[str, StaticStopReference],
    service_date: date,
    trip_delay: timedelta | None,
) -> StopPrediction:
    realtime, static = aligned.realtime, aligned.static
    current_id = realtime.stop_id or (static.stop_id if static else None)
    if current_id is None:
        raise ValueError("aligned stop has no current identity")
    planned_id = static.stop_id if static else None
    planned = stop_reference(planned_id, references) if planned_id else None
    current = stop_reference(current_id, references)
    arrival_planned = _scheduled(static.arrival if static else None, service_date)
    departure_planned = _scheduled(static.departure if static else None, service_date)
    arrival, arrival_source = predict_event(
        realtime.arrival, arrival_planned, trip_delay
    )
    departure, departure_source = predict_event(
        realtime.departure, departure_planned, trip_delay
    )
    source = stronger_source(arrival_source, departure_source)
    return StopPrediction(
        sequence=realtime.sequence
        if realtime.sequence is not None
        else static.sequence
        if static
        else None,
        planned_stop=planned,
        current_stop=current,
        arrival_planned=arrival_planned,
        arrival_predicted=arrival,
        departure_planned=departure_planned,
        departure_predicted=departure,
        prediction_source=source.value,
        schedule_relationship=realtime.relationship.value,
        skipped=realtime.relationship is StopRelationship.SKIPPED,
        stop_changed=planned is not None and planned.id != current.id,
    )


def predict_event(
    event: StopEvent | None,
    planned: datetime | None,
    trip_delay: timedelta | None,
) -> tuple[datetime | None, PredictionSource]:
    if event and event.time:
        return event.time, PredictionSource.ABSOLUTE_TIME
    if planned is not None and event and event.delay is not None:
        return planned + event.delay, PredictionSource.STOP_DELAY
    if planned is not None and trip_delay is not None:
        return planned + trip_delay, PredictionSource.TRIP_DELAY
    if planned is not None:
        return planned, PredictionSource.SCHEDULE
    return None, PredictionSource.UNAVAILABLE


def stronger_source(
    first: PredictionSource, second: PredictionSource
) -> PredictionSource:
    rank = {
        PredictionSource.UNAVAILABLE: 0,
        PredictionSource.SCHEDULE: 1,
        PredictionSource.TRIP_DELAY: 2,
        PredictionSource.STOP_DELAY: 3,
        PredictionSource.ABSOLUTE_TIME: 4,
    }
    return max((first, second), key=rank.__getitem__)


def _scheduled(value: GtfsTime | None, service_date: date) -> datetime | None:
    return value.at(service_date, SYDNEY_TZ) if value else None
