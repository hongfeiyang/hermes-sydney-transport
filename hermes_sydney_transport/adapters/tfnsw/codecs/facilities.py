"""Compose bounded table readers with facility wire contracts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ....models.errors import DomainError
from ..wire.facilities import (
    FacilityCsvRow,
    LiftSheetRow,
    StoredFacility,
    StoredFacilitySnapshot,
    StoredLift,
)
from .csv import rows
from .static_specs import FACILITIES_CSV, LIFTS_XLSX
from .xlsx import named_rows

__all__ = [
    "FacilityCsvRow",
    "LiftSheetRow",
    "StoredFacility",
    "StoredFacilitySnapshot",
    "StoredLift",
    "facility_rows",
    "lift_rows",
]


def facility_rows(path: Path) -> Iterator[FacilityCsvRow]:
    adapter = TypeAdapter(FacilityCsvRow)
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            for row in rows(source, FACILITIES_CSV):
                yield adapter.validate_python(row)
    except (OSError, ValidationError) as exc:
        raise DomainError(
            "static_data_invalid",
            "TfNSW location-facility data does not match its contract.",
        ) from exc


def lift_rows(path: Path) -> Iterator[LiftSheetRow]:
    adapter = TypeAdapter(LiftSheetRow)
    try:
        for row in named_rows(path, LIFTS_XLSX):
            decoded = adapter.validate_python(row)
            if decoded.tsn is not None:
                yield decoded
    except ValidationError as exc:
        raise DomainError(
            "static_data_invalid",
            "TfNSW lift inventory does not match its contract.",
        ) from exc
