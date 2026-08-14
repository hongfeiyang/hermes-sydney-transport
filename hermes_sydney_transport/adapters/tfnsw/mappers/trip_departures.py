"""Pure Trip Planner departure projections and selection helpers."""

from __future__ import annotations

from ....models.outputs import Route
from ....ports.trip_planner import DepartureCandidate, ServiceResolution
from ..wire.trip_planner import StopEventWire, TransportationWire
from .time import sydney_time

MODE_CODES = {
    "train": 1,
    "metro": 2,
    "light_rail": 4,
    "bus": 5,
    "ferry": 9,
}


def transport_mode(event: StopEventWire) -> str | None:
    product_class = product_class_for(event.transportation)
    return next(
        (mode for mode, code in MODE_CODES.items() if code == product_class), None
    )


def map_departure(event: StopEventWire) -> DepartureCandidate:
    transport = event.transportation or TransportationWire()
    properties = event.properties
    transport_properties = transport.properties
    location = event.location
    return DepartureCandidate(
        mode=transport_mode(event),
        planned_time=sydney_time(
            event.departure_time_planned or event.planned_departure_time
        ),
        estimated_time=sydney_time(
            event.departure_time_estimated or event.estimated_departure_time
        ),
        cancelled=_reported_flag(
            event.is_cancelled,
            properties.is_cancelled,
            transport_properties.is_cancelled,
        ),
        platform=(location.disassembled_name or location.name) if location else None,
        route=Route(
            id=transport.id,
            number=transport.number,
            name=transport.name,
            icon_id=transport.icon_id,
            product_class=product_class_for(transport),
        ),
        destination=transport.destination.name if transport.destination else None,
        operator=transport.operator.name if transport.operator else None,
        trip_code=transport_properties.trip_code,
        service_id=properties.realtime_trip_id,
        alert_ids=tuple(item.id for item in event.infos if item.id),
    )


def service_resolution(event: StopEventWire) -> ServiceResolution | None:
    service_id = event.properties.realtime_trip_id
    if service_id is None:
        return None
    return ServiceResolution(
        service_id=service_id,
        planned_time=sydney_time(
            event.departure_time_planned or event.planned_departure_time
        ),
    )


def trip_code(event: StopEventWire) -> str | None:
    return event.transportation.properties.trip_code if event.transportation else None


def product_class_for(transport: TransportationWire | None) -> int | None:
    return transport.product.product_class if transport and transport.product else None


def _reported_flag(*values: bool | None) -> bool | None:
    present = tuple(value for value in values if value is not None)
    return any(present) if present else None
