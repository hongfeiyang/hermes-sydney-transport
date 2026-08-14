"""Compose archive, CSV, and Pydantic contracts into one GTFS decoder."""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, TypeAdapter, ValidationError

from ....models.errors import DomainError
from ..wire.gtfs import (
    CalendarDateRow,
    CalendarRow,
    RouteRow,
    StopRow,
    StopTimeRow,
    TripRow,
)
from .archive import ArchiveSource, ArchiveSpec, open_archive, open_text_table
from .csv import CsvSpec, rows
from .static_specs import (
    COMPLETE_GTFS_ARCHIVE,
    COMPLETE_GTFS_TABLES,
    STATIC_GTFS_ARCHIVE,
    STATIC_GTFS_TABLES,
)


def gtfs_rows[RowT: BaseModel](
    source: ArchiveSource,
    archive_spec: ArchiveSpec,
    table_spec: CsvSpec,
    row_type: type[RowT],
) -> Iterator[RowT]:
    """Decode a bounded GTFS table directly into its declared row model."""

    adapter = TypeAdapter(row_type)
    try:
        with (
            open_archive(source, archive_spec) as archive,
            open_text_table(archive, table_spec.name) as text,
        ):
            for row in rows(text, table_spec):
                yield adapter.validate_python(row)
    except ValidationError as exc:
        raise DomainError(
            "static_data_invalid",
            f"TfNSW {table_spec.name} does not match its GTFS row contract.",
        ) from exc


def gtfs_time_seconds(value: str) -> int:
    """Convert already-validated GTFS service time text to seconds."""

    hour, minute, second = map(int, value.split(":"))
    return hour * 3600 + minute * 60 + second


def static_routes(source: ArchiveSource) -> Iterator[RouteRow]:
    return gtfs_rows(
        source, STATIC_GTFS_ARCHIVE, STATIC_GTFS_TABLES["routes.txt"], RouteRow
    )


def static_stops(source: ArchiveSource) -> Iterator[StopRow]:
    return gtfs_rows(
        source, STATIC_GTFS_ARCHIVE, STATIC_GTFS_TABLES["stops.txt"], StopRow
    )


def static_trips(source: ArchiveSource) -> Iterator[TripRow]:
    return gtfs_rows(
        source, STATIC_GTFS_ARCHIVE, STATIC_GTFS_TABLES["trips.txt"], TripRow
    )


def static_stop_times(source: ArchiveSource) -> Iterator[StopTimeRow]:
    return gtfs_rows(
        source,
        STATIC_GTFS_ARCHIVE,
        STATIC_GTFS_TABLES["stop_times.txt"],
        StopTimeRow,
    )


def complete_routes(source: ArchiveSource) -> Iterator[RouteRow]:
    return gtfs_rows(
        source, COMPLETE_GTFS_ARCHIVE, COMPLETE_GTFS_TABLES["routes.txt"], RouteRow
    )


def complete_stops(source: ArchiveSource) -> Iterator[StopRow]:
    return gtfs_rows(
        source, COMPLETE_GTFS_ARCHIVE, COMPLETE_GTFS_TABLES["stops.txt"], StopRow
    )


def complete_trips(source: ArchiveSource) -> Iterator[TripRow]:
    return gtfs_rows(
        source, COMPLETE_GTFS_ARCHIVE, COMPLETE_GTFS_TABLES["trips.txt"], TripRow
    )


def complete_stop_times(source: ArchiveSource) -> Iterator[StopTimeRow]:
    return gtfs_rows(
        source,
        COMPLETE_GTFS_ARCHIVE,
        COMPLETE_GTFS_TABLES["stop_times.txt"],
        StopTimeRow,
    )


def complete_calendar(source: ArchiveSource) -> Iterator[CalendarRow]:
    return gtfs_rows(
        source,
        COMPLETE_GTFS_ARCHIVE,
        COMPLETE_GTFS_TABLES["calendar.txt"],
        CalendarRow,
    )


def complete_calendar_dates(source: ArchiveSource) -> Iterator[CalendarDateRow]:
    return gtfs_rows(
        source,
        COMPLETE_GTFS_ARCHIVE,
        COMPLETE_GTFS_TABLES["calendar_dates.txt"],
        CalendarDateRow,
    )
