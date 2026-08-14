"""Pure Trip Planner alert projections."""

from __future__ import annotations

from ....models.outputs import AffectedEntity, Alert, TimeRange
from ..wire.trip_planner import AlertWire, TimeRangeWire
from .time import sydney_time


def map_alert(item: AlertWire) -> Alert:
    properties = item.properties
    timestamps = item.timestamps
    return Alert(
        id=item.id,
        version=item.version,
        priority=item.priority or "unknown",
        type=item.type,
        title=item.subtitle or "",
        content=item.content or "",
        sms_summary=properties.sms_text or "",
        affected_lines=[
            AffectedEntity(id=value.id, name=value.name, number=value.number)
            for value in item.affected.lines
        ],
        affected_stops=[
            AffectedEntity(id=value.id, name=value.name, number=value.number)
            for value in item.affected.stops
        ],
        created_at=sydney_time(timestamps.creation),
        last_modified=sydney_time(timestamps.last_modification),
        validity=_ranges(timestamps.validity),
        availability=_ranges(timestamps.availability),
        provider=properties.provider_code,
        source_name=properties.source.name if properties.source else None,
        url=item.url,
        url_text=item.url_text or "",
    )


def _ranges(
    value: tuple[TimeRangeWire, ...] | TimeRangeWire | None,
) -> list[TimeRange]:
    items = value if isinstance(value, tuple) else (value,) if value is not None else ()
    return [
        TimeRange.from_bounds(sydney_time(item.from_), sydney_time(item.to))
        for item in items[:10]
    ]
