"""Declarative wire contracts for facility CSV and lift XLSX rows."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from .base import ClosedWireModel, WireModel
from .timestamps import NullableTimestamp


def _text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("facility text must be a string")  # noqa: TRY004
    return " ".join(value.split()) or None


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("facility coordinate must be text")  # noqa: TRY004
    return float(value)


def _bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in {"True", "False"}:
        raise ValueError("facility boolean is outside its vocabulary")
    return value == "True"


OptionalText = Annotated[
    Annotated[str, Field(max_length=8_192)] | None, BeforeValidator(_text)
]
RequiredText = Annotated[
    str, BeforeValidator(_text), Field(min_length=1, max_length=8_192)
]
OptionalFloat = Annotated[float | None, BeforeValidator(_float)]
OptionalBool = Annotated[bool | None, BeforeValidator(_bool)]


class FacilityCsvRow(WireModel):
    name: RequiredText = Field(alias="LOCATION_NAME")
    tsn: RequiredText = Field(alias="TSN")
    efa_id: RequiredText = Field(alias="EFA_ID")
    accessibility: OptionalText = Field(default=None, alias="ACCESSIBILITY")
    facilities: OptionalText = Field(default=None, alias="FACILITIES")
    transport_modes: OptionalText = Field(default=None, alias="TRANSPORT_MODE")
    address: OptionalText = Field(default=None, alias="ADDRESS")
    phone: OptionalText = Field(default=None, alias="PHONE")
    latitude: OptionalFloat = Field(default=None, alias="LATITUDE", ge=-90, le=90)
    longitude: OptionalFloat = Field(default=None, alias="LONGITUDE", ge=-180, le=180)
    morning_staffed_hours: OptionalText = Field(default=None, alias="MORNING_PEAK")
    afternoon_staffed_hours: OptionalText = Field(default=None, alias="AFTERNOON_PEAK")
    short_platform: OptionalBool = Field(default=None, alias="SHORT_PLATFORM")

    @model_validator(mode="after")
    def coordinate_pair_is_complete(self) -> FacilityCsvRow:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("facility coordinates must be a complete pair")
        return self


class LiftSheetRow(WireModel):
    tsn: OptionalText = None
    record_updated_at: NullableTimestamp = Field(default=None, alias="_updated_at")
    functional_location_code: OptionalText = Field(
        default=None, alias="sydney_trains__lift_functional_location_code"
    )
    description: OptionalText = Field(default=None, alias="lift_location_description")


class StoredFacility(ClosedWireModel):
    name: str
    efa_id: str
    tsn: str
    address: str | None
    phone: str | None
    latitude: float | None
    longitude: float | None
    transport_modes: tuple[str, ...]
    accessibility: tuple[str, ...]
    facilities: tuple[str, ...]
    morning_staffed_hours: str | None
    afternoon_staffed_hours: str | None
    short_platform: bool | None


class StoredLift(ClosedWireModel):
    functional_location_code: str | None
    description: str | None
    record_updated_at: datetime | None


class StoredFacilitySnapshot(ClosedWireModel):
    matched_by: Literal["efa_id", "tsn", "none"]
    facility: StoredFacility | None
    lifts: tuple[StoredLift, ...]
    source_updated_at: datetime | None
    cache_stale: bool
