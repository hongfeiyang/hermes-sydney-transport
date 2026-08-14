"""Semantic, cached repository over TfNSW GTFS-Realtime feeds."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from ....models.errors import DomainError
from ....ports.realtime import (
    ServiceRealtimeSnapshot,
    TripUpdateRecord,
    TripUpdatesFeed,
    UpdateBundle,
    VehiclePositionsFeed,
    VehicleRealtimeSnapshot,
    VehicleRecord,
)
from ..catalogs.feeds import ModeFeeds
from ..platform import EndpointSpec, HttpTransport


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
    def __init__(
        self,
        transport: HttpTransport,
        decoder: RealtimeFeedDecoder,
        *,
        feeds: ModeFeeds,
        cache_seconds: float = 15.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= cache_seconds <= 60:
            raise ValueError("cache_seconds must be between 0 and 60")
        self._transport = transport
        self._decoder = decoder
        self._feeds = feeds
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
            if self._trip_cache is not None and now < self._trip_cache[0]:
                self._trip_cache_hits += 1
                return self._trip_cache[1]
            bodies = self._fetch_bodies(self._feeds.trip_updates, "trip updates")
            feed = _merge_trip_updates(map(self._decoder.trip_updates, bodies))
            self._trip_fetches += len(bodies)
            self._trip_cache = (now + self._cache_seconds, feed)
            return feed

    def _vehicle_feed(self) -> VehiclePositionsFeed:
        with self._lock:
            now = self._monotonic()
            if self._vehicle_cache is not None and now < self._vehicle_cache[0]:
                self._vehicle_cache_hits += 1
                return self._vehicle_cache[1]
            bodies = self._fetch_bodies(
                self._feeds.vehicle_positions, "vehicle positions"
            )
            feed = _merge_vehicle_positions(
                map(self._decoder.vehicle_positions, bodies)
            )
            self._vehicle_fetches += len(bodies)
            self._vehicle_cache = (now + self._cache_seconds, feed)
            return feed

    def _fetch_bodies(
        self, endpoints: tuple[EndpointSpec, ...], label: str
    ) -> tuple[bytes, ...]:
        payloads = tuple(self._transport.fetch(endpoint) for endpoint in endpoints)
        if not payloads or any(payload.body is None for payload in payloads):
            raise DomainError(
                "invalid_realtime_feed",
                f"TfNSW {label} did not return a complete feed.",
            )
        return tuple(payload.body for payload in payloads if payload.body is not None)


def _merge_trip_updates(feeds: Iterable[TripUpdatesFeed]) -> TripUpdatesFeed:
    materialized = tuple(feeds)
    if not materialized:
        raise DomainError(
            "invalid_realtime_feed",
            "TfNSW Trip Updates did not return any upstream feed.",
        )
    updates: dict[str, TripUpdateRecord] = {}
    bundles: list[UpdateBundle] = []
    for feed in materialized:
        for service_id, update in feed.updates.items():
            updates.setdefault(service_id, update)
        bundles.extend(feed.update_bundles)
    return TripUpdatesFeed(
        feed_timestamp=max(feed.feed_timestamp for feed in materialized),
        updates=updates,
        update_bundles=tuple(bundles),
    )


def _merge_vehicle_positions(
    feeds: Iterable[VehiclePositionsFeed],
) -> VehiclePositionsFeed:
    materialized = tuple(feeds)
    if not materialized:
        raise DomainError(
            "invalid_realtime_feed",
            "TfNSW Vehicle Positions did not return any upstream feed.",
        )
    vehicles: dict[str, VehicleRecord] = {}
    for feed in materialized:
        for service_id, vehicle in feed.vehicles.items():
            vehicles.setdefault(service_id, vehicle)
    return VehiclePositionsFeed(
        feed_timestamp=max(feed.feed_timestamp for feed in materialized),
        vehicles=vehicles,
    )
