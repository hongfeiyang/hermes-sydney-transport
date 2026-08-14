"""Strict normalized wire contracts for Live Traffic GeoJSON."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt

from .base import (
    FiniteNumber,
    Latitude,
    Longitude,
    LongText,
    OptionalEpochMillis,
    OptionalNonNegativeNumber,
    OptionalPositiveInt,
    ShortText,
    UrlText,
    WireModel,
)

HazardId = StrictInt | FiniteNumber


class RightsWire(WireModel):
    copyright: ShortText | None = None
    licence: LongText | None = None


class WebLinkWire(WireModel):
    text: ShortText | None = Field(default=None, alias="linkText")
    url: UrlText | None = Field(default=None, alias="linkURL")


class RoadWire(WireModel):
    main_street: ShortText | None = Field(default=None, alias="mainStreet")
    cross_street: ShortText | None = Field(default=None, alias="crossStreet")
    location_qualifier: ShortText | None = Field(
        default=None, alias="locationQualifier"
    )
    second_location: ShortText | None = Field(default=None, alias="secondLocation")
    suburb: ShortText | None = None
    region: ShortText | None = None
    traffic_volume: ShortText | None = Field(default=None, alias="trafficVolume")
    delay: ShortText | None = None
    queue_length_km: OptionalNonNegativeNumber = Field(
        default=None, alias="queueLength"
    )


class HazardPropertiesWire(WireModel):
    display_name: ShortText | None = Field(default=None, alias="displayName")
    headline: LongText | None = None
    main_category: ShortText | None = Field(default=None, alias="mainCategory")
    incident_kind: ShortText | None = Field(default=None, alias="incidentKind")
    advice_a: ShortText | None = Field(default=None, alias="adviceA")
    advice_b: ShortText | None = Field(default=None, alias="adviceB")
    advice_c: ShortText | None = Field(default=None, alias="adviceC")
    other_advice: LongText | None = Field(default=None, alias="otherAdvice")
    public_transport: LongText | None = Field(default=None, alias="publicTransport")
    impacting_network: StrictBool = Field(alias="impactingNetwork")
    ended: StrictBool
    is_major: StrictBool = Field(alias="isMajor")
    expected_delay_minutes: OptionalPositiveInt = Field(
        default=None, alias="expectedDelay"
    )
    speed_limit_kmh: OptionalPositiveInt = Field(default=None, alias="speedLimit")
    updated_at: OptionalEpochMillis = Field(default=None, alias="lastUpdated")
    start_at: OptionalEpochMillis = Field(default=None, alias="start")
    end_at: OptionalEpochMillis = Field(default=None, alias="end")
    roads: tuple[RoadWire, ...] = Field(default_factory=tuple, max_length=100)
    web_links: tuple[WebLinkWire, ...] = Field(
        default_factory=tuple, alias="webLinks", max_length=50
    )


class GeometryWire(WireModel):
    type: Literal["Point", "POINT"]
    coordinates: tuple[Longitude, Latitude]


class FeatureWire(WireModel):
    type: Literal["Feature"]
    id: HazardId
    geometry: GeometryWire
    properties: HazardPropertiesWire


class FeatureCollectionWire(WireModel):
    type: Literal["FeatureCollection"]
    rights: RightsWire | None = None
    layer_name: ShortText = Field(alias="layerName")
    last_published: OptionalEpochMillis = Field(default=None, alias="lastPublished")
    features: Annotated[tuple[FeatureWire, ...], Field(max_length=2_000)]
