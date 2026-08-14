"""SQLite index builder for mode-specific static GTFS archives."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from ....models.errors import DomainError
from ..codecs.gtfs import static_routes, static_stop_times, static_stops, static_trips

_SCHEMA_VERSION = "1"
_INSERT_BATCH = 2_000


def build_static_index(
    connection: sqlite3.Connection,
    archives: tuple[bytes, ...],
    last_modified: str | None,
) -> None:
    """Build one all-or-nothing index; later archives are authoritative."""

    try:
        _create_schema(connection)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", _SCHEMA_VERSION),
                ("last_modified", last_modified or ""),
            ),
        )
        for archive in archives:
            _load_routes(connection, archive)
            _load_stops(connection, archive)
        for archive in archives:
            _load_trips(connection, archive)
            _load_stop_times(connection, archive)
        connection.execute(
            "CREATE INDEX stop_times_trip_sequence ON stop_times (trip_id, stop_sequence)"
        )
        connection.commit()
    except (DomainError, sqlite3.Error) as exc:
        connection.rollback()
        if isinstance(exc, DomainError):
            raise
        raise DomainError(
            "static_data_invalid", "TfNSW static GTFS tables could not be indexed."
        ) from exc


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE routes (
            route_id TEXT PRIMARY KEY, agency_id TEXT, route_type INTEGER,
            route_short_name TEXT, route_long_name TEXT
        );
        CREATE TABLE stops (
            stop_id TEXT PRIMARY KEY, stop_name TEXT,
            parent_station TEXT, platform_code TEXT
        );
        CREATE TABLE trips (
            trip_id TEXT PRIMARY KEY, service_id TEXT, route_id TEXT,
            trip_headsign TEXT, direction_id INTEGER, vehicle_category_id TEXT
        );
        CREATE TABLE stop_times (
            trip_id TEXT NOT NULL, stop_sequence INTEGER NOT NULL,
            arrival_time TEXT, departure_time TEXT, stop_id TEXT NOT NULL,
            stop_headsign TEXT
        );
        """
    )


def _load_routes(connection: sqlite3.Connection, archive: bytes) -> None:
    _insert(
        connection,
        "INSERT OR REPLACE INTO routes VALUES (?, ?, ?, ?, ?)",
        (
            (
                row.route_id,
                row.agency_id,
                row.route_type,
                row.route_short_name,
                row.route_long_name,
            )
            for row in static_routes(archive)
        ),
    )


def _load_stops(connection: sqlite3.Connection, archive: bytes) -> None:
    _insert(
        connection,
        "INSERT OR REPLACE INTO stops VALUES (?, ?, ?, ?)",
        (
            (row.stop_id, row.stop_name, row.parent_station, row.platform_code)
            for row in static_stops(archive)
        ),
    )


def _load_trips(connection: sqlite3.Connection, archive: bytes) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS archive_trips;
        CREATE TEMP TABLE archive_trips (
            trip_id TEXT PRIMARY KEY, service_id TEXT, route_id TEXT,
            trip_headsign TEXT, direction_id INTEGER, vehicle_category_id TEXT
        );
        """
    )
    _insert(
        connection,
        "INSERT OR REPLACE INTO archive_trips VALUES (?, ?, ?, ?, ?, ?)",
        (
            (
                row.trip_id,
                row.service_id,
                row.route_id,
                row.trip_headsign,
                row.direction_id,
                row.vehicle_category_id,
            )
            for row in static_trips(archive)
        ),
    )
    connection.execute(
        "DELETE FROM stop_times WHERE trip_id IN (SELECT trip_id FROM archive_trips)"
    )
    connection.execute("INSERT OR REPLACE INTO trips SELECT * FROM archive_trips")


def _load_stop_times(connection: sqlite3.Connection, archive: bytes) -> None:
    _insert(
        connection,
        "INSERT INTO stop_times VALUES (?, ?, ?, ?, ?, ?)",
        (
            (
                row.trip_id,
                row.stop_sequence,
                row.arrival_time,
                row.departure_time,
                row.stop_id,
                row.stop_headsign,
            )
            for row in static_stop_times(archive)
        ),
    )


def _insert(
    connection: sqlite3.Connection,
    statement: str,
    values: Iterator[tuple[object, ...]],
) -> None:
    batch: list[tuple[object, ...]] = []
    for value in values:
        batch.append(value)
        if len(batch) == _INSERT_BATCH:
            connection.executemany(statement, batch)
            batch.clear()
    if batch:
        connection.executemany(statement, batch)
