"""Persistent static-GTFS store with atomic index replacement."""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from collections.abc import Collection
from pathlib import Path

from ....models.errors import DomainError
from ....ports.realtime import (
    GtfsTime,
    StaticStopReference,
    StaticStopTime,
    StaticTrip,
)
from ..codecs.gtfs import gtfs_time_seconds
from .static_gtfs_index import build_static_index

_SCHEMA_VERSION = "1"
_PLATFORM_RE = re.compile(r"\bPlatform\s+(.+)$", re.IGNORECASE)


class StaticGtfsStore:
    """Own SQLite lifecycle, queries, and atomic replacement only."""

    def __init__(self, database_path: Path | None) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self.last_modified: str | None = None

    @property
    def available(self) -> bool:
        return self._connection is not None

    def open_existing(self) -> None:
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
        self.last_modified = metadata.get("last_modified") or None

    def replace(self, archives: tuple[bytes, ...], last_modified: str | None) -> None:
        if self._database_path is None:
            connection = _connect(None)
            build_static_index(connection, archives, last_modified)
            self._swap_connection(connection)
        else:
            self._replace_file(archives, last_modified)
        self.last_modified = last_modified

    def trip(self, service_id: str) -> StaticTrip | None:
        connection = self._require_connection()
        row = connection.execute(
            """
            SELECT t.trip_id, t.service_id, t.route_id, t.trip_headsign,
                   t.direction_id, t.vehicle_category_id,
                   r.agency_id, r.route_type, r.route_short_name, r.route_long_name
              FROM trips AS t LEFT JOIN routes AS r ON r.route_id = t.route_id
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
                arrival=_stored_time(item["arrival_time"]),
                departure=_stored_time(item["departure_time"]),
                stop_headsign=item["stop_headsign"],
            )
            for item in connection.execute(
                """
                SELECT stop_id, stop_sequence, arrival_time, departure_time, stop_headsign
                  FROM stop_times WHERE trip_id = ? ORDER BY stop_sequence LIMIT 300
                """,
                (service_id,),
            )
        )
        return StaticTrip(
            service_id=service_id,
            service_calendar_id=row["service_id"],
            route_id=row["route_id"],
            agency_id=row["agency_id"],
            route_type=row["route_type"],
            route_short_name=row["route_short_name"],
            route_long_name=row["route_long_name"],
            headsign=row["trip_headsign"],
            direction_id=(
                str(row["direction_id"]) if row["direction_id"] is not None else None
            ),
            vehicle_category_id=row["vehicle_category_id"],
            stop_times=times,
            last_modified=self.last_modified,
        )

    def stops(self, stop_ids: Collection[str]) -> dict[str, StaticStopReference]:
        connection = self._require_connection()
        rows = _select_stops(connection, stop_ids)
        parent_ids = tuple(
            dict.fromkeys(
                str(row["parent_station"])
                for row in rows.values()
                if row["parent_station"]
            )
        )
        parents = _select_stops(connection, parent_ids) if parent_ids else {}
        return {
            stop_id: _stop_reference(stop_id, rows.get(stop_id), parents)
            for stop_id in stop_ids
        }

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _replace_file(
        self, archives: tuple[bytes, ...], last_modified: str | None
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
            build_static_index(connection, archives, last_modified)
            connection.close()
            self.close()
            os.replace(temporary, self._database_path)
            self._connection = _connect(self._database_path)
        except Exception:
            connection.close()
            temporary.unlink(missing_ok=True)
            raise

    def _swap_connection(self, connection: sqlite3.Connection) -> None:
        old = self._connection
        self._connection = connection
        if old is not None:
            old.close()

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DomainError("static_data_unavailable", "Static GTFS is unavailable.")
        return self._connection


def _connect(path: Path | None) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(path) if path is not None else ":memory:", check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


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
    stop_id: str, row: sqlite3.Row | None, parents: dict[str, sqlite3.Row]
) -> StaticStopReference:
    name = _row_text(row, "stop_name")
    parent_id = _row_text(row, "parent_station")
    parent = parents.get(parent_id or "")
    return StaticStopReference(
        id=stop_id,
        name=name,
        parent_station_id=parent_id,
        parent_station_name=_row_text(parent, "stop_name"),
        platform=_platform(row, name),
    )


def _stored_time(value: object) -> GtfsTime | None:
    return GtfsTime(gtfs_time_seconds(value)) if isinstance(value, str) else None


def _row_text(row: sqlite3.Row | None, key: str) -> str | None:
    return str(row[key]) if row is not None and row[key] else None


def _platform(row: sqlite3.Row | None, name: str | None) -> str | None:
    code = _row_text(row, "platform_code")
    match = _PLATFORM_RE.search(name or "")
    return code.strip() if code else (match.group(1).strip() if match else None)
