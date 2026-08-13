"""Semantic, cached repository over TfNSW realtime feed infrastructure."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ...models.errors import DomainError
from ...ports.realtime import (
    ServiceRealtimeSnapshot,
    TripUpdateRecord,
    TripUpdatesFeed,
    UpdateBundle,
    VehiclePositionsFeed,
    VehicleRealtimeSnapshot,
    VehicleRecord,
)
from .binary_transport import BinaryTransport


class RealtimeFeedDecoder(Protocol):
    def trip_updates(self, raw: bytes) -> TripUpdatesFeed: ...

    def vehicle_positions(self, raw: bytes) -> VehiclePositionsFeed: ...


@dataclass(frozen=True, slots=True)
class RealtimeCacheStats:
    trip_fetches: int
    trip_cache_hits: int
    vehicle_fetches: int
    vehicle_cache_hits: int


class TfnswRealtimeRepository:
    """Fetch and index each feed at most once per bounded cache interval."""

    def __init__(
        self,
        transport: BinaryTransport,
        decoder: RealtimeFeedDecoder,
        *,
        cache_seconds: float = 15.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if cache_seconds < 0 or cache_seconds > 60:
            raise ValueError("cache_seconds must be between 0 and 60")
        self._transport = transport
        self._decoder = decoder
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._trip_cache: tuple[float, TripUpdatesFeed] | None = None
        self._vehicle_cache: tuple[float, VehiclePositionsFeed] | None = None
        self._trip_fetches = 0
        self._trip_cache_hits = 0
        self._vehicle_fetches = 0
        self._vehicle_cache_hits = 0

    def service_snapshot(self, service_id: str) -> ServiceRealtimeSnapshot:
        feed = self._trip_feed()
        return ServiceRealtimeSnapshot(
            feed_timestamp=feed.feed_timestamp,
            update=feed.updates.get(service_id),
            cancellation_bundles=tuple(
                bundle
                for bundle in feed.update_bundles
                if service_id in bundle.cancelled_trip_ids
            ),
        )

    def vehicle_snapshot(self, service_id: str) -> VehicleRealtimeSnapshot:
        feed = self._vehicle_feed()
        return VehicleRealtimeSnapshot(
            feed_timestamp=feed.feed_timestamp,
            vehicle=feed.vehicles.get(service_id),
        )

    def stats(self) -> RealtimeCacheStats:
        with self._lock:
            return RealtimeCacheStats(
                trip_fetches=self._trip_fetches,
                trip_cache_hits=self._trip_cache_hits,
                vehicle_fetches=self._vehicle_fetches,
                vehicle_cache_hits=self._vehicle_cache_hits,
            )

    def _trip_feed(self) -> TripUpdatesFeed:
        with self._lock:
            now = self._monotonic()
            if self._trip_cache and now < self._trip_cache[0]:
                self._trip_cache_hits += 1
                return self._trip_cache[1]
            responses = self._transport.get_all("trip_updates")
            feeds = []
            for response in responses:
                if response.data is None:
                    raise DomainError(
                        "invalid_realtime_feed",
                        "TfNSW Trip Updates response did not contain a feed.",
                    )
                feeds.append(self._decoder.trip_updates(response.data))
            feed = _merge_trip_updates(tuple(feeds))
            self._trip_fetches += len(responses)
            self._trip_cache = (now + self._cache_seconds, feed)
            return feed

    def _vehicle_feed(self) -> VehiclePositionsFeed:
        with self._lock:
            now = self._monotonic()
            if self._vehicle_cache and now < self._vehicle_cache[0]:
                self._vehicle_cache_hits += 1
                return self._vehicle_cache[1]
            responses = self._transport.get_all("vehicle_positions")
            feeds = []
            for response in responses:
                if response.data is None:
                    raise DomainError(
                        "invalid_realtime_feed",
                        "TfNSW Vehicle Positions response did not contain a feed.",
                    )
                feeds.append(self._decoder.vehicle_positions(response.data))
            feed = _merge_vehicle_positions(tuple(feeds))
            self._vehicle_fetches += len(responses)
            self._vehicle_cache = (now + self._cache_seconds, feed)
            return feed


def _merge_trip_updates(feeds: tuple[TripUpdatesFeed, ...]) -> TripUpdatesFeed:
    if not feeds:
        raise DomainError(
            "invalid_realtime_feed",
            "TfNSW Trip Updates did not return any upstream feed.",
        )
    feed_timestamp = max(feed.feed_timestamp for feed in feeds)
    updates: dict[str, TripUpdateRecord] = {}
    bundles: list[UpdateBundle] = []
    for feed in feeds:
        for service_id, update in feed.updates.items():
            # Earlier upstream feeds in the allowlisted registry keep precedence when
            # a service ID appears more than once.
            updates.setdefault(service_id, update)
        bundles.extend(feed.update_bundles)
    return TripUpdatesFeed(
        feed_timestamp=feed_timestamp,
        updates=updates,
        update_bundles=tuple(bundles),
    )


def _merge_vehicle_positions(
    feeds: tuple[VehiclePositionsFeed, ...],
) -> VehiclePositionsFeed:
    if not feeds:
        raise DomainError(
            "invalid_realtime_feed",
            "TfNSW Vehicle Positions did not return any upstream feed.",
        )
    feed_timestamp = max(feed.feed_timestamp for feed in feeds)
    vehicles: dict[str, VehicleRecord] = {}
    for feed in feeds:
        for service_id, vehicle in feed.vehicles.items():
            # Earlier upstream feeds in the allowlisted registry keep precedence when
            # a service ID appears more than once.
            vehicles.setdefault(service_id, vehicle)
    return VehiclePositionsFeed(feed_timestamp=feed_timestamp, vehicles=vehicles)
