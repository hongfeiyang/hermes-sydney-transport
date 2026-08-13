"""Pure result policies shared by Trip Planner use cases."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal, cast

from ..models.inputs import TransitMode
from ..models.outputs import Alert, Departure, Journey
from ..ports.trip_planner import DepartureCandidate, JourneyCandidate


def departure_from_candidate(candidate: DepartureCandidate) -> Departure:
    delay = _delay_minutes(candidate.planned_time, candidate.estimated_time)
    status: Literal["cancelled", "unknown", "delayed", "early", "on_time"] = (
        "cancelled"
        if candidate.cancelled is True
        else "unknown"
        if delay is None
        else "delayed"
        if delay > 2
        else "early"
        if delay < -2
        else "on_time"
    )
    if candidate.mode not in {"train", "bus"}:
        raise ValueError("departure candidate has unsupported mode")
    return Departure(
        mode=cast(TransitMode, candidate.mode),
        planned_time=candidate.planned_time,
        estimated_time=candidate.estimated_time,
        status=status,
        delay_minutes=delay,
        realtime_available=candidate.estimated_time is not None,
        cancelled=candidate.cancelled,
        platform=candidate.platform,
        route=candidate.route,
        destination=candidate.destination,
        operator=candidate.operator,
        trip_code=candidate.trip_code,
        service_id=candidate.service_id,
        alert_ids=list(candidate.alert_ids),
    )


def journey_from_candidate(candidate: JourneyCandidate) -> Journey:
    legs = list(candidate.legs)
    if not legs:
        raise ValueError("journey candidate has no legs")
    active = [leg for leg in legs if leg.cancelled is not True]
    duration = (
        sum(leg.duration_seconds for leg in active if leg.duration_seconds is not None)
        if all(leg.duration_seconds is not None for leg in active)
        else None
    )
    train_legs = sum(leg.mode == "train" for leg in legs)
    first_origin = legs[0].origin
    last_destination = legs[-1].destination
    return Journey(
        departure_time_planned=first_origin.departure_time_planned,
        departure_time_estimated=first_origin.departure_time_estimated,
        arrival_time_planned=last_destination.arrival_time_planned,
        arrival_time_estimated=last_destination.arrival_time_estimated,
        duration_seconds=duration,
        duration_minutes=round(duration / 60) if duration is not None else None,
        interchanges=(
            candidate.declared_interchanges
            if candidate.declared_interchanges is not None
            else max(train_legs - 1, 0)
        ),
        realtime_available=_combine_optional_flags(
            leg.is_realtime_controlled for leg in legs
        ),
        cancelled=_combine_optional_flags(leg.cancelled for leg in legs),
        rating=candidate.rating,
        alert_ids=list(
            dict.fromkeys(alert_id for leg in legs for alert_id in leg.alert_ids)
        )[:30],
        legs=legs,
    )


def deduplicate_alerts(alerts: tuple[Alert, ...]) -> list[Alert]:
    by_id: dict[str, Alert] = {}
    anonymous: list[Alert] = []
    for alert in alerts:
        if not alert.id:
            anonymous.append(alert)
            continue
        existing = by_id.get(alert.id)
        revision = (
            alert.version or 0,
            alert.last_modified or datetime.min.replace(tzinfo=UTC),
        )
        if existing is None or revision >= (
            existing.version or 0,
            existing.last_modified or datetime.min.replace(tzinfo=UTC),
        ):
            by_id[alert.id] = alert
    return [*by_id.values(), *anonymous]


def alert_priority_rank(value: str) -> int:
    return {"veryHigh": 5, "high": 4, "normal": 3, "low": 2, "veryLow": 1}.get(value, 0)


def _delay_minutes(planned: datetime | None, estimated: datetime | None) -> int | None:
    if planned is None or estimated is None:
        return None
    return round((estimated - planned).total_seconds() / 60)


def _combine_optional_flags(values: Iterable[bool | None]) -> bool | None:
    present = [value for value in values if value is not None]
    return any(present) if present else None
