"""Single declarative timestamp contract for every TfNSW wire model."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AwareDatetime, BeforeValidator, StringConstraints, TypeAdapter

_AWARE_DATETIME: TypeAdapter[datetime] = TypeAdapter(AwareDatetime)
_TIMESTAMP_TEXT: TypeAdapter[str] = TypeAdapter(
    Annotated[
        str,
        StringConstraints(
            max_length=64,
            pattern=(
                r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
                r"(?:Z| UTC|[+-]\d{2}(?::?\d{2})?)$"
            ),
        ),
    ]
)
_MAX_EPOCH_MILLISECONDS = 4_102_444_800_000


def _normalise_timestamp_text(value: str) -> str:
    text = _TIMESTAMP_TEXT.validate_python(value.strip(), strict=True)
    if text.endswith(" UTC"):
        text = f"{text[:-4]}+00:00"
    normalized = text.replace(" ", "T", 1)
    if re.search(r"[+-]\d{2}$", normalized):
        return f"{normalized}:00"
    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)


def _parse_wire_timestamp(value: object) -> datetime:
    if not isinstance(value, str | datetime) or isinstance(value, bool):
        raise ValueError("timestamp must be an ISO 8601 string")  # noqa: TRY004
    candidate = _normalise_timestamp_text(value) if isinstance(value, str) else value
    return _AWARE_DATETIME.validate_python(candidate, strict=False)


def _parse_nullable_timestamp(value: object) -> datetime | None:
    if value is None or value == "" or value == "NULL":
        return None
    return _parse_wire_timestamp(value)


def _parse_optional_provider_timestamp(value: object) -> datetime | None:
    if value is None or value == 0:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        if not 0 < value <= _MAX_EPOCH_MILLISECONDS:
            raise ValueError("epoch milliseconds are outside the supported range")
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return _parse_wire_timestamp(value)


WireTimestamp = Annotated[AwareDatetime, BeforeValidator(_parse_wire_timestamp)]
NullableTimestamp = Annotated[
    WireTimestamp | None,
    BeforeValidator(_parse_nullable_timestamp),
]
OptionalProviderTimestamp = Annotated[
    WireTimestamp | None,
    BeforeValidator(_parse_optional_provider_timestamp),
]
