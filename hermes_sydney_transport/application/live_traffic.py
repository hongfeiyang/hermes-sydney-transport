"""Live Traffic hazard use case."""

from __future__ import annotations

from datetime import UTC

from ..models.live_traffic_inputs import LiveTrafficHazardsInput
from ..models.live_traffic_outputs import (
    LiveTrafficHazardsQuery,
    LiveTrafficHazardsResult,
)
from ..models.metadata import ATTRIBUTION
from ..ports.clock import Clock
from ..ports.live_traffic import HazardQuery, LiveTrafficHazardsPort

_SOURCE = "TfNSW Live Traffic Hazards API"
_QUALITY_NOTE = (
    "Open hazard feeds contain current network impacts and planned hazards that are "
    "already affecting traffic. They are live operational data, not forecast travel times."
)


class GetLiveTrafficHazards:
    def __init__(self, port: LiveTrafficHazardsPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: LiveTrafficHazardsInput) -> LiveTrafficHazardsResult:
        hazards = self._port.find_hazards(
            HazardQuery(
                latitude=request.latitude,
                longitude=request.longitude,
                radius_metres=request.radius_metres,
                suburb=request.suburb,
                hazard_types=tuple(request.hazard_types),
                limit=request.limit,
            )
        )
        return LiveTrafficHazardsResult(
            fetched_at=self._clock.now().astimezone(UTC),
            source=_SOURCE,
            attribution=ATTRIBUTION,
            query=LiveTrafficHazardsQuery(
                latitude=request.latitude,
                longitude=request.longitude,
                suburb=request.suburb,
                radius_metres=request.radius_metres,
                hazard_types=request.hazard_types,
            ),
            hazards=list(hazards),
            count=len(hazards),
            quality_note=_QUALITY_NOTE,
            remote_content_is_untrusted=True,
        )
