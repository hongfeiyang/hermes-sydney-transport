"""Live Traffic hazard use case."""

from __future__ import annotations

from datetime import UTC

from ..models.live_traffic_inputs import LiveTrafficHazardsInput
from ..models.live_traffic_outputs import LiveTrafficHazardsResult
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
        return LiveTrafficHazardsResult.model_validate(
            {
                "fetched_at": self._clock.now().astimezone(UTC),
                "source": _SOURCE,
                "attribution": ATTRIBUTION,
                "query": {
                    "latitude": request.latitude,
                    "longitude": request.longitude,
                    "suburb": request.suburb,
                    "radius_metres": request.radius_metres,
                    "hazard_types": request.hazard_types,
                },
                "hazards": [
                    {
                        "id": item.id,
                        "hazard_type": item.hazard_type,
                        "incident_kind": item.incident_kind,
                        "display_name": item.display_name,
                        "headline": item.headline,
                        "main_category": item.main_category,
                        "advice": list(item.advice),
                        "other_advice": item.other_advice,
                        "public_transport": item.public_transport,
                        "impacting_network": item.impacting_network,
                        "ended": item.ended,
                        "is_major": item.is_major,
                        "expected_delay_minutes": item.expected_delay_minutes,
                        "speed_limit_kmh": item.speed_limit_kmh,
                        "updated_at": item.updated_at,
                        "start_at": item.start_at,
                        "end_at": item.end_at,
                        "distance_metres": item.distance_metres,
                        "coordinates": {
                            "latitude": item.latitude,
                            "longitude": item.longitude,
                        },
                        "roads": [
                            {
                                "main_street": road.main_street,
                                "cross_street": road.cross_street,
                                "location_qualifier": road.location_qualifier,
                                "second_location": road.second_location,
                                "suburb": road.suburb,
                                "region": road.region,
                                "traffic_volume": road.traffic_volume,
                                "delay": road.delay,
                                "queue_length_km": road.queue_length_km,
                            }
                            for road in item.roads
                        ],
                        "links": [
                            {"text": link.text, "url": link.url} for link in item.links
                        ],
                    }
                    for item in hazards
                ],
                "count": len(hazards),
                "quality_note": _QUALITY_NOTE,
                "remote_content_is_untrusted": True,
            }
        )
