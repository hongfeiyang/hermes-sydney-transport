"""Strict wire models for TfNSW Live Traffic GeoJSON hazards."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

ShortText = Annotated[str, Field(strict=True, max_length=500)]
LongText = Annotated[str, Field(strict=True, max_length=8_192)]
UrlText = Annotated[str, Field(strict=True, max_length=2_048)]
EpochMillis = Annotated[int, Field(strict=True, ge=0, le=4_102_444_800_000)]
HazardId = StrictInt | Annotated[float, Field(strict=True, allow_inf_nan=False)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class RightsWire(WireModel):
    copyright: ShortText | None = None
    licence: LongText | None = None


class WebLinkWire(WireModel):
    linkText: ShortText | None = None
    linkURL: UrlText | None = None


class RoadWire(WireModel):
    mainStreet: ShortText | None = None
    crossStreet: ShortText | None = None
    locationQualifier: ShortText | None = None
    secondLocation: ShortText | None = None
    suburb: ShortText | None = None
    region: ShortText | None = None
    trafficVolume: ShortText | None = None
    delay: ShortText | None = None
    queueLength: StrictInt | float | None = None


class HazardPropertiesWire(WireModel):
    displayName: ShortText | None = None
    headline: LongText | None = None
    mainCategory: ShortText | None = None
    incidentKind: ShortText | None = None
    adviceA: ShortText | None = None
    adviceB: ShortText | None = None
    adviceC: ShortText | None = None
    otherAdvice: LongText | None = None
    publicTransport: LongText | None = None
    impactingNetwork: StrictBool
    ended: StrictBool
    isMajor: StrictBool
    expectedDelay: StrictInt | None = None
    speedLimit: StrictInt | None = None
    lastUpdated: EpochMillis | None = None
    start: EpochMillis | None = None
    end: EpochMillis | None = None
    roads: list[RoadWire] = Field(default_factory=list, max_length=100)
    webLinks: list[WebLinkWire] = Field(default_factory=list, max_length=50)


class GeometryWire(WireModel):
    type: Literal["Point", "POINT"]
    coordinates: list[StrictInt | float] = Field(min_length=2, max_length=2)


class FeatureWire(WireModel):
    type: Literal["Feature"]
    id: HazardId
    geometry: GeometryWire
    properties: HazardPropertiesWire


class FeatureCollectionWire(WireModel):
    type: Literal["FeatureCollection"]
    rights: RightsWire | None = None
    layerName: ShortText
    lastPublished: EpochMillis | None = None
    features: list[FeatureWire] = Field(max_length=2_000)
