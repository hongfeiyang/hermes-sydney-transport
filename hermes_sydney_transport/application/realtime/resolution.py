"""Resolve one model request to an exact realtime service identity."""

from __future__ import annotations

from ...models.errors import DomainError
from ...models.inputs import RealtimeServiceInput
from ...models.outputs import RealtimeQuery
from ...ports.clock import Clock
from ...ports.trip_planner import TripPlannerPort
from .mode_policy import ModePolicy


class ServiceResolver:
    def __init__(
        self, trip_planner: TripPlannerPort, clock: Clock, policy: ModePolicy
    ) -> None:
        self._trip_planner = trip_planner
        self._clock = clock
        self._policy = policy

    def resolve(self, request: RealtimeServiceInput) -> RealtimeQuery:
        if request.service_id is not None:
            return RealtimeQuery(
                mode=self._policy.mode.value,
                requested_service_id=request.service_id,
                trip_code=None,
                stop_id=None,
                requested_at=request.at,
                resolved_service_id=request.service_id,
                resolution="service_id",
            )
        if request.trip_code is None or request.stop_id is None:
            raise DomainError(
                "invalid_argument", "trip_code and stop_id must be supplied together."
            )
        resolution = self._trip_planner.resolve_service_id(
            request.trip_code,
            request.stop_id,
            request.at or self._clock.now(),
            self._policy.mode.value,
        )
        return RealtimeQuery(
            mode=self._policy.mode.value,
            requested_service_id=None,
            trip_code=request.trip_code,
            stop_id=request.stop_id,
            requested_at=request.at,
            resolved_service_id=resolution.service_id,
            resolution="trip_code",
        )
