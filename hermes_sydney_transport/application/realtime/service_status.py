"""Service-status use case; orchestration only, with policies delegated."""

from __future__ import annotations

from datetime import datetime

from ...models.inputs import RealtimeServiceInput
from ...models.metadata import ATTRIBUTION
from ...models.outputs import (
    RealtimeDataQuality,
    ServiceStatusResult,
    StopChange,
    StopPrediction,
)
from ...ports.clock import Clock
from ...ports.realtime import RealtimeRepository, StaticSchedulePort
from ...ports.trip_planner import TripPlannerPort
from .cancellation import decide_cancellation, require_update
from .common import (
    STALE_AFTER_SECONDS,
    age_seconds,
    choose_service_date,
    load_static_trip,
    load_stop_references,
    service_description,
    sydney_time,
)
from .confidence import confidence
from .mode_policy import ModePolicy
from .progress import locate_progress, service_state
from .resolution import ServiceResolver
from .timeline import build_timeline, collect_stop_ids

_SOURCE = "TfNSW GTFS-Realtime Trip Updates v2"


class GetServiceStatus:
    def __init__(
        self,
        realtime: RealtimeRepository,
        trip_planner: TripPlannerPort,
        static_schedule: StaticSchedulePort,
        clock: Clock,
        policy: ModePolicy,
    ) -> None:
        self._realtime = realtime
        self._static = static_schedule
        self._clock = clock
        self._policy = policy
        self._resolver = ServiceResolver(trip_planner, clock, policy)

    def execute(self, request: RealtimeServiceInput) -> ServiceStatusResult:
        query = self._resolver.resolve(request)
        snapshot = self._realtime.service_snapshot(query.resolved_service_id)
        update = require_update(
            snapshot.update, snapshot.cancellation_bundles, self._policy
        )
        decision = decide_cancellation(
            update, snapshot.cancellation_bundles, self._policy
        )
        warnings = list(decision.warnings)
        static_trip = load_static_trip(self._static, update.service_id, warnings)
        now = sydney_time(self._clock.now())
        feed_age = age_seconds(now, snapshot.feed_timestamp) or 0
        observation_age = age_seconds(now, update.timestamp)
        observation_time = (
            min(snapshot.feed_timestamp, update.timestamp)
            if update.timestamp
            else snapshot.feed_timestamp
        )
        service_date = choose_service_date(
            update.start_date,
            static_trip,
            request.at or snapshot.feed_timestamp,
        )
        stop_ids = collect_stop_ids(update, static_trip)
        references = load_stop_references(self._static, stop_ids)
        timeline = build_timeline(
            update, static_trip, references, service_date, self._policy
        )
        last, next_stop = _progress(
            timeline.stops, observation_time, decision.cancelled
        )
        inferred_schedule = any(
            stop is not None and stop.prediction_source == "schedule"
            for stop in (last, next_stop)
        )
        state = service_state(
            timeline.stops, observation_time, cancelled=decision.cancelled
        )
        skipped = [stop.current_stop for stop in timeline.stops if stop.skipped]
        changes = [
            _stop_change(stop, self._policy)
            for stop in timeline.stops
            if stop.stop_changed and stop.planned_stop is not None
        ]
        stale = feed_age > STALE_AFTER_SECONDS
        if stale:
            warnings.append(f"Trip Updates feed is {feed_age} seconds old.")
        detail = _has_realtime_detail(
            timeline.used_prediction,
            decision.cancelled,
            has_skipped=bool(skipped),
            has_changes=bool(changes),
        )
        return ServiceStatusResult(
            fetched_at=now,
            source=_SOURCE,
            attribution=ATTRIBUTION,
            query=query,
            feed_timestamp=snapshot.feed_timestamp,
            observation_timestamp=observation_time,
            service=service_description(
                service_id=update.service_id,
                route_id=update.route_id,
                start_time=update.start_time,
                relationship=update.relationship,
                static_trip=static_trip,
                service_date=service_date,
                policy=self._policy,
            ),
            state=state,
            is_cancelled=decision.cancelled,
            cancellation_source=decision.source,
            next_stop=next_stop,
            last_passed_stop=last,
            stop_updates=list(timeline.stops),
            stop_count=len(timeline.stops),
            skipped_stops=skipped,
            stop_changes=changes,
            confidence=confidence(
                entity_present=True,
                static_join=static_trip is not None,
                feed_age=max(feed_age, observation_age or 0),
                realtime_detail_present=detail,
            ),
            data_quality=RealtimeDataQuality(
                feed_age_seconds=feed_age,
                observation_age_seconds=observation_age,
                feed_is_stale=stale,
                realtime_entity_present=True,
                static_join_successful=static_trip is not None,
                used_prediction=timeline.used_prediction,
                used_inference=timeline.used_inference or inferred_schedule,
                warnings=warnings,
            ),
            coverage_note=(
                "Trip Updates can report delays, cancellations, skipped stops, added "
                "services, replacements, and platform/stop changes. A scheduled time "
                f"is not itself proof that the {self._policy.mode.value} is on time."
            ),
        )


def _stop_change(stop: StopPrediction, policy: ModePolicy) -> StopChange:
    if stop.planned_stop is None:
        raise ValueError("changed stop requires a planned stop")
    planned = stop.planned_stop
    current = stop.current_stop
    same_station = (
        policy.mode.value == "train"
        and planned.parent_station_id is not None
        and planned.parent_station_id == current.parent_station_id
    )
    return StopChange(
        sequence=stop.sequence,
        location_name=current.parent_station_name or current.name,
        change_type="platform" if same_station else "stop",
        planned_stop=planned,
        current_stop=current,
    )


def _progress(
    stops: tuple[StopPrediction, ...],
    observation_time: datetime,
    cancelled: bool,
) -> tuple[StopPrediction | None, StopPrediction | None]:
    return (None, None) if cancelled else locate_progress(stops, observation_time)


def _has_realtime_detail(
    used_prediction: bool,
    cancelled: bool,
    *,
    has_skipped: bool,
    has_changes: bool,
) -> bool:
    return any((used_prediction, cancelled, has_skipped, has_changes))
