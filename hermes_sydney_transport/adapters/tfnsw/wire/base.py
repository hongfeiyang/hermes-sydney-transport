"""Reusable strict scalar contracts for TfNSW wire models."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AwareDatetime,
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


def _has_explicit_offset(value: str) -> bool:
    suffix = value[10:]
    return value.endswith("Z") or "+" in suffix or "-" in suffix


def _optional_timestamp(value: object) -> object:
    if value is None or value == 0:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not 0 < value <= 4_102_444_800_000:
            raise ValueError("epoch milliseconds are outside the supported range")
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str) and ("T" not in value or not _has_explicit_offset(value)):
        raise ValueError("timestamps must be an ISO 8601 date-time with an offset")
    return value


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


def _timestamp_text(value: object) -> object:
    if isinstance(value, bool | int | float):
        # Pydantic deliberately does not wrap TypeError raised by validators.
        raise ValueError("timestamp must be an ISO 8601 string")  # noqa: TRY004
    if not isinstance(value, str):
        return value
    normalized = value.strip().replace(" ", "T", 1)
    return f"{normalized}:00" if re.search(r"[+-]\d{2}$", normalized) else normalized


OptionalEpochMillis = Annotated[
    Annotated[AwareDatetime, Field(strict=False)] | None,
    BeforeValidator(_optional_timestamp),
]
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
WireTimestamp = Annotated[
    datetime,
    BeforeValidator(_timestamp_text),
    Field(strict=False),
]
NullableTimestamp = Annotated[WireTimestamp | None, BeforeValidator(_nullish)]


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
