"""Reusable strict scalar contracts for TfNSW wire models."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

ShortText = Annotated[
    str,
    BeforeValidator(
        lambda value: " ".join(value.split()) if isinstance(value, str) else value
    ),
    StringConstraints(max_length=500),
]
LongText = Annotated[
    str,
    BeforeValidator(
        lambda value: " ".join(value.split()) if isinstance(value, str) else value
    ),
    StringConstraints(max_length=8_192),
]
UrlText = Annotated[
    str,
    BeforeValidator(lambda value: value.strip() if isinstance(value, str) else value),
    StringConstraints(max_length=2_048, pattern=r"^https?://[^\s]+$"),
]
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Latitude = Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(strict=True, ge=-180, le=180, allow_inf_nan=False)]


def _optional_positive_int(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return value
    return value if value > 0 else None


def _optional_non_negative_number(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    return float(value) if value >= 0 else None


def _nullish(value: object) -> object:
    return None if value is None or value == "" or value == "NULL" else value


OptionalPositiveInt = Annotated[int | None, BeforeValidator(_optional_positive_int)]
OptionalNonNegativeNumber = Annotated[
    float | None, BeforeValidator(_optional_non_negative_number)
]
NullableText = Annotated[
    Annotated[str, Field(strict=False), StringConstraints(max_length=500)] | None,
    BeforeValidator(_nullish),
]
NullableInt = Annotated[
    Annotated[int, Field(strict=False)] | None,
    BeforeValidator(_nullish),
]
NullableNonNegativeInt = Annotated[
    Annotated[int, Field(strict=False, ge=0)] | None,
    BeforeValidator(_nullish),
]
NullableFloat = Annotated[
    Annotated[float, Field(strict=False, allow_inf_nan=False)] | None,
    BeforeValidator(_nullish),
]
NullableBool = Annotated[
    Annotated[bool, Field(strict=False)] | None,
    BeforeValidator(_nullish),
]


class WireModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        populate_by_name=True,
        coerce_numbers_to_str=True,
        strict=True,
    )


class ClosedWireModel(WireModel):
    """Wire-derived records whose fields must be exact after decoding."""

    model_config = ConfigDict(extra="forbid")
