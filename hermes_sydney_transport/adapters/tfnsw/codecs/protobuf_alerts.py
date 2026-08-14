"""GTFS-Realtime Alerts protobuf projection."""

from __future__ import annotations

from typing import Any

from ....ports.alerts import AlertRecord, AlertSelector
from ....ports.realtime import TransportMode
from .protobuf_core import (
    alert_selector,
    binding,
    enum_name,
    parse_feed,
    time_range,
    translated_text,
)


def decode_alerts(
    raw: bytes, mode: TransportMode, source_feed: str | None = None
) -> tuple[AlertRecord, ...]:
    pb = binding()
    feed = parse_feed(raw, pb)
    return tuple(
        _alert_record(entity, mode, source_feed or mode.value)
        for entity in feed.entity
        if entity.HasField("alert")
    )


def _alert_record(entity: Any, mode: TransportMode, source: str) -> AlertRecord:
    alert = entity.alert
    selectors = tuple(alert_selector(item) for item in alert.informed_entity)
    title = translated_text(alert, "header_text")
    description = translated_text(alert, "description_text")
    return AlertRecord(
        id=str(entity.id).strip() or title or description or "unknown-alert",
        mode=mode,
        source_feed=source,
        title=title or description or "Service disruption",
        description=description,
        cause=enum_name(alert.Cause, alert.cause, "unknown_cause") or "unknown_cause",
        effect=enum_name(alert.Effect, alert.effect, "unknown_effect")
        or "unknown_effect",
        severity=_severity(alert),
        url=translated_text(alert, "url") or None,
        active_periods=tuple(time_range(item) for item in alert.active_period),
        selectors=selectors,
        route_ids=_selector_values(selectors, "route_id"),
        stop_ids=_selector_values(selectors, "stop_id"),
        trip_ids=_selector_values(selectors, "trip_id"),
    )


def _severity(alert: Any) -> str:
    if not alert.HasField("severity_level"):
        return "unknown_severity"
    return (
        enum_name(alert.SeverityLevel, alert.severity_level, "unknown_severity")
        or "unknown_severity"
    )


def _selector_values(
    selectors: tuple[AlertSelector, ...], field: str
) -> tuple[str, ...]:
    return tuple(
        sorted(
            value
            for selector in selectors
            if (value := getattr(selector, field)) is not None
        )
    )
