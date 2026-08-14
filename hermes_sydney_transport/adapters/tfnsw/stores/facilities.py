"""Persistent facilities cache with independent resource refresh metadata."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Literal

from ....models.errors import DomainError
from ..codecs.facilities import (
    FacilityCsvRow,
    LiftSheetRow,
    StoredFacility,
    StoredFacilitySnapshot,
    StoredLift,
    facility_rows,
    lift_rows,
)
from ..codecs.text_fields import delimited_text
from .facility_schema import SCHEMA_VERSION, create_schema, recreate_schema
from .metadata import (
    latest_metadata_datetime,
    metadata_datetime,
    read_metadata,
    stored_datetime,
    write_metadata,
)
from .resources import StaticDownload, StaticResourceStore

_MAX_LIFTS_PER_STOP = 100


class FacilitiesStore:
    """Own refresh fallback, schema lifecycle, persistence, and exact-ID lookup."""

    def __init__(self, resource: StaticResourceStore, database_path: Path) -> None:
        self._resource = resource
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self.cache_stale = False

    def refresh(self) -> None:
        self._open_or_create()
        connection = self._require_connection()
        has_cache = _table_has_rows(connection, "facilities")
        try:
            self._refresh_resources(connection)
        except DomainError:
            if not has_cache:
                raise
            self.cache_stale = True

    def get(self, stop_id: str) -> StoredFacilitySnapshot:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT * FROM facilities WHERE efa_id=? ORDER BY id LIMIT 1",
            (stop_id,),
        ).fetchone()
        matched_by: Literal["efa_id", "tsn"] = "efa_id"
        if row is None:
            row = connection.execute(
                "SELECT * FROM facilities WHERE tsn=? ORDER BY id LIMIT 1",
                (stop_id,),
            ).fetchone()
            matched_by = "tsn"
        facility = _stored_facility(row) if row is not None else None
        lifts = _stored_lifts(connection, facility.tsn) if facility is not None else ()
        return StoredFacilitySnapshot(
            matched_by=matched_by if facility is not None else "none",
            facility=facility,
            lifts=lifts,
            source_updated_at=latest_metadata_datetime(
                connection, ("location_last_modified", "lifts_last_modified")
            ),
            cache_stale=self.cache_stale,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _refresh_resources(self, connection: sqlite3.Connection) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".facilities-refresh-", dir=self._database_path.parent
        ) as directory:
            root = Path(directory)
            facility_path = root / "facilities.csv"
            lift_path = root / "lifts.xlsx"
            facility_download = self._resource.download(
                "location_facilities",
                facility_path,
                if_modified_since=metadata_datetime(
                    connection, "location_last_modified"
                ),
            )
            lift_download = self._resource.download(
                "interchange_lifts",
                lift_path,
                if_modified_since=metadata_datetime(connection, "lifts_last_modified"),
            )
            facilities = (
                tuple(facility_rows(facility_path))
                if not facility_download.not_modified
                else None
            )
            lifts = (
                tuple(lift_rows(lift_path)) if not lift_download.not_modified else None
            )
            _require_initial_payloads(connection, facilities, lifts)
            _replace_rows(
                connection, facilities, lifts, facility_download, lift_download
            )
            self.cache_stale = False

    def _open_or_create(self) -> None:
        if self._connection is not None:
            return
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        database_existed = self._database_path.exists()
        connection = sqlite3.connect(str(self._database_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            create_schema(connection)
            version = read_metadata(connection, "schema_version")
            if database_existed and version != SCHEMA_VERSION:
                recreate_schema(connection)
            if version != SCHEMA_VERSION:
                write_metadata(connection, "schema_version", SCHEMA_VERSION)
                connection.commit()
        except sqlite3.Error as exc:
            connection.close()
            raise DomainError(
                "static_data_invalid", "The local TfNSW facility cache is invalid."
            ) from exc
        self._connection = connection

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DomainError(
                "static_data_unavailable", "TfNSW facility cache is unavailable."
            )
        return self._connection


def _replace_rows(
    connection: sqlite3.Connection,
    facilities: tuple[FacilityCsvRow, ...] | None,
    lifts: tuple[LiftSheetRow, ...] | None,
    facility_download: StaticDownload,
    lift_download: StaticDownload,
) -> None:
    try:
        connection.execute("BEGIN")
        if facilities is not None:
            connection.execute("DELETE FROM facilities")
            connection.executemany(
                """INSERT INTO facilities (
                    name,efa_id,tsn,address,phone,latitude,longitude,transport_modes,
                    accessibility,facilities,morning_staffed_hours,
                    afternoon_staffed_hours,short_platform
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_facility_values(item) for item in facilities),
            )
            _set_download_metadata(
                connection, "location_last_modified", facility_download
            )
        if lifts is not None:
            connection.execute("DELETE FROM lifts")
            connection.executemany(
                """INSERT INTO lifts (
                    tsn,functional_location_code,description,record_updated_at
                ) VALUES (?,?,?,?)""",
                (_lift_values(item) for item in lifts if item.tsn is not None),
            )
            write_metadata(connection, "lifts_loaded", "true")
            _set_download_metadata(connection, "lifts_last_modified", lift_download)
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise DomainError(
            "static_data_invalid", "TfNSW facility data could not be indexed."
        ) from exc


def _facility_values(item: FacilityCsvRow) -> tuple[object, ...]:
    return (
        item.name,
        item.efa_id,
        item.tsn,
        item.address,
        item.phone,
        item.latitude,
        item.longitude,
        item.transport_modes,
        item.accessibility,
        item.facilities,
        item.morning_staffed_hours,
        item.afternoon_staffed_hours,
        None if item.short_platform is None else int(item.short_platform),
    )


def _lift_values(item: LiftSheetRow) -> tuple[object, ...]:
    return (
        item.tsn,
        item.functional_location_code,
        item.description,
        item.record_updated_at.isoformat() if item.record_updated_at else None,
    )


def _stored_facility(row: sqlite3.Row) -> StoredFacility:
    return StoredFacility(
        name=str(row["name"]),
        efa_id=str(row["efa_id"]),
        tsn=str(row["tsn"]),
        address=row["address"],
        phone=row["phone"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        transport_modes=delimited_text(row["transport_modes"], separator=",", limit=20),
        accessibility=delimited_text(row["accessibility"], separator="|", limit=50),
        facilities=delimited_text(row["facilities"], separator="|", limit=50),
        morning_staffed_hours=row["morning_staffed_hours"],
        afternoon_staffed_hours=row["afternoon_staffed_hours"],
        short_platform=(
            bool(row["short_platform"]) if row["short_platform"] is not None else None
        ),
    )


def _stored_lifts(connection: sqlite3.Connection, tsn: str) -> tuple[StoredLift, ...]:
    return tuple(
        StoredLift(
            functional_location_code=row["functional_location_code"],
            description=row["description"],
            record_updated_at=stored_datetime(row["record_updated_at"]),
        )
        for row in connection.execute(
            """SELECT functional_location_code,description,record_updated_at
               FROM lifts WHERE tsn=? ORDER BY id LIMIT ?""",
            (tsn, _MAX_LIFTS_PER_STOP),
        )
    )


def _require_initial_payloads(
    connection: sqlite3.Connection,
    facilities: tuple[FacilityCsvRow, ...] | None,
    lifts: tuple[LiftSheetRow, ...] | None,
) -> None:
    if facilities is None and not _table_has_rows(connection, "facilities"):
        raise DomainError(
            "static_data_unavailable",
            "TfNSW returned no facilities for an empty cache.",
        )
    if lifts is None and not read_metadata(connection, "lifts_loaded"):
        raise DomainError(
            "static_data_unavailable", "TfNSW returned no lifts for an empty cache."
        )


def _table_has_rows(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None


def _set_download_metadata(
    connection: sqlite3.Connection, key: str, download: StaticDownload
) -> None:
    if download.last_modified is not None:
        write_metadata(connection, key, download.last_modified.isoformat())
