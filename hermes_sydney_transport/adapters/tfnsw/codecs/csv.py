"""The sole bounded CSV grammar for TfNSW adapters."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from io import TextIOBase

from pydantic import BaseModel, ConfigDict, Field

from ....models.errors import DomainError


class CsvSpec(BaseModel):
    """Declarative table shape and resource limits."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1, max_length=100)
    required_headers: frozenset[str] = Field(default_factory=frozenset, max_length=40)
    max_rows: int = Field(ge=1, le=10_000_000)
    max_field_chars: int = Field(default=8_192, ge=1, le=65_536)


def rows(source: TextIOBase, spec: CsvSpec) -> Iterator[dict[str, str | None]]:
    """Yield bounded dictionaries and fail closed with one stable error."""

    try:
        reader = csv.DictReader(source)
        if not spec.required_headers.issubset(reader.fieldnames or ()):
            raise ValueError("required headers are missing")
        for index, row in enumerate(reader, start=1):
            if index > spec.max_rows:
                raise ValueError("row limit exceeded")
            if any(
                value is not None and len(value) > spec.max_field_chars
                for value in row.values()
            ):
                raise ValueError("field limit exceeded")
            yield row
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        raise DomainError(
            "static_data_invalid", f"TfNSW {spec.name} CSV is invalid."
        ) from exc
