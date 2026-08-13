"""TfNSW GTFS-Realtime Alerts v2 adapter."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Protocol
from urllib.parse import urlsplit

from ...models.errors import DomainError
from ...ports.alerts import AlertQuery, AlertRecord, AlertsPort
from ...ports.realtime import TransportMode
from .binary_transport import BinaryTransport
from .trip_planner import html_to_plaintext

_FEED_NAMES: dict[TransportMode, tuple[str, ...]] = {
    TransportMode.TRAIN: ("sydneytrains", "nswtrains"),
    TransportMode.BUS: ("buses", "regionbuses"),
    TransportMode.METRO: ("metro",),
    TransportMode.LIGHT_RAIL: ("lightrail",),
    TransportMode.FERRY: ("ferries",),
}
_MAX_MATCHED_ALERTS = 500


class AlertsDecoder(Protocol):
    def alerts(
        self, raw: bytes, mode: TransportMode, source_feed: str | None = None
    ) -> tuple[AlertRecord, ...]: ...


class TfnswAlertsAdapter(AlertsPort):
    def __init__(
        self,
        transports: Mapping[TransportMode, BinaryTransport],
        decoder: AlertsDecoder,
        *,
        cache_seconds: float = 15.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transports = dict(transports)
        self._decoder = decoder
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._cache: dict[TransportMode, tuple[float, tuple[AlertRecord, ...]]] = {}

    def find_alerts(self, query: AlertQuery) -> tuple[AlertRecord, ...]:
        records: list[AlertRecord] = []
        for mode in query.modes:
            for record in self._alerts_for_mode(mode):
                if _matches(record, query):
                    records.append(record)
        deduped = list(_dedupe(records))
        # Final severity/time ordering and caller limits are application policy.
        # This adapter applies only a generous safety ceiling after filtering.
        return tuple(deduped[:_MAX_MATCHED_ALERTS])

    def _alerts_for_mode(self, mode: TransportMode) -> tuple[AlertRecord, ...]:
        with self._lock:
            now = self._monotonic()
            cached = self._cache.get(mode)
            if cached and now < cached[0]:
                return cached[1]
            transport = self._transports[mode]
            responses = transport.get_all("alerts")
            feed_names = _FEED_NAMES[mode]
            if len(responses) != len(feed_names):
                raise DomainError(
                    "invalid_upstream_response",
                    f"TfNSW alerts feeds for mode {mode.value!r} were incomplete.",
                )
            records: list[AlertRecord] = []
            for source_feed, response in zip(feed_names, responses, strict=True):
                if response.data is None:
                    raise DomainError(
                        "invalid_upstream_response",
                        f"TfNSW alerts feed {source_feed!r} did not contain data.",
                    )
                records.extend(
                    _sanitise(record)
                    for record in self._decoder.alerts(response.data, mode, source_feed)
                )
            result = tuple(_dedupe(records))
            self._cache[mode] = (now + self._cache_seconds, result)
            return result


def _matches(record: AlertRecord, query: AlertQuery) -> bool:
    if query.stop_id is not None and query.stop_id not in record.stop_ids:
        return False
    if query.route_id is not None and query.route_id not in record.route_ids:
        return False
    if query.trip_id is not None and query.trip_id not in record.trip_ids:
        return False
    if query.causes and record.cause not in query.causes:
        return False
    if query.effects and record.effect not in query.effects:
        return False
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
        title=html_to_plaintext(record.title, max_chars=240),
        description=html_to_plaintext(record.description, max_chars=2000),
        cause=record.cause,
        effect=record.effect,
        severity=record.severity,
        url=_safe_url(record.url),
        active_periods=record.active_periods,
        selectors=record.selectors,
        route_ids=record.route_ids,
        stop_ids=record.stop_ids,
        trip_ids=record.trip_ids,
    )


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _dedupe(records: list[AlertRecord]) -> tuple[AlertRecord, ...]:
    seen: set[tuple[str, str]] = set()
    ordered = sorted(records, key=lambda item: (item.source_feed, item.id, item.title))
    result: list[AlertRecord] = []
    for record in ordered:
        key = (record.source_feed, record.id)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return tuple(result)
