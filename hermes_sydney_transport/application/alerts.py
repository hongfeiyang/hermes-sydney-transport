"""Route disruption policy over GTFS-Realtime alerts."""

from __future__ import annotations

from datetime import UTC

from ..models.disruption_inputs import RouteDisruptionsInput
from ..models.disruption_outputs import (
    DisruptionQuery,
    DisruptionSelector,
    DisruptionTimeRange,
    RouteDisruption,
    RouteDisruptionsResult,
)
from ..models.metadata import ATTRIBUTION
from ..ports.alerts import AlertQuery, AlertsPort
from ..ports.clock import Clock
from ..ports.realtime import TransportMode

_SOURCE = "TfNSW GTFS-Realtime Alerts v2"
_SEVERITY_RANK = {
    "severe": 3,
    "warning": 2,
    "info": 1,
    "unknown_severity": 0,
}


class GetRouteDisruptions:
    def __init__(self, port: AlertsPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: RouteDisruptionsInput) -> RouteDisruptionsResult:
        now = self._clock.now()
        effective = request.model_copy(update={"at": request.at or now})
        if effective.at is None:
            raise RuntimeError("effective disruption time was not set")
        query = AlertQuery(
            modes=tuple(TransportMode(mode) for mode in effective.modes),
            stop_id=effective.stop_id,
            route_id=effective.route_id,
            trip_id=effective.trip_id,
            causes=tuple(effective.causes),
            effects=tuple(effective.effects),
            active_at=effective.at,
        )
        disruptions = list(self._port.find_alerts(query))
        disruptions.sort(key=lambda item: item.id)
        disruptions.sort(
            key=lambda item: (
                item.active_periods[0].start
                if item.active_periods and item.active_periods[0].start is not None
                else None or now.astimezone(UTC)
            ),
            reverse=True,
        )
        disruptions.sort(
            key=lambda item: _SEVERITY_RANK.get(item.severity, 0),
            reverse=True,
        )
        disruptions = disruptions[: request.limit]
        return RouteDisruptionsResult(
            fetched_at=now,
            source=_SOURCE,
            attribution=ATTRIBUTION,
            query=DisruptionQuery(
                requested_modes=request.modes,
                stop_id=request.stop_id,
                route_id=request.route_id,
                trip_id=request.trip_id,
                requested_at=effective.at,
                causes=request.causes,
                effects=request.effects,
            ),
            disruptions=[
                RouteDisruption(
                    id=item.id,
                    mode=item.mode.value,
                    source_feed=item.source_feed,
                    title=item.title,
                    description=item.description,
                    cause=item.cause,
                    effect=item.effect,
                    severity=item.severity,
                    url=item.url,
                    active_periods=[
                        DisruptionTimeRange.model_validate(part, from_attributes=True)
                        for part in item.active_periods
                    ],
                    selectors=[
                        DisruptionSelector.model_validate(part, from_attributes=True)
                        for part in item.selectors
                    ],
                    route_ids=list(item.route_ids),
                    stop_ids=list(item.stop_ids),
                    trip_ids=list(item.trip_ids),
                )
                for item in disruptions
            ],
            count=len(disruptions),
            remote_content_is_untrusted=True,
        )
