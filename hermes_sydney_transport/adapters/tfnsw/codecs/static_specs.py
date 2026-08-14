"""Declarative grammars and resource ceilings for TfNSW static datasets."""

from __future__ import annotations

from .archive import ArchiveSpec
from .csv import CsvSpec
from .xlsx import XlsxSpec

_GTFS_LIMITS = {
    "routes.txt": 32 * 1024 * 1024,
    "stops.txt": 64 * 1024 * 1024,
    "trips.txt": 128 * 1024 * 1024,
    "stop_times.txt": 512 * 1024 * 1024,
}

STATIC_GTFS_ARCHIVE = ArchiveSpec(
    required_files=frozenset(_GTFS_LIMITS),
    max_uncompressed_bytes=_GTFS_LIMITS,
    max_compression_ratio=200,
)
COMPLETE_GTFS_ARCHIVE = ArchiveSpec(
    required_files=frozenset((*_GTFS_LIMITS, "calendar.txt", "calendar_dates.txt")),
    max_uncompressed_bytes={
        **_GTFS_LIMITS,
        "calendar.txt": 16 * 1024 * 1024,
        "calendar_dates.txt": 64 * 1024 * 1024,
    },
    max_compression_ratio=300,
)

STATIC_GTFS_TABLES = {
    "routes.txt": CsvSpec(name="routes.txt", max_rows=100_000),
    "stops.txt": CsvSpec(name="stops.txt", max_rows=500_000),
    "trips.txt": CsvSpec(name="trips.txt", max_rows=2_000_000),
    "stop_times.txt": CsvSpec(name="stop_times.txt", max_rows=8_000_000),
}
COMPLETE_GTFS_TABLES = {
    **STATIC_GTFS_TABLES,
    "routes.txt": CsvSpec(name="routes.txt", max_rows=200_000),
    "calendar.txt": CsvSpec(name="calendar.txt", max_rows=500_000),
    "calendar_dates.txt": CsvSpec(name="calendar_dates.txt", max_rows=2_000_000),
}

FACILITIES_CSV = CsvSpec(
    name="location facilities",
    required_headers=frozenset(
        {
            "LOCATION_NAME",
            "TSN",
            "EFA_ID",
            "ACCESSIBILITY",
            "FACILITIES",
            "TRANSPORT_MODE",
        }
    ),
    max_rows=20_000,
)
LIFTS_XLSX = XlsxSpec(
    sheet_path="xl/worksheets/sheet1.xml",
    required_headers=frozenset(
        {
            "tsn",
            "_updated_at",
            "sydney_trains__lift_functional_location_code",
        }
    ),
    max_rows=20_000,
)
