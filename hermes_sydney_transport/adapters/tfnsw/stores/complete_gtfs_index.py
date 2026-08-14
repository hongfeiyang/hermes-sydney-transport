"""SQLite schema and loaders for the Complete GTFS timetable index."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from ....models.errors import DomainError
from ..codecs.gtfs import (
    complete_calendar,
    complete_calendar_dates,
    complete_routes,
    complete_stop_times,
    complete_stops,
    complete_trips,
)

SCHEMA_VERSION = "1"
_INSERT_BATCH = 2_000


def build_complete_index(
    database_path: Path, archive_path: Path, last_modified: datetime | None
) -> None:
    connection = _connect(database_path)
    try:
        _create_schema(connection)
        _insert(
            connection,
            "INSERT INTO routes VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    row.route_id,
                    row.agency_id,
                    row.route_short_name,
                    row.route_long_name,
                    row.route_desc,
                    row.route_type,
                )
                for row in complete_routes(archive_path)
            ),
        )
        _insert(
            connection,
            "INSERT INTO stops VALUES (?, ?)",
            ((row.stop_id, row.stop_name) for row in complete_stops(archive_path)),
        )
        _load_service_calendar(connection, archive_path)
        _insert(
            connection,
            "INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    row.trip_id,
                    row.route_id,
                    row.service_id,
                    row.trip_headsign,
                    row.direction_id,
                    row.wheelchair_accessible,
                )
                for row in complete_trips(archive_path)
            ),
        )
        _insert(
            connection,
            "INSERT INTO stop_times VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    row.trip_id,
                    row.arrival_time,
                    row.departure_time,
                    row.stop_id,
                    row.stop_sequence,
                    row.pickup_type,
                    row.drop_off_type,
                )
                for row in complete_stop_times(archive_path)
            ),
        )
        _create_indexes(connection)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", SCHEMA_VERSION),
                ("last_modified", last_modified.isoformat() if last_modified else ""),
            ),
        )
        connection.commit()
    except (DomainError, OSError, sqlite3.Error) as exc:
        connection.rollback()
        if isinstance(exc, DomainError):
            raise
        raise DomainError(
            "static_data_invalid", "TfNSW Complete GTFS could not be indexed."
        ) from exc
    finally:
        connection.close()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE routes (
            route_id TEXT PRIMARY KEY, agency_id TEXT, route_short_name TEXT,
            route_long_name TEXT, route_desc TEXT, route_type INTEGER
        );
        CREATE TABLE stops (stop_id TEXT PRIMARY KEY, stop_name TEXT);
        CREATE TABLE calendar (
            service_id TEXT PRIMARY KEY,
            monday INTEGER NOT NULL, tuesday INTEGER NOT NULL,
            wednesday INTEGER NOT NULL, thursday INTEGER NOT NULL,
            friday INTEGER NOT NULL, saturday INTEGER NOT NULL,
            sunday INTEGER NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL
        );
        CREATE TABLE calendar_dates (
            service_id TEXT NOT NULL, service_date TEXT NOT NULL,
            exception_type INTEGER NOT NULL, PRIMARY KEY (service_id, service_date)
        );
        CREATE TABLE trips (
            trip_id TEXT PRIMARY KEY, route_id TEXT NOT NULL,
            service_id TEXT NOT NULL, trip_headsign TEXT,
            direction_id INTEGER, wheelchair_accessible INTEGER
        );
        CREATE TABLE stop_times (
            trip_id TEXT NOT NULL, arrival_time TEXT, departure_time TEXT,
            stop_id TEXT NOT NULL, stop_sequence INTEGER NOT NULL,
            pickup_type INTEGER, drop_off_type INTEGER
        );
        """
    )


def _load_service_calendar(connection: sqlite3.Connection, archive_path: Path) -> None:
    _insert(
        connection,
        "INSERT INTO calendar VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (
                row.service_id,
                row.monday,
                row.tuesday,
                row.wednesday,
                row.thursday,
                row.friday,
                row.saturday,
                row.sunday,
                row.start_date,
                row.end_date,
            )
            for row in complete_calendar(archive_path)
        ),
    )
    _insert(
        connection,
        "INSERT OR REPLACE INTO calendar_dates VALUES (?, ?, ?)",
        (
            (row.service_id, row.date, row.exception_type)
            for row in complete_calendar_dates(archive_path)
        ),
    )


def _create_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX trips_route_direction ON trips (route_id, direction_id, service_id);
        CREATE INDEX calendar_dates_service_date
            ON calendar_dates (service_id, service_date, exception_type);
        CREATE INDEX stop_times_trip_sequence
            ON stop_times (trip_id, stop_sequence);
        CREATE INDEX stop_times_stop_trip ON stop_times (stop_id, trip_id);
        """
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
