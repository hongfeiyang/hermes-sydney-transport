"""Indexed route timetable adapter over the TfNSW Complete GTFS bundle."""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

from ...models.errors import DomainError
from ...models.static_inputs import RouteTimetableInput
from ...ports.timetable import (
    RouteTimetablePort,
    RouteTimetableSnapshot,
    TimetableRouteRecord,
    TimetableStopRecord,
    TimetableTripRecord,
)
from .static_resources import StaticResourceTransport

_SYDNEY = ZoneInfo("Australia/Sydney")
_SCHEMA_VERSION = "1"
_REFRESH_SECONDS = 6 * 60 * 60
_MAX_STOP_TIMES_PER_TRIP = 100
_INSERT_BATCH = 2_000
_MAX_FIELD_CHARS = 8_192
_REQUIRED_FILES = frozenset(
    {
        "routes.txt",
        "stops.txt",
        "calendar.txt",
        "calendar_dates.txt",
        "trips.txt",
        "stop_times.txt",
    }
)
_MAX_UNCOMPRESSED_BYTES = {
    "routes.txt": 32 * 1024 * 1024,
    "stops.txt": 64 * 1024 * 1024,
    "calendar.txt": 16 * 1024 * 1024,
    "calendar_dates.txt": 64 * 1024 * 1024,
    "trips.txt": 128 * 1024 * 1024,
    "stop_times.txt": 512 * 1024 * 1024,
}
_MAX_ROWS = {
    "routes.txt": 200_000,
    "stops.txt": 500_000,
    "calendar.txt": 500_000,
    "calendar_dates.txt": 2_000_000,
    "trips.txt": 2_000_000,
    "stop_times.txt": 8_000_000,
}
_MAX_COMPRESSION_RATIO = 300
_WEEKDAY_COLUMNS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class CompleteGtfsTimetableAdapter(RouteTimetablePort):
    """Refresh a Complete GTFS SQLite index atomically and query exact route IDs."""

    def __init__(
        self,
        transport: StaticResourceTransport,
        *,
        database_path: Path,
    ) -> None:
        self._transport = transport
        self._database_path = database_path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._checked_at: float | None = None
        self._cache_stale = False

    def get_route_timetable(
        self, request: RouteTimetableInput, service_date: date
    ) -> RouteTimetableSnapshot:
        with self._lock:
            self._refresh_if_needed()
            connection = self._require_connection()
            route = _select_route(connection, request.route_id)
            if route is None:
                return RouteTimetableSnapshot(
                    route=None,
                    service_date=service_date,
                    trips=(),
                    source_updated_at=_metadata_datetime(connection, "last_modified"),
                    cache_stale=self._cache_stale,
                )
            trips = tuple(
                _trip_record(connection, row, service_date)
                for row in _select_trips(connection, request, service_date)
            )
            return RouteTimetableSnapshot(
                route=route,
                service_date=service_date,
                trips=trips,
                source_updated_at=_metadata_datetime(connection, "last_modified"),
                cache_stale=self._cache_stale,
            )

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _refresh_if_needed(self) -> None:
        now = time.monotonic()
        self._open_existing()
        if self._checked_at is not None and now - self._checked_at < _REFRESH_SECONDS:
            return
        has_cache = self._connection is not None
        try:
            self._refresh()
        except DomainError:
            if not has_cache:
                raise
            self._cache_stale = True
        self._checked_at = now

    def _refresh(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        previous = (
            _metadata_datetime(self._connection, "last_modified")
            if self._connection is not None
            else None
        )
        with tempfile.TemporaryDirectory(
            prefix=".complete-gtfs-refresh-", dir=self._database_path.parent
        ) as directory:
            archive_path = Path(directory) / "complete-gtfs.zip"
            download = self._transport.download(
                "complete_gtfs", archive_path, if_modified_since=previous
            )
            if download.not_modified:
                if self._connection is None:
                    raise DomainError(
                        "static_data_unavailable",
                        "TfNSW returned not-modified without a Complete GTFS cache.",
                    )
                self._cache_stale = False
                return
            temporary_index = Path(directory) / "complete-gtfs.sqlite3"
            _build_index(temporary_index, archive_path, download.last_modified)
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            os.replace(temporary_index, self._database_path)
            self._connection = _connect(self._database_path)
            self._cache_stale = False

    def _open_existing(self) -> None:
        if self._connection is not None or not self._database_path.is_file():
            return
        connection = _connect(self._database_path)
        try:
            if _metadata(connection, "schema_version") != _SCHEMA_VERSION:
                connection.close()
                return
        except sqlite3.Error:
            connection.close()
            return
        self._connection = connection

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DomainError(
                "static_data_unavailable", "Complete GTFS index is unavailable."
            )
        return self._connection


def _build_index(
    database_path: Path, archive_path: Path, last_modified: datetime | None
) -> None:
    connection = _connect(database_path)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _validate_archive(archive)
            _create_schema(connection)
            _load_routes(connection, archive)
            _load_stops(connection, archive)
            _load_calendar(connection, archive)
            _load_calendar_dates(connection, archive)
            _load_trips(connection, archive)
            _load_stop_times(connection, archive)
            _create_indexes(connection)
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                (
                    ("schema_version", _SCHEMA_VERSION),
                    (
                        "last_modified",
                        last_modified.isoformat() if last_modified else "",
                    ),
                ),
            )
            connection.commit()
    except (
        KeyError,
        UnicodeError,
        csv.Error,
        sqlite3.Error,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        connection.rollback()
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
            exception_type INTEGER NOT NULL,
            PRIMARY KEY (service_id, service_date)
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


def _create_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX trips_route_direction
            ON trips (route_id, direction_id, service_id);
        CREATE INDEX calendar_dates_service_date
            ON calendar_dates (service_id, service_date, exception_type);
        CREATE INDEX stop_times_trip_sequence
            ON stop_times (trip_id, stop_sequence);
        CREATE INDEX stop_times_stop_trip
            ON stop_times (stop_id, trip_id);
        """
    )


def _load_routes(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    _batched_insert(
        connection,
        "INSERT INTO routes VALUES (?, ?, ?, ?, ?, ?)",
        (
            (
                _required(row, "route_id"),
                _optional(row.get("agency_id")),
                _optional(row.get("route_short_name")),
                _optional(row.get("route_long_name")),
                _optional(row.get("route_desc")),
                _bounded_int(row.get("route_type"), minimum=0, maximum=2_000),
            )
            for row in _rows(archive, "routes.txt")
        ),
    )


def _load_stops(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    _batched_insert(
        connection,
        "INSERT INTO stops VALUES (?, ?)",
        (
            (_required(row, "stop_id"), _optional(row.get("stop_name")))
            for row in _rows(archive, "stops.txt")
        ),
    )


def _load_calendar(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    def values() -> Iterator[tuple[object, ...]]:
        for row in _rows(archive, "calendar.txt"):
            days = tuple(_binary_int(row.get(name)) for name in _WEEKDAY_COLUMNS)
            start = _gtfs_date(_required(row, "start_date"))
            end = _gtfs_date(_required(row, "end_date"))
            if start > end:
                raise ValueError("calendar start_date is after end_date")
            yield (_required(row, "service_id"), *days, start, end)

    _batched_insert(
        connection,
        "INSERT INTO calendar VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        values(),
    )


def _load_calendar_dates(
    connection: sqlite3.Connection, archive: zipfile.ZipFile
) -> None:
    _batched_insert(
        connection,
        "INSERT OR REPLACE INTO calendar_dates VALUES (?, ?, ?)",
        (
            (
                _required(row, "service_id"),
                _gtfs_date(_required(row, "date")),
                _choice_int(row.get("exception_type"), {1, 2}),
            )
            for row in _rows(archive, "calendar_dates.txt")
        ),
    )


def _load_trips(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    _batched_insert(
        connection,
        "INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?)",
        (
            (
                _required(row, "trip_id"),
                _required(row, "route_id"),
                _required(row, "service_id"),
                _optional(row.get("trip_headsign")),
                _optional_choice_int(row.get("direction_id"), {0, 1}),
                _optional_choice_int(row.get("wheelchair_accessible"), {0, 1, 2}),
            )
            for row in _rows(archive, "trips.txt")
        ),
    )


def _load_stop_times(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    def values() -> Iterator[tuple[object, ...]]:
        for row in _rows(archive, "stop_times.txt"):
            arrival = _optional_gtfs_time(row.get("arrival_time"))
            departure = _optional_gtfs_time(row.get("departure_time"))
            if arrival is None and departure is None:
                raise ValueError("stop time has neither arrival nor departure")
            yield (
                _required(row, "trip_id"),
                arrival,
                departure,
                _required(row, "stop_id"),
                _bounded_int(row.get("stop_sequence"), minimum=0, maximum=10_000),
                _optional_choice_int(row.get("pickup_type"), {0, 1, 2, 3}),
                _optional_choice_int(row.get("drop_off_type"), {0, 1, 2, 3}),
            )

    _batched_insert(
        connection,
        "INSERT INTO stop_times VALUES (?, ?, ?, ?, ?, ?, ?)",
        values(),
    )


def _batched_insert(
    connection: sqlite3.Connection, statement: str, rows: Iterator[tuple[object, ...]]
) -> None:
    batch: list[tuple[object, ...]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == _INSERT_BATCH:
            connection.executemany(statement, batch)
            batch.clear()
    if batch:
        connection.executemany(statement, batch)


def _select_route(
    connection: sqlite3.Connection, route_id: str
) -> TimetableRouteRecord | None:
    row = connection.execute(
        "SELECT * FROM routes WHERE route_id = ?", (route_id,)
    ).fetchone()
    if row is None:
        return None
    return TimetableRouteRecord(
        id=str(row["route_id"]),
        agency_id=row["agency_id"],
        short_name=row["route_short_name"],
        long_name=row["route_long_name"],
        description=row["route_desc"],
        route_type=row["route_type"],
    )


def _select_trips(
    connection: sqlite3.Connection, request: RouteTimetableInput, service_date: date
) -> tuple[sqlite3.Row, ...]:
    weekday = _WEEKDAY_COLUMNS[service_date.weekday()]
    date_text = service_date.strftime("%Y%m%d")
    clauses = ["t.route_id = ?"]
    parameters: list[object] = [request.route_id]
    if request.direction_id is not None:
        clauses.append("t.direction_id = ?")
        parameters.append(request.direction_id)
    if request.stop_id is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM stop_times AS sf "
            "WHERE sf.trip_id = t.trip_id AND sf.stop_id = ?)"
        )
        parameters.append(request.stop_id)
    parameters.extend((date_text, date_text, date_text, request.limit))
    rows = connection.execute(
        f"""
        SELECT t.*,
               (SELECT COALESCE(s.departure_time, s.arrival_time)
                  FROM stop_times AS s WHERE s.trip_id = t.trip_id
                 ORDER BY s.stop_sequence LIMIT 1) AS first_departure,
               (SELECT COALESCE(s.arrival_time, s.departure_time)
                  FROM stop_times AS s WHERE s.trip_id = t.trip_id
                 ORDER BY s.stop_sequence DESC LIMIT 1) AS last_arrival
          FROM trips AS t
          LEFT JOIN calendar AS c ON c.service_id = t.service_id
         WHERE {" AND ".join(clauses)}
           AND COALESCE(
                (SELECT CASE cd.exception_type WHEN 1 THEN 1 WHEN 2 THEN 0 END
                   FROM calendar_dates AS cd
                  WHERE cd.service_id = t.service_id AND cd.service_date = ?
                  LIMIT 1),
                CASE WHEN c.start_date <= ? AND c.end_date >= ?
                     THEN c.{weekday} ELSE 0 END
           ) = 1
         ORDER BY COALESCE(first_departure, '99:99:99'), t.trip_id
         LIMIT ?
        """,
        tuple(parameters),
    ).fetchall()
    return tuple(rows)


def _trip_record(
    connection: sqlite3.Connection, row: sqlite3.Row, service_date: date
) -> TimetableTripRecord:
    stop_rows = connection.execute(
        """
        SELECT st.*, s.stop_name
          FROM stop_times AS st LEFT JOIN stops AS s ON s.stop_id = st.stop_id
         WHERE st.trip_id = ? ORDER BY st.stop_sequence LIMIT ?
        """,
        (row["trip_id"], _MAX_STOP_TIMES_PER_TRIP + 1),
    ).fetchall()
    truncated = len(stop_rows) > _MAX_STOP_TIMES_PER_TRIP
    selected = stop_rows[:_MAX_STOP_TIMES_PER_TRIP]
    stops = tuple(
        TimetableStopRecord(
            stop_id=str(item["stop_id"]),
            stop_name=item["stop_name"],
            sequence=int(item["stop_sequence"]),
            arrival=_service_datetime(service_date, item["arrival_time"]),
            departure=_service_datetime(service_date, item["departure_time"]),
            pickup_type=item["pickup_type"],
            drop_off_type=item["drop_off_type"],
        )
        for item in selected
    )
    wheelchair = {1: "accessible", 2: "not_accessible"}.get(
        row["wheelchair_accessible"], "unknown"
    )
    return TimetableTripRecord(
        trip_id=str(row["trip_id"]),
        headsign=row["trip_headsign"],
        direction_id=row["direction_id"],
        wheelchair_accessibility=wheelchair,
        first_departure=_service_datetime(service_date, row["first_departure"]),
        last_arrival=_service_datetime(service_date, row["last_arrival"]),
        stop_times=stops,
        stop_times_truncated=truncated,
    )


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str | None]]:
    with (
        archive.open(name) as raw,
        io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text,
    ):
        for index, row in enumerate(csv.DictReader(text), start=1):
            if index > _MAX_ROWS[name]:
                raise ValueError(f"{name} exceeds its row limit")
            if any(
                value is not None and len(value) > _MAX_FIELD_CHARS
                for value in row.values()
            ):
                raise ValueError(f"{name} contains an oversized field")
            yield row


def _validate_archive(archive: zipfile.ZipFile) -> None:
    by_name: dict[str, list[zipfile.ZipInfo]] = {}
    for item in archive.infolist():
        by_name.setdefault(item.filename, []).append(item)
    if not _REQUIRED_FILES.issubset(by_name):
        raise ValueError("Complete GTFS is missing required tables")
    for name in _REQUIRED_FILES:
        matches = by_name[name]
        if len(matches) != 1:
            raise ValueError(f"Complete GTFS contains duplicate {name}")
        item = matches[0]
        if item.file_size > _MAX_UNCOMPRESSED_BYTES[name]:
            raise ValueError(f"Complete GTFS {name} exceeds expanded-size limit")
        if item.file_size / max(item.compress_size, 1) > _MAX_COMPRESSION_RATIO:
            raise ValueError(f"Complete GTFS {name} compression ratio is unsafe")


def _service_datetime(service_date: date, value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    seconds = _gtfs_time_seconds(value)
    return datetime.combine(service_date, datetime_time(), tzinfo=_SYDNEY) + timedelta(
        seconds=seconds
    )


def _optional_gtfs_time(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("GTFS time must be text")  # noqa: TRY004
    _gtfs_time_seconds(value)
    return value


def _gtfs_time_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("GTFS time has invalid shape")
    hour, minute, second = (int(part) for part in parts)
    if hour not in range(48) or minute not in range(60) or second not in range(60):
        raise ValueError("GTFS time is out of range")
    return hour * 3600 + minute * 60 + second


def _gtfs_date(value: str) -> str:
    if len(value) != 8 or not value.isascii() or not value.isdecimal():
        raise ValueError("GTFS date has invalid shape")
    parsed = date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return parsed.strftime("%Y%m%d")


def _required(row: dict[str, str | None], key: str) -> str:
    value = row.get(key)
    if not value:
        raise ValueError(f"GTFS {key} is required")
    return value


def _optional(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _binary_int(value: object) -> int:
    return _choice_int(value, {0, 1})


def _choice_int(value: object, allowed: set[int]) -> int:
    parsed = _bounded_int(value, minimum=min(allowed), maximum=max(allowed))
    if parsed not in allowed:
        raise ValueError("GTFS integer is outside its vocabulary")
    return parsed


def _optional_choice_int(value: object, allowed: set[int]) -> int | None:
    if value in {None, ""}:
        return None
    return _choice_int(value, allowed)


def _bounded_int(value: object, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError("GTFS integer is absent")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError("GTFS integer is out of range")
    return parsed


def _metadata(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = ?", (key,)
    ).fetchone()
    return str(row[0]) if row is not None else None


def _metadata_datetime(
    connection: sqlite3.Connection | None, key: str
) -> datetime | None:
    if connection is None:
        return None
    value = _metadata(connection, key)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
