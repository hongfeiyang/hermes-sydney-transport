"""Semantic, cached repository over typed TfNSW Alerts v2 feeds."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from ....models.availability import Availability
from ....models.errors import DomainError
from ....ports.alerts import AlertQuery, AlertRecord, AlertsPort
from ....ports.realtime import TransportMode
from ..codecs.rich_text import plain_text, safe_web_url
from ..platform import EndpointSpec, HttpTransport, capture_domain_error

_MAX_MATCHED_ALERTS = 500


class AlertsDecoder(Protocol):
    def alerts(
        self, raw: bytes, mode: TransportMode, source_feed: str | None = None
    ) -> tuple[AlertRecord, ...]: ...


class TfnswAlertsRepository(AlertsPort):
    def __init__(
        self,
        transport: HttpTransport,
        decoder: AlertsDecoder,
        *,
        endpoints: Mapping[TransportMode, tuple[EndpointSpec, ...]],
        sources: Mapping[TransportMode, tuple[str, ...]],
        cache_seconds: float = 15.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= cache_seconds <= 60:
            raise ValueError("cache_seconds must be between 0 and 60")
        self._transport = transport
        self._decoder = decoder
        self._endpoints = dict(endpoints)
        self._sources = dict(sources)
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._cache: dict[TransportMode, tuple[float, tuple[AlertRecord, ...]]] = {}

    def find_alerts(self, query: AlertQuery) -> tuple[AlertRecord, ...]:
        records = (
            record
            for mode in query.modes
            for record in self._alerts_for_mode(mode)
            if _matches(record, query)
        )
        return _dedupe(records)[:_MAX_MATCHED_ALERTS]

    def query_alerts(self, query: AlertQuery) -> Availability[tuple[AlertRecord, ...]]:
        return capture_domain_error(lambda: self.find_alerts(query))

    def _alerts_for_mode(self, mode: TransportMode) -> tuple[AlertRecord, ...]:
        with self._lock:
            now = self._monotonic()
            cached = self._cache.get(mode)
            if cached is not None and now < cached[0]:
                return cached[1]
            records = self._decode_mode(mode)
            self._cache[mode] = (now + self._cache_seconds, records)
            return records

    def _decode_mode(self, mode: TransportMode) -> tuple[AlertRecord, ...]:
        endpoints = self._endpoints[mode]
        sources = self._sources[mode]
        if len(endpoints) != len(sources):
            raise DomainError(
                "invalid_upstream_response",
                f"TfNSW alerts endpoint catalog for {mode.value!r} is incomplete.",
            )
        records = (
            _sanitise(record)
            for source, endpoint in zip(sources, endpoints, strict=True)
            for record in self._decode_feed(mode, source, endpoint)
        )
        return _dedupe(records)

    def _decode_feed(
        self, mode: TransportMode, source: str, endpoint: EndpointSpec
    ) -> tuple[AlertRecord, ...]:
        payload = self._transport.fetch(endpoint)
        if payload.body is None:
            raise DomainError(
                "invalid_upstream_response",
                f"TfNSW alerts feed {source!r} did not contain data.",
            )
        return self._decoder.alerts(payload.body, mode, source)


def _matches(record: AlertRecord, query: AlertQuery) -> bool:
    return _matches_selectors(record, query) and _matches_time(record, query)


def _matches_selectors(record: AlertRecord, query: AlertQuery) -> bool:
    checks = (
        query.stop_id is None or query.stop_id in record.stop_ids,
        query.route_id is None or query.route_id in record.route_ids,
        query.trip_id is None or query.trip_id in record.trip_ids,
        not query.causes or record.cause in query.causes,
        not query.effects or record.effect in query.effects,
    )
    return all(checks)


def _matches_time(record: AlertRecord, query: AlertQuery) -> bool:
    if query.active_at is None or not record.active_periods:
        return True
    return any(
        (period.start is None or period.start <= query.active_at)
        and (period.end is None or query.active_at <= period.end)
        for period in record.active_periods
    )


def _sanitise(record: AlertRecord) -> AlertRecord:
    return AlertRecord(
        id=record.id,
        mode=record.mode,
        source_feed=record.source_feed,
        title=plain_text(record.title, max_chars=240),
        description=plain_text(record.description, max_chars=2_000),
        cause=record.cause,
        effect=record.effect,
        severity=record.severity,
        url=safe_web_url(record.url),
        active_periods=record.active_periods,
        selectors=record.selectors,
        route_ids=record.route_ids,
        stop_ids=record.stop_ids,
        trip_ids=record.trip_ids,
    )


def _dedupe(records: Iterable[AlertRecord]) -> tuple[AlertRecord, ...]:
    ordered = sorted(records, key=lambda item: (item.source_feed, item.id, item.title))
    return tuple({(item.source_feed, item.id): item for item in ordered}.values())
