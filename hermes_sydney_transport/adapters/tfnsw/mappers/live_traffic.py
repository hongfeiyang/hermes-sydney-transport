"""Pure Live Traffic wire filtering, ordering, and canonical projection."""

from __future__ import annotations

from ....models.live_traffic_inputs import HazardType
from ....models.live_traffic_outputs import (
    LiveTrafficHazard,
    LiveTrafficLink,
    LiveTrafficRoad,
)
from ....models.outputs import Coordinates
from ....ports.live_traffic import HazardQuery
from ..wire.live_traffic import FeatureWire, RoadWire, WebLinkWire
from .geo import haversine_metres


def feature_matches_suburb(feature: FeatureWire, suburb: str | None) -> bool:
    if suburb is None:
        return True
    target = suburb.casefold()
    return any(
        road.suburb is not None and road.suburb.casefold() == target
        for road in feature.properties.roads
    )


def map_hazard(
    feature: FeatureWire, hazard_type: HazardType, query: HazardQuery
) -> LiveTrafficHazard:
    longitude, latitude = feature.geometry.coordinates
    properties = feature.properties
    distance = _distance(latitude, longitude, query)
    return LiveTrafficHazard(
        id=str(feature.id),
        hazard_type=hazard_type,
        incident_kind=(properties.incident_kind or "unknown").casefold(),
        display_name=properties.display_name or properties.headline or "Traffic hazard",
        headline=properties.headline,
        main_category=properties.main_category,
        advice=tuple(
            item
            for item in (
                properties.advice_a,
                properties.advice_b,
                properties.advice_c,
            )
            if item
        ),
        other_advice=properties.other_advice or "",
        public_transport=properties.public_transport or "",
        impacting_network=properties.impacting_network,
        ended=properties.ended,
        is_major=properties.is_major,
        expected_delay_minutes=properties.expected_delay_minutes,
        speed_limit_kmh=properties.speed_limit_kmh,
        updated_at=properties.updated_at,
        start_at=properties.start_at,
        end_at=properties.end_at,
        distance_metres=distance,
        coordinates=Coordinates(latitude=latitude, longitude=longitude),
        roads=tuple(map_road(item) for item in properties.roads[:3]),
        links=tuple(
            mapped
            for item in properties.web_links[:3]
            if (mapped := map_link(item)) is not None
        ),
    )


def map_road(item: RoadWire) -> LiveTrafficRoad:
    return LiveTrafficRoad(
        main_street=item.main_street,
        cross_street=item.cross_street,
        location_qualifier=item.location_qualifier,
        second_location=item.second_location,
        suburb=item.suburb,
        region=item.region,
        traffic_volume=item.traffic_volume,
        delay=item.delay,
        queue_length_km=item.queue_length_km,
    )


def map_link(item: WebLinkWire) -> LiveTrafficLink | None:
    return (
        LiveTrafficLink(text=item.text, url=item.url)
        if item.text and item.url
        else None
    )


def within_radius(item: LiveTrafficHazard, radius_metres: int | None) -> bool:
    return radius_metres is None or (
        item.distance_metres is not None and item.distance_metres <= radius_metres
    )


def hazard_sort_key(item: LiveTrafficHazard) -> tuple[float, bool, float, str]:
    distance = float(item.distance_metres) if item.distance_metres is not None else 1e12
    updated = item.updated_at.timestamp() if item.updated_at is not None else 0.0
    return distance, not item.is_major, -updated, item.display_name


def _distance(latitude: float, longitude: float, query: HazardQuery) -> int | None:
    if query.latitude is None or query.longitude is None:
        return None
    return haversine_metres(query.latitude, query.longitude, latitude, longitude)
