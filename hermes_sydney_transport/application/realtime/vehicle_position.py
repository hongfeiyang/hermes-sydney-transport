"""Vehicle-position use case; orchestration only, with policies delegated."""

from __future__ import annotations

from ...models.inputs import RealtimeServiceInput
from ...models.metadata import ATTRIBUTION
from ...models.outputs import (
    RealtimeDataQuality,
    VehiclePositionResult,
)
from ...ports.clock import Clock
from ...ports.realtime import RealtimeRepository, StaticSchedulePort, TripRelationship
from ...ports.trip_planner import TripPlannerPort
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
from .occupancy import occupancy_report
from .resolution import ServiceResolver
from .vehicle_projection import (
    collect_vehicle_stop_ids,
    project_vehicle,
)

_SOURCE = "TfNSW GTFS-Realtime Vehicle Positions v2"


class GetVehiclePosition:
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

    def execute(self, request: RealtimeServiceInput) -> VehiclePositionResult:
        query = self._resolver.resolve(request)
        snapshot = self._realtime.vehicle_snapshot(query.resolved_service_id)
        vehicle = snapshot.vehicle
        warnings: list[str] = []
        static_trip = load_static_trip(
            self._static, query.resolved_service_id, warnings
        )
        now = sydney_time(self._clock.now())
        feed_age = age_seconds(now, snapshot.feed_timestamp) or 0
        stale = feed_age > STALE_AFTER_SECONDS
        if stale:
            warnings.append(f"Vehicle Positions feed is {feed_age} seconds old.")
        service_date = choose_service_date(
            vehicle.start_date if vehicle else None,
            static_trip,
            request.at or snapshot.feed_timestamp,
        )
        references = load_stop_references(
            self._static,
            collect_vehicle_stop_ids(vehicle, static_trip),
        )
        projection = project_vehicle(
            vehicle, static_trip, references, snapshot.feed_timestamp
        )
        warnings.extend(projection.warnings)
        observation_age = age_seconds(now, projection.observation_time)
        if observation_age is not None and observation_age > STALE_AFTER_SECONDS:
            warnings.append(f"Vehicle observation is {observation_age} seconds old.")
        return VehiclePositionResult(
            fetched_at=now,
            source=_SOURCE,
            attribution=ATTRIBUTION,
            query=query,
            feed_timestamp=snapshot.feed_timestamp,
            service=service_description(
                service_id=query.resolved_service_id,
                route_id=vehicle.route_id if vehicle else None,
                start_time=vehicle.start_time if vehicle else None,
                relationship=(
                    vehicle.relationship if vehicle else TripRelationship.UNKNOWN
                ),
                static_trip=static_trip,
                service_date=service_date,
                policy=self._policy,
            ),
            available=projection.position is not None,
            vehicle=projection.details,
            position=projection.position,
            current_status=(vehicle.current_status.value if vehicle else "unknown"),
            stop_context=projection.stop_context,
            occupancy=occupancy_report(vehicle, self._policy),
            confidence=confidence(
                entity_present=vehicle is not None,
                static_join=static_trip is not None,
                feed_age=max(feed_age, observation_age or 0),
                realtime_detail_present=projection.position is not None,
            ),
            data_quality=RealtimeDataQuality(
                feed_age_seconds=feed_age,
                observation_age_seconds=observation_age,
                feed_is_stale=stale,
                realtime_entity_present=vehicle is not None,
                static_join_successful=static_trip is not None,
                used_prediction=False,
                used_inference=projection.used_inference,
                warnings=warnings,
            ),
            coverage_note=self._policy.position_coverage_note,
        )
