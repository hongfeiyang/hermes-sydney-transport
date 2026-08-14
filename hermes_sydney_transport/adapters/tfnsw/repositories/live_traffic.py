"""Small Live Traffic repository composed from shared platform contracts."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping

from ....models.errors import DomainError
from ....models.live_traffic_inputs import HazardType
from ....models.live_traffic_outputs import LiveTrafficHazard
from ....ports.live_traffic import HazardQuery, LiveTrafficHazardsPort
from ..catalogs.endpoints import LIVE_TRAFFIC_ENDPOINTS
from ..codecs import JsonModelCodec
from ..codecs.rich_text import normalise_live_traffic
from ..mappers.live_traffic import (
    feature_matches_suburb,
    hazard_sort_key,
    map_hazard,
    within_radius,
)
from ..platform import EndpointSpec, HttpTransport
from ..wire.live_traffic import FeatureCollectionWire


class TfnswLiveTrafficRepository(LiveTrafficHazardsPort):
    def __init__(
        self,
        transport: HttpTransport,
        *,
        endpoints: Mapping[str, EndpointSpec] = LIVE_TRAFFIC_ENDPOINTS,
        codec: JsonModelCodec[FeatureCollectionWire] | None = None,
        cache_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= cache_seconds <= 120:
            raise ValueError("cache_seconds must be between 0 and 120")
        self._transport = transport
        self._endpoints = dict(endpoints)
        self._codec = codec or JsonModelCodec(
            FeatureCollectionWire, source="Live Traffic GeoJSON"
        )
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, FeatureCollectionWire]] = {}

    def find_hazards(self, query: HazardQuery) -> tuple[LiveTrafficHazard, ...]:
        records = [
            mapped
            for hazard_type in query.hazard_types
            for feature in self._collection(hazard_type).features
            if feature_matches_suburb(feature, query.suburb)
            if within_radius(
                mapped := map_hazard(feature, hazard_type, query),
                query.radius_metres,
            )
        ]
        return tuple(sorted(records, key=hazard_sort_key)[: query.limit])

    def _collection(self, hazard_type: HazardType) -> FeatureCollectionWire:
        with self._lock:
            now = self._monotonic()
            cached = self._cache.get(hazard_type)
            if cached is not None and now < cached[0]:
                return cached[1]
            endpoint = self._endpoints[hazard_type]
            payload = self._transport.fetch(endpoint)
            if payload.body is None:
                raise DomainError(
                    "invalid_upstream_response",
                    "TfNSW Live Traffic response did not contain a body.",
                )
            collection = normalise_live_traffic(self._codec(payload.body))
            self._cache[hazard_type] = (now + self._cache_seconds, collection)
            return collection
