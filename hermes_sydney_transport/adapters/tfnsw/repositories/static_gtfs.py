"""Mode-specific static schedule repository orchestration."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Collection
from pathlib import Path

from ....models.availability import Availability
from ....models.errors import DomainError
from ....ports.realtime import StaticStopReference, StaticTrip
from ..platform import EndpointSpec, HttpPayload, HttpTransport, capture_domain_error
from ..stores.static_gtfs import StaticGtfsStore

_REFRESH_SECONDS = 6 * 60 * 60
_MAX_CACHED_TRIPS = 64


class StaticGtfsRepository:
    """Refresh a schedule store and expose the static schedule port."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        endpoints: tuple[EndpointSpec, ...],
        database_path: Path | None = None,
    ) -> None:
        self._transport = transport
        self._endpoints = endpoints
        self._store = StaticGtfsStore(database_path)
        self._lock = threading.RLock()
        self._checked_at: float | None = None
        self._trips: OrderedDict[str, StaticTrip | None] = OrderedDict()

    def get_trip(self, service_id: str) -> StaticTrip | None:
        with self._lock:
            self._refresh_if_needed()
            if service_id in self._trips:
                self._trips.move_to_end(service_id)
                return self._trips[service_id]
            result = self._store.trip(service_id)
            self._trips[service_id] = result
            if len(self._trips) > _MAX_CACHED_TRIPS:
                self._trips.popitem(last=False)
            return result

    def get_stop_references(
        self, stop_ids: Collection[str]
    ) -> dict[str, StaticStopReference]:
        unique = tuple(dict.fromkeys(stop_ids))[:300]
        if not unique:
            return {}
        with self._lock:
            self._refresh_if_needed()
            return self._store.stops(unique)

    def stop_reference(self, stop_id: str) -> StaticStopReference:
        return self.get_stop_references((stop_id,))[stop_id]

    def lookup_trip(self, service_id: str) -> Availability[StaticTrip | None]:
        return capture_domain_error(lambda: self.get_trip(service_id))

    def lookup_stop_references(
        self, stop_ids: Collection[str]
    ) -> Availability[dict[str, StaticStopReference]]:
        return capture_domain_error(lambda: self.get_stop_references(stop_ids))

    def close(self) -> None:
        with self._lock:
            self._store.close()

    def _refresh_if_needed(self) -> None:
        now = time.monotonic()
        self._store.open_existing()
        if self._cache_is_fresh(now):
            return
        responses = self._fetch_bundles()
        self._checked_at = now
        if (
            self._store.available
            and responses
            and all(response.not_modified for response in responses)
        ):
            return
        if any(response.body is None for response in responses):
            raise DomainError(
                "static_data_unavailable",
                "TfNSW did not return the static timetable bundle.",
                retryable=True,
            )
        last_modified = "|".join(response.last_modified or "" for response in responses)
        if self._store.available and last_modified == (self._store.last_modified or ""):
            return
        self._store.replace(
            tuple(response.body for response in responses if response.body is not None),
            last_modified,
        )
        self._trips.clear()

    def _cache_is_fresh(self, now: float) -> bool:
        return (
            self._store.available
            and self._checked_at is not None
            and now - self._checked_at < _REFRESH_SECONDS
        )

    def _fetch_bundles(self) -> tuple[HttpPayload, ...]:
        conditional = self._store.last_modified if len(self._endpoints) == 1 else None
        return tuple(
            self._transport.fetch(item, if_modified_since=conditional)
            for item in self._endpoints
        )
