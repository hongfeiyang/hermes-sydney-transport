"""Typed wire contracts for TfNSW Trip Planner rapidJSON responses."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .base import (
    FiniteNumber,
    LongText,
    NullableBool,
    NullableInt,
    NullableNonNegativeInt,
    NullableText,
    NullableTimestamp,
    WireModel,
)

LaxInt = Annotated[int, Field(strict=False)]


class ApiErrorWire(WireModel):
    message: LongText | None = None


class TripPlannerPayloadWire(WireModel):
    error: ApiErrorWire | str | None = None


class NamedWire(WireModel):
    id: NullableText = None
    name: NullableText = None


class ProductWire(WireModel):
    product_class: NullableInt = Field(default=None, alias="class")


class ProviderPropertiesWire(WireModel):
    trip_code: NullableText = Field(default=None, alias="tripCode")
    realtime_trip_id: NullableText = Field(default=None, alias="RealtimeTripId")
    is_cancelled: NullableBool = Field(default=None, alias="isCancelled")
    platform_name: NullableText = Field(default=None, alias="platformName")
    planned_platform_name: NullableText = Field(
        default=None, alias="plannedPlatformName"
    )
    stopping_point_planned: NullableText = Field(
        default=None, alias="stoppingPointPlanned"
    )
    wheelchair_access: NullableBool = Field(default=None, alias="WheelchairAccess")
    stop_global_id: NullableText = Field(default=None, alias="STOP_GLOBAL_ID")
    stop_name_with_place: NullableText = Field(
        default=None, alias="STOP_NAME_WITH_PLACE"
    )
    stop_name: NullableText = Field(default=None, alias="STOP_NAME")
    stop_point_long_name: NullableText = Field(
        default=None, alias="STOP_POINT_LONGNAME"
    )
    distance: NullableInt = None
    sms_text: LongText | None = Field(default=None, alias="smsText")
    provider_code: NullableText = Field(default=None, alias="providerCode")
    source: NamedWire | None = None


class LocationWire(WireModel):
    id: NullableText = None
    name: NullableText = None
    disassembled_name: NullableText = Field(default=None, alias="disassembledName")
    type: NullableText = None
    modes: Annotated[tuple[LaxInt, ...], Field(max_length=20)] = ()
    match_quality: NullableInt = Field(default=None, alias="matchQuality")
    is_best: NullableBool = Field(default=None, alias="isBest")
    coord: tuple[FiniteNumber, FiniteNumber] | None = None
    parent: NamedWire | None = None
    properties: ProviderPropertiesWire = Field(default_factory=ProviderPropertiesWire)
    departure_time_planned: NullableTimestamp = Field(
        default=None, alias="departureTimePlanned"
    )
    departure_time_estimated: NullableTimestamp = Field(
        default=None, alias="departureTimeEstimated"
    )
    arrival_time_planned: NullableTimestamp = Field(
        default=None, alias="arrivalTimePlanned"
    )
    arrival_time_estimated: NullableTimestamp = Field(
        default=None, alias="arrivalTimeEstimated"
    )


class StopFinderPayloadWire(TripPlannerPayloadWire):
    locations: Annotated[tuple[LocationWire, ...], Field(max_length=2_000)] = ()


class InfoReferenceWire(WireModel):
    id: NullableText = None


class TransportationWire(WireModel):
    id: NullableText = None
    number: NullableText = None
    name: NullableText = None
    description: NullableText = None
    icon_id: NullableInt = Field(default=None, alias="iconId")
    product: ProductWire | None = None
    properties: ProviderPropertiesWire = Field(default_factory=ProviderPropertiesWire)
    destination: NamedWire | None = None
    operator: NamedWire | None = None
    is_cancelled: NullableBool = Field(default=None, alias="isCancelled")


class StopEventWire(WireModel):
    departure_time_planned: NullableTimestamp = Field(
        default=None, alias="departureTimePlanned"
    )
    planned_departure_time: NullableTimestamp = Field(
        default=None, alias="plannedDepartureTime"
    )
    departure_time_estimated: NullableTimestamp = Field(
        default=None, alias="departureTimeEstimated"
    )
    estimated_departure_time: NullableTimestamp = Field(
        default=None, alias="estimatedDepartureTime"
    )
    is_cancelled: NullableBool = Field(default=None, alias="isCancelled")
    transportation: TransportationWire | None = None
    location: LocationWire | None = None
    properties: ProviderPropertiesWire = Field(default_factory=ProviderPropertiesWire)
    infos: Annotated[tuple[InfoReferenceWire, ...], Field(max_length=30)] = ()


class DeparturesPayloadWire(TripPlannerPayloadWire):
    stop_events: Annotated[tuple[StopEventWire, ...], Field(max_length=2_000)] = Field(
        default=(), alias="stopEvents"
    )
    locations: Annotated[tuple[LocationWire, ...], Field(max_length=100)] = ()


class HintWire(WireModel):
    info_text: LongText | None = Field(default=None, alias="infoText")


class JourneyLegWire(WireModel):
    duration: NullableNonNegativeInt = None
    distance: NullableNonNegativeInt = None
    is_realtime_controlled: NullableBool = Field(
        default=None, alias="isRealtimeControlled"
    )
    realtime_status: NullableText = Field(default=None, alias="realtimeStatus")
    is_cancelled: NullableBool = Field(default=None, alias="isCancelled")
    origin: LocationWire | None = None
    destination: LocationWire | None = None
    transportation: TransportationWire | None = None
    properties: ProviderPropertiesWire = Field(default_factory=ProviderPropertiesWire)
    stop_sequence: Annotated[tuple[LocationWire, ...], Field(max_length=30)] = Field(
        default=(), alias="stopSequence"
    )
    infos: Annotated[tuple[InfoReferenceWire, ...], Field(max_length=30)] = ()
    hints: Annotated[tuple[HintWire, ...], Field(max_length=10)] = ()


class JourneyWire(WireModel):
    legs: Annotated[tuple[JourneyLegWire, ...], Field(max_length=12)] = ()
    interchanges: NullableInt = None
    rating: NullableInt = None


class SystemMessageWire(WireModel):
    type: NullableText = None
    code: NullableInt = None
    error: LongText | None = None
    text: LongText | None = None
    module: NullableText = None
    subtype: NullableText = Field(default=None, alias="subType")


class SystemMessageEnvelopeWire(WireModel):
    response_messages: Annotated[
        tuple[SystemMessageWire, ...], Field(max_length=10)
    ] = Field(default=(), alias="responseMessages")


class JourneyPayloadWire(TripPlannerPayloadWire):
    journeys: Annotated[tuple[JourneyWire, ...], Field(max_length=100)] = ()
    system_messages: (
        tuple[SystemMessageWire, ...] | SystemMessageEnvelopeWire | None
    ) = Field(default=None, alias="systemMessages")


class AffectedWire(WireModel):
    id: NullableText = None
    name: NullableText = None
    number: NullableText = None


class AffectedGroupsWire(WireModel):
    lines: Annotated[tuple[AffectedWire, ...], Field(max_length=20)] = ()
    stops: Annotated[tuple[AffectedWire, ...], Field(max_length=20)] = ()


class TimeRangeWire(WireModel):
    from_: NullableTimestamp = Field(default=None, alias="from")
    to: NullableTimestamp = None


class AlertTimestampsWire(WireModel):
    creation: NullableTimestamp = None
    last_modification: NullableTimestamp = Field(default=None, alias="lastModification")
    validity: tuple[TimeRangeWire, ...] | TimeRangeWire | None = None
    availability: tuple[TimeRangeWire, ...] | TimeRangeWire | None = None


class AlertWire(WireModel):
    id: NullableText = None
    version: NullableInt = None
    priority: NullableText = None
    type: NullableText = None
    subtitle: LongText | None = None
    content: LongText | None = None
    affected: AffectedGroupsWire = Field(default_factory=AffectedGroupsWire)
    timestamps: AlertTimestampsWire = Field(default_factory=AlertTimestampsWire)
    properties: ProviderPropertiesWire = Field(default_factory=ProviderPropertiesWire)
    url: NullableText = None
    url_text: LongText | None = Field(default=None, alias="urlText")


class CurrentInfosWire(WireModel):
    current: Annotated[tuple[AlertWire, ...], Field(max_length=1_000)] = ()


class AlertsPayloadWire(TripPlannerPayloadWire):
    infos: CurrentInfosWire | None = None
