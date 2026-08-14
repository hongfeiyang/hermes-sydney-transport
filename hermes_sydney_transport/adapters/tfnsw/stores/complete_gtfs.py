"""Persistent Complete GTFS cache and bounded timetable queries."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from ....models.errors import DomainError
from ....models.static_inputs import RouteTimetableInput
from ....ports.timetable import (
    RouteTimetableSnapshot,
    TimetableRouteRecord,
    TimetableStopRecord,
    TimetableTripRecord,
)
from .complete_gtfs_index import SCHEMA_VERSION, build_complete_index
from .metadata import metadata_datetime, read_metadata, write_metadata
from .resources import StaticResourceStore

_SYDNEY = ZoneInfo("Australia/Sydney")
_MAX_STOP_TIMES_PER_TRIP = 100


class CompleteGtfsStore:
    """Own cache refresh, stale fallback, SQLite lifecycle, and queries."""

    def __init__(self, resource: StaticResourceStore, database_path: Path) -> None:
        self._resource = resource
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self.cache_stale = False

    def refresh(self, *, max_age_seconds: int = 0) -> None:
        self._open_existing()
        if self._cache_is_fresh(max_age_seconds):
            self.cache_stale = False
            return
        has_cache = self._connection is not None
        try:
            self._replace_from_remote()
        except DomainError:
            if not has_cache:
                raise
            self.cache_stale = True

    def snapshot(
        self, request: RouteTimetableInput, service_date: date
    ) -> RouteTimetableSnapshot:
        connection = self._require_connection()
        route = _select_route(connection, request.route_id)
        trips = (
            tuple(
                _trip_record(connection, row, service_date)
                for row in _select_trips(connection, request, service_date)
            )
            if route is not None
            else ()
        )
        return RouteTimetableSnapshot(
            route=route,
            service_date=service_date,
            trips=trips,
            source_updated_at=metadata_datetime(connection, "last_modified"),
            cache_stale=self.cache_stale,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _replace_from_remote(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        previous = (
            metadata_datetime(self._connection, "last_modified")
            if self._connection is not None
            else None
        )
        with tempfile.TemporaryDirectory(
            prefix=".complete-gtfs-refresh-", dir=self._database_path.parent
        ) as directory:
            checked_at = datetime.now(UTC)
            archive_path = Path(directory) / "complete-gtfs.zip"
            download = self._resource.download(
                "complete_gtfs", archive_path, if_modified_since=previous
            )
            if download.not_modified:
                if self._connection is None:
                    raise DomainError(
                        "static_data_unavailable",
                        "TfNSW returned not-modified without a Complete GTFS cache.",
                    )
                write_metadata(self._connection, "checked_at", checked_at.isoformat())
                self._connection.commit()
                self.cache_stale = False
                return
            temporary_index = Path(directory) / "complete-gtfs.sqlite3"
            build_complete_index(
                temporary_index,
                archive_path,
                download.last_modified,
                checked_at,
            )
            self.close()
            os.replace(temporary_index, self._database_path)
            self._connection = _connect(self._database_path)
            self.cache_stale = False

    def _open_existing(self) -> None:
        if self._connection is not None or not self._database_path.is_file():
            return
        connection = _connect(self._database_path)
        try:
            if read_metadata(connection, "schema_version") != SCHEMA_VERSION:
                connection.close()
                return
        except sqlite3.Error:
            connection.close()
            return
        self._connection = connection

    def _cache_is_fresh(self, max_age_seconds: int) -> bool:
        if self._connection is None or max_age_seconds <= 0:
            return False
        checked_at = metadata_datetime(self._connection, "checked_at")
        if checked_at is None:
            try:
                checked_at = datetime.fromtimestamp(
                    self._database_path.stat().st_mtime, tz=UTC
                )
            except OSError:
                return False
        age = (datetime.now(UTC) - checked_at).total_seconds()
        return 0 <= age < max_age_seconds

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DomainError(
                "static_data_unavailable", "Complete GTFS index is unavailable."
            )
        return self._connection


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def _select_route(
    connection: sqlite3.Connection, route_id: str
) -> TimetableRouteRecord | None:
    row = connection.execute(
        "SELECT * FROM routes WHERE route_id = ?", (route_id,)
    ).fetchone()
    return (
        TimetableRouteRecord(
            id=str(row["route_id"]),
            agency_id=row["agency_id"],
            short_name=row["route_short_name"],
            long_name=row["route_long_name"],
            description=row["route_desc"],
            route_type=row["route_type"],
        )
        if row is not None
        else None
    )


def _select_trips(
    connection: sqlite3.Connection, request: RouteTimetableInput, service_date: date
) -> tuple[sqlite3.Row, ...]:
    weekday = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )[service_date.weekday()]
    date_text = service_date.strftime("%Y%m%d")
    clauses = ["t.route_id = ?"]
    parameters: list[object] = [request.route_id]
    if request.direction_id is not None:
        clauses.append("t.direction_id = ?")
        parameters.append(request.direction_id)
    if request.stop_id is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM stop_times sf "
            "WHERE sf.trip_id = t.trip_id AND sf.stop_id = ?)"
        )
        parameters.append(request.stop_id)
    parameters.extend((date_text, date_text, date_text, request.limit))
    return tuple(
        connection.execute(
            f"""
            SELECT t.*,
              (SELECT COALESCE(s.departure_time, s.arrival_time) FROM stop_times s
                WHERE s.trip_id=t.trip_id ORDER BY s.stop_sequence LIMIT 1) first_departure,
              (SELECT COALESCE(s.arrival_time, s.departure_time) FROM stop_times s
                WHERE s.trip_id=t.trip_id ORDER BY s.stop_sequence DESC LIMIT 1) last_arrival
            FROM trips t LEFT JOIN calendar c ON c.service_id=t.service_id
            WHERE {" AND ".join(clauses)}
              AND COALESCE(
                (SELECT CASE cd.exception_type WHEN 1 THEN 1 WHEN 2 THEN 0 END
                 FROM calendar_dates cd WHERE cd.service_id=t.service_id
                 AND cd.service_date=? LIMIT 1),
                CASE WHEN c.start_date<=? AND c.end_date>=? THEN c.{weekday} ELSE 0 END
              )=1
            ORDER BY COALESCE(first_departure,'99:99:99'), t.trip_id LIMIT ?
            """,
            tuple(parameters),
        ).fetchall()
    )


def _trip_record(
    connection: sqlite3.Connection, row: sqlite3.Row, service_date: date
) -> TimetableTripRecord:
    stop_rows = connection.execute(
        """
        SELECT st.*, s.stop_name FROM stop_times st
        LEFT JOIN stops s ON s.stop_id=st.stop_id
        WHERE st.trip_id=? ORDER BY st.stop_sequence LIMIT ?
        """,
        (row["trip_id"], _MAX_STOP_TIMES_PER_TRIP + 1),
    ).fetchall()
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
        for item in stop_rows[:_MAX_STOP_TIMES_PER_TRIP]
    )
    return TimetableTripRecord(
        trip_id=str(row["trip_id"]),
        headsign=row["trip_headsign"],
        direction_id=row["direction_id"],
        wheelchair_accessibility=_wheelchair(row["wheelchair_accessible"]),
        first_departure=_service_datetime(service_date, row["first_departure"]),
        last_arrival=_service_datetime(service_date, row["last_arrival"]),
        stop_times=stops,
        stop_times_truncated=len(stop_rows) > _MAX_STOP_TIMES_PER_TRIP,
    )


def _wheelchair(value: object) -> Literal["accessible", "not_accessible", "unknown"]:
    return "accessible" if value == 1 else "not_accessible" if value == 2 else "unknown"


def _service_datetime(service_date: date, value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    hour, minute, second = map(int, value.split(":"))
    return datetime.combine(service_date, datetime_time(), tzinfo=_SYDNEY) + timedelta(
        hours=hour, minutes=minute, seconds=second
    )
