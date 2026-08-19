"""Pure Trip Planner journey and system-message projections."""

from __future__ import annotations

from ....models.outputs import SystemMessage, TripLeg, TripRoute
from ....ports.trip_planner import JourneyCandidate
from ..wire.trip_planner import (
    JourneyLegWire,
    JourneyWire,
    SystemMessageEnvelopeWire,
    SystemMessageWire,
    TransportationWire,
)
from .trip_departures import MODE_CODES, product_class_for
from .trip_locations import map_trip_stop


def map_journey(item: JourneyWire) -> JourneyCandidate | None:
    legs = tuple(map_leg(leg) for leg in item.legs)
    return (
        JourneyCandidate(
            legs=legs,
            declared_interchanges=item.interchanges,
            rating=item.rating,
        )
        if legs
        else None
    )


def map_leg(item: JourneyLegWire) -> TripLeg:
    transport = item.transportation or TransportationWire()
    product_class = product_class_for(transport)
    stops = [map_trip_stop(stop) for stop in item.stop_sequence]
    return TripLeg(
        mode=_mode(product_class, item.transportation is None),
        duration_seconds=item.duration,
        duration_minutes=round(item.duration / 60)
        if item.duration is not None
        else None,
        distance_metres=item.distance,
        is_realtime_controlled=item.is_realtime_controlled,
        realtime_status=_realtime_status(item.realtime_status),
        cancelled=_reported_flag(
            item.is_cancelled,
            item.properties.is_cancelled,
            transport.is_cancelled,
        ),
        origin=map_trip_stop(item.origin),
        destination=map_trip_stop(item.destination),
        route=TripRoute(
            id=transport.id,
            number=transport.number,
            name=transport.name,
            description=transport.description,
            product_class=product_class,
        ),
        operator=transport.operator.name if transport.operator else None,
        service_destination=(
            transport.destination.name if transport.destination else None
        ),
        stop_count=len(stops),
        stops=stops,
        alert_ids=[item.id for item in item.infos if item.id],
        hints=[text for hint in item.hints if (text := hint.info_text)],
    )


def map_system_messages(
    value: tuple[SystemMessageWire, ...] | SystemMessageEnvelopeWire | None,
) -> tuple[SystemMessage, ...]:
    messages = (
        value.response_messages
        if isinstance(value, SystemMessageEnvelopeWire)
        else value or ()
    )
    return tuple(
        SystemMessage(
            type=item.type,
            code=item.code,
            message=item.error or item.text or "",
            module=item.module or item.subtype,
        )
        for item in messages
    )


def _mode(product_class: int | None, missing_transport: bool) -> str:
    known = next(
        (mode for mode, code in MODE_CODES.items() if code == product_class), None
    )
    if known is not None:
        return known
    if product_class in {99, 100} or missing_transport:
        return "walk"
    return f"mode_{product_class}" if product_class is not None else "unknown"


def _reported_flag(*values: bool | None) -> bool | None:
    present = tuple(value for value in values if value is not None)
    return any(present) if present else None


def _realtime_status(value: str | tuple[str, ...] | None) -> str | None:
    if isinstance(value, tuple):
        return ", ".join(value) or None
    return value
