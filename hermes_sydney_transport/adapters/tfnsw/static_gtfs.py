"""Thread-safe, indexed repository over TfNSW static GTFS archives."""

from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import tempfile
import threading
import time
import zipfile
from collections import OrderedDict
from collections.abc import Collection, Iterator
from pathlib import Path

from ...models.errors import DomainError
from ...ports.realtime import GtfsTime, StaticStopReference, StaticStopTime, StaticTrip
from .binary_transport import BinaryTransport

TfnswApiError = DomainError

_SCHEMA_VERSION = "1"
_REFRESH_SECONDS = 6 * 60 * 60
_REQUIRED_FILES = frozenset({"routes.txt", "stops.txt", "trips.txt", "stop_times.txt"})
_PLATFORM_RE = re.compile(r"\bPlatform\s+(.+)$", re.IGNORECASE)
_MAX_CACHED_TRIPS = 64
_MAX_UNCOMPRESSED_BYTES = {
    "routes.txt": 32 * 1024 * 1024,
    "stops.txt": 64 * 1024 * 1024,
    "trips.txt": 128 * 1024 * 1024,
    "stop_times.txt": 512 * 1024 * 1024,
}
_MAX_ROWS = {
    "routes.txt": 100_000,
    "stops.txt": 500_000,
    "trips.txt": 2_000_000,
    "stop_times.txt": 8_000_000,
}
_MAX_COMPRESSION_RATIO = 200
_MAX_FIELD_CHARS = 8_192
_INSERT_BATCH = 2_000


class StaticGtfsRepository:
    """Own static-feed transport and atomically index selected GTFS columns."""

    def __init__(
        self,
        transport: BinaryTransport,
        *,
        database_path: Path | None = None,
    ) -> None:
        self._transport = transport
        self._database_path = database_path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._last_modified: str | None = None
        self._checked_at: float | None = None
        self._trips: OrderedDict[str, StaticTrip | None] = OrderedDict()

    def get_trip(self, service_id: str) -> StaticTrip | None:
        with self._lock:
            self._refresh_if_needed()
            if service_id in self._trips:
                self._trips.move_to_end(service_id)
                return self._trips[service_id]
            result = self._query_trip(service_id)
            self._trips[service_id] = result
            if len(self._trips) > _MAX_CACHED_TRIPS:
                self._trips.popitem(last=False)
            return result

    def get_stop_references(
        self, stop_ids: Collection[str]
    ) -> dict[str, StaticStopReference]:
        unique = tuple(dict.fromkeys(stop_ids))[:300]
        if not unique:
            return {}
        with self._lock:
            self._refresh_if_needed()
            connection = self._require_connection()
            rows = _select_stops(connection, unique)
            parents = tuple(
                dict.fromkeys(
                    str(row["parent_station"])
                    for row in rows.values()
                    if row["parent_station"]
                )
            )
            parent_rows = _select_stops(connection, parents) if parents else {}
            return {
                stop_id: _stop_reference(stop_id, rows.get(stop_id), parent_rows)
                for stop_id in unique
            }

    def stop_reference(self, stop_id: str) -> StaticStopReference:
        return self.get_stop_references((stop_id,))[stop_id]

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _refresh_if_needed(self) -> None:
        now = time.monotonic()
        self._open_existing()
        if (
            self._connection is not None
            and self._checked_at is not None
            and now - self._checked_at < _REFRESH_SECONDS
        ):
            return
        responses = self._transport.get_all("static_schedule")
        self._checked_at = now
        if any(response.data is None for response in responses):
            raise TfnswApiError(
                "static_data_unavailable",
                "TfNSW did not return the static timetable bundle.",
                retryable=True,
            )
        last_modified = "|".join(response.last_modified or "" for response in responses)
        if self._connection is not None and last_modified == (
            self._last_modified or ""
        ):
            return
        self._replace_index(
            tuple(response.data for response in responses if response.data is not None),
            last_modified,
        )

    def _open_existing(self) -> None:
        if self._connection is not None or self._database_path is None:
            return
        if not self._database_path.is_file():
            return
        connection = _connect(self._database_path)
        try:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            if metadata.get("schema_version") != _SCHEMA_VERSION:
                connection.close()
                return
        except sqlite3.Error:
            connection.close()
            return
        self._connection = connection
        self._last_modified = metadata.get("last_modified") or None

    def _replace_index(
        self, raws: tuple[bytes, ...], last_modified: str | None
    ) -> None:
        try:
            archives = []
            for raw in raws:
                archive = zipfile.ZipFile(io.BytesIO(raw))
                _validate_archive(archive)
                archives.append(archive)
            try:
                if self._database_path is None:
                    connection = _connect(None)
                    _build_index(connection, tuple(archives), last_modified)
                    old = self._connection
                    self._connection = connection
                    if old is not None:
                        old.close()
                else:
                    self._replace_file_index(tuple(archives), last_modified)
            finally:
                for archive in archives:
                    archive.close()
        except zipfile.BadZipFile as exc:
            raise TfnswApiError(
                "static_data_invalid", "TfNSW returned an invalid static GTFS archive."
            ) from exc
        self._last_modified = last_modified
        self._trips.clear()

    def _replace_file_index(
        self, archives: tuple[zipfile.ZipFile, ...], last_modified: str | None
    ) -> None:
        if self._database_path is None:
            raise RuntimeError("database path is required")
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{self._database_path.name}.",
            suffix=".tmp",
            dir=self._database_path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        connection = _connect(temporary)
        try:
            _build_index(connection, archives, last_modified)
            connection.close()
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            os.replace(temporary, self._database_path)
            self._connection = _connect(self._database_path)
        except Exception:
            connection.close()
            temporary.unlink(missing_ok=True)
            raise

    def _query_trip(self, service_id: str) -> StaticTrip | None:
        connection = self._require_connection()
        row = connection.execute(
            """
            SELECT t.trip_id, t.service_id, t.route_id, t.trip_headsign,
                   t.direction_id, t.vehicle_category_id,
                   r.agency_id, r.route_type, r.route_short_name, r.route_long_name
              FROM trips AS t
              LEFT JOIN routes AS r ON r.route_id = t.route_id
             WHERE t.trip_id = ?
            """,
            (service_id,),
        ).fetchone()
        if row is None:
            return None
        times = tuple(
            StaticStopTime(
                stop_id=str(item["stop_id"]),
                sequence=int(item["stop_sequence"]),
                arrival=_gtfs_time(item["arrival_time"]),
                departure=_gtfs_time(item["departure_time"]),
                stop_headsign=item["stop_headsign"],
            )
            for item in connection.execute(
                """
                SELECT stop_id, stop_sequence, arrival_time, departure_time, stop_headsign
                  FROM stop_times
                 WHERE trip_id = ?
                 ORDER BY stop_sequence
                 LIMIT 300
                """,
                (service_id,),
            )
        )
        return StaticTrip(
            service_id=service_id,
            service_calendar_id=row["service_id"],
            route_id=row["route_id"],
            agency_id=row["agency_id"],
            route_type=_optional_int(row["route_type"]),
            route_short_name=row["route_short_name"],
            route_long_name=row["route_long_name"],
            headsign=row["trip_headsign"],
            direction_id=row["direction_id"],
            vehicle_category_id=row["vehicle_category_id"],
            stop_times=times,
            last_modified=self._last_modified,
        )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise TfnswApiError(
                "static_data_unavailable", "Static GTFS index is unavailable."
            )
        return self._connection


def _connect(path: Path | None) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(path) if path is not None else ":memory:", check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def _build_index(
    connection: sqlite3.Connection,
    archives: tuple[zipfile.ZipFile, ...],
    last_modified: str | None,
) -> None:
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE routes (
                route_id TEXT PRIMARY KEY, agency_id TEXT, route_type TEXT,
                route_short_name TEXT, route_long_name TEXT
            );
            CREATE TABLE stops (
                stop_id TEXT PRIMARY KEY, stop_name TEXT,
                parent_station TEXT, platform_code TEXT
            );
            CREATE TABLE trips (
                trip_id TEXT PRIMARY KEY, service_id TEXT, route_id TEXT,
                trip_headsign TEXT, direction_id TEXT, vehicle_category_id TEXT
            );
            CREATE TABLE stop_times (
                trip_id TEXT NOT NULL, stop_sequence INTEGER NOT NULL,
                arrival_time TEXT, departure_time TEXT, stop_id TEXT NOT NULL,
                stop_headsign TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", _SCHEMA_VERSION),
                ("last_modified", last_modified or ""),
            ),
        )
        for archive in archives:
            _load_routes(connection, archive)
        for archive in archives:
            _load_stops(connection, archive)
        for archive in archives:
            _load_trips(connection, archive)
            _load_stop_times(connection, archive)
        connection.execute(
            "CREATE INDEX stop_times_trip_sequence "
            "ON stop_times (trip_id, stop_sequence)"
        )
        connection.commit()
    except (KeyError, UnicodeError, csv.Error, sqlite3.Error, ValueError) as exc:
        connection.rollback()
        if isinstance(exc, TfnswApiError):
            raise
        raise TfnswApiError(
            "static_data_invalid", "TfNSW static GTFS tables could not be indexed."
        ) from exc


def _load_routes(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    _batched_insert(
        connection,
        "INSERT OR REPLACE INTO routes VALUES (?, ?, ?, ?, ?)",
        (
            (
                row.get("route_id") or "",
                row.get("agency_id") or None,
                row.get("route_type") or None,
                row.get("route_short_name") or None,
                row.get("route_long_name") or None,
            )
            for row in _rows(archive, "routes.txt")
            if row.get("route_id")
        ),
    )


def _load_stops(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    _batched_insert(
        connection,
        "INSERT OR REPLACE INTO stops VALUES (?, ?, ?, ?)",
        (
            (
                row.get("stop_id") or "",
                row.get("stop_name") or None,
                row.get("parent_station") or None,
                row.get("platform_code") or None,
            )
            for row in _rows(archive, "stops.txt")
            if row.get("stop_id")
        ),
    )


def _load_trips(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS archive_trips;
        CREATE TEMP TABLE archive_trips (
            trip_id TEXT PRIMARY KEY, service_id TEXT, route_id TEXT,
            trip_headsign TEXT, direction_id TEXT, vehicle_category_id TEXT
        );
        """
    )
    _batched_insert(
        connection,
        "INSERT OR REPLACE INTO archive_trips VALUES (?, ?, ?, ?, ?, ?)",
        (
            (
                row.get("trip_id") or "",
                row.get("service_id") or None,
                row.get("route_id") or None,
                row.get("trip_headsign") or None,
                row.get("direction_id") or None,
                row.get("vehicle_category_id") or None,
            )
            for row in _rows(archive, "trips.txt")
            if row.get("trip_id")
        ),
    )
    # Each upstream archive is a complete authority for the trips it declares.
    # Remove an earlier archive's stop timeline before the later trip metadata and
    # stop times are installed, so collision handling is truly last-wins.
    connection.execute(
        "DELETE FROM stop_times WHERE trip_id IN (SELECT trip_id FROM archive_trips)"
    )
    connection.execute("INSERT OR REPLACE INTO trips SELECT * FROM archive_trips")


def _load_stop_times(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> None:
    def values() -> Iterator[tuple[object, ...]]:
        for row in _rows(archive, "stop_times.txt"):
            trip_id = row.get("trip_id")
            stop_id = row.get("stop_id")
            sequence = _optional_int(row.get("stop_sequence"))
            if not trip_id or not stop_id or sequence is None:
                raise TfnswApiError(
                    "static_data_invalid",
                    "TfNSW static GTFS contains an invalid stop-time identity.",
                )
            _gtfs_time(row.get("arrival_time"))
            _gtfs_time(row.get("departure_time"))
            yield (
                trip_id,
                sequence,
                row.get("arrival_time") or None,
                row.get("departure_time") or None,
                stop_id,
                row.get("stop_headsign") or None,
            )

    _batched_insert(
        connection,
        "INSERT INTO stop_times VALUES (?, ?, ?, ?, ?, ?)",
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


def _select_stops(
    connection: sqlite3.Connection, stop_ids: Collection[str]
) -> dict[str, sqlite3.Row]:
    placeholders = ",".join("?" for _ in stop_ids)
    return {
        str(row["stop_id"]): row
        for row in connection.execute(
            f"SELECT stop_id, stop_name, parent_station, platform_code "
            f"FROM stops WHERE stop_id IN ({placeholders})",
            tuple(stop_ids),
        )
    }


def _stop_reference(
    stop_id: str,
    row: sqlite3.Row | None,
    parents: dict[str, sqlite3.Row],
) -> StaticStopReference:
    name = str(row["stop_name"]) if row and row["stop_name"] else None
    parent_id = str(row["parent_station"]) if row and row["parent_station"] else None
    parent = parents.get(parent_id or "")
    platform_code = (
        str(row["platform_code"]).strip() if row and row["platform_code"] else None
    )
    match = _PLATFORM_RE.search(name or "")
    return StaticStopReference(
        id=stop_id,
        name=name,
        parent_station_id=parent_id,
        parent_station_name=(
            str(parent["stop_name"]) if parent and parent["stop_name"] else None
        ),
        platform=platform_code or (match.group(1).strip() if match else None),
    )


def _gtfs_time(value: object) -> GtfsTime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise TfnswApiError(
            "static_data_invalid", "TfNSW static GTFS contains an invalid service time."
        )
    try:
        hour, minute, second = (int(part) for part in value.split(":"))
    except ValueError as exc:
        raise TfnswApiError(
            "static_data_invalid", "TfNSW static GTFS contains an invalid service time."
        ) from exc
    if hour < 0 or hour > 47 or minute not in range(60) or second not in range(60):
        raise TfnswApiError(
            "static_data_invalid", "TfNSW static GTFS contains an invalid service time."
        )
    return GtfsTime(hour * 3600 + minute * 60 + second)


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str | None]]:
    with (
        archive.open(name) as raw,
        io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text,
    ):
        for index, row in enumerate(csv.DictReader(text), start=1):
            if index > _MAX_ROWS[name]:
                raise TfnswApiError(
                    "static_data_invalid",
                    f"TfNSW static GTFS {name} exceeds its row limit.",
                )
            if any(
                value is not None and len(value) > _MAX_FIELD_CHARS
                for value in row.values()
            ):
                raise TfnswApiError(
                    "static_data_invalid",
                    f"TfNSW static GTFS {name} has an oversized field.",
                )
            yield row


def _validate_archive(archive: zipfile.ZipFile) -> None:
    by_name: dict[str, list[zipfile.ZipInfo]] = {}
    for info in archive.infolist():
        by_name.setdefault(info.filename, []).append(info)
    if not _REQUIRED_FILES.issubset(by_name):
        raise TfnswApiError(
            "static_data_invalid",
            "TfNSW static GTFS archive is missing required tables.",
        )
    for name in _REQUIRED_FILES:
        matches = by_name[name]
        if len(matches) != 1:
            raise TfnswApiError(
                "static_data_invalid", f"TfNSW static GTFS contains duplicate {name}."
            )
        info = matches[0]
        if info.file_size > _MAX_UNCOMPRESSED_BYTES[name]:
            raise TfnswApiError(
                "static_data_invalid",
                f"TfNSW static GTFS {name} exceeds expanded-size limit.",
            )
        if info.file_size / max(info.compress_size, 1) > _MAX_COMPRESSION_RATIO:
            raise TfnswApiError(
                "static_data_invalid",
                f"TfNSW static GTFS {name} has an unsafe compression ratio.",
            )


def _optional_int(value: object) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value) if isinstance(value, (str, int)) else None
    except ValueError:
        return None
