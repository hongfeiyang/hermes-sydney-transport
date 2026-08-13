"""Bounded indexed adapter for TfNSW location facilities and lift inventory."""

from __future__ import annotations

import csv
import re
import sqlite3
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from ...models.errors import DomainError
from ...ports.facilities import (
    FacilitiesPort,
    FacilityCoordinates,
    FacilityRecord,
    FacilitySnapshot,
    LiftRecord,
)
from .static_resources import StaticDownload, StaticResourceTransport

_SCHEMA_VERSION = "1"
_REFRESH_SECONDS = 24 * 60 * 60
_MAX_CSV_ROWS = 20_000
_MAX_FIELD_CHARS = 8_192
_MAX_LIFTS_PER_STOP = 100
_MAX_XLSX_FILES = 64
_MAX_XLSX_ENTRY_BYTES = 8 * 1024 * 1024
_MAX_XLSX_RATIO = 200
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_COLUMN_RE = re.compile(r"^([A-Z]+)")


class TfnswFacilitiesAdapter(FacilitiesPort):
    """Exact-ID facility lookup over two independently versioned static resources."""

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

    def get_facility(self, stop_id: str) -> FacilitySnapshot:
        with self._lock:
            self._refresh_if_needed()
            connection = self._require_connection()
            row = connection.execute(
                "SELECT * FROM facilities WHERE efa_id = ? ORDER BY id LIMIT 1",
                (stop_id,),
            ).fetchone()
            matched_by = "efa_id"
            if row is None:
                row = connection.execute(
                    "SELECT * FROM facilities WHERE tsn = ? ORDER BY id LIMIT 1",
                    (stop_id,),
                ).fetchone()
                matched_by = "tsn"
            if row is None:
                return FacilitySnapshot(
                    matched_by="none",
                    facility=None,
                    lifts=(),
                    source_updated_at=self._source_updated_at(connection),
                    cache_stale=self._cache_stale,
                )
            facility = _facility_record(row)
            lifts = tuple(
                LiftRecord(
                    functional_location_code=item["functional_location_code"],
                    description=item["description"],
                    inventory_record_updated_at=_iso_datetime(
                        item["record_updated_at"]
                    ),
                )
                for item in connection.execute(
                    """
                    SELECT functional_location_code, description, record_updated_at
                      FROM lifts WHERE tsn = ? ORDER BY id LIMIT ?
                    """,
                    (facility.tsn, _MAX_LIFTS_PER_STOP),
                )
            )
            return FacilitySnapshot(
                matched_by=matched_by,
                facility=facility,
                lifts=lifts,
                source_updated_at=self._source_updated_at(connection),
                cache_stale=self._cache_stale,
            )

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _refresh_if_needed(self) -> None:
        now = time.monotonic()
        self._open_or_create()
        if self._checked_at is not None and now - self._checked_at < _REFRESH_SECONDS:
            return
        connection = self._require_connection()
        has_cache = _table_has_rows(connection, "facilities")
        try:
            self._refresh_resources(connection)
        except DomainError:
            if not has_cache:
                raise
            self._cache_stale = True
        self._checked_at = now

    def _refresh_resources(self, connection: sqlite3.Connection) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".facilities-refresh-", dir=self._database_path.parent
        ) as directory:
            root = Path(directory)
            facility_file = root / "facilities.csv"
            lift_file = root / "lifts.xlsx"
            facility_download = self._transport.download(
                "location_facilities",
                facility_file,
                if_modified_since=_metadata_datetime(
                    connection, "location_last_modified"
                ),
            )
            lift_download = self._transport.download(
                "interchange_lifts",
                lift_file,
                if_modified_since=_metadata_datetime(connection, "lifts_last_modified"),
            )
            facility_rows = (
                tuple(_read_facilities(facility_file))
                if not facility_download.not_modified
                else None
            )
            lift_rows = (
                tuple(_read_lifts(lift_file))
                if not lift_download.not_modified
                else None
            )
            if facility_rows is None and not _table_has_rows(connection, "facilities"):
                raise DomainError(
                    "static_data_unavailable",
                    "TfNSW returned no location-facility data for an empty cache.",
                )
            if lift_rows is None and not _metadata(connection, "lifts_loaded"):
                raise DomainError(
                    "static_data_unavailable",
                    "TfNSW returned no lift inventory for an empty cache.",
                )
            _replace_resource_rows(
                connection,
                facility_rows,
                lift_rows,
                facility_download,
                lift_download,
            )
            self._cache_stale = False

    def _open_or_create(self) -> None:
        if self._connection is not None:
            return
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self._database_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            _create_schema(connection)
            version = _metadata(connection, "schema_version")
            if version not in {None, _SCHEMA_VERSION}:
                raise sqlite3.DatabaseError("unsupported facility cache schema")
            if version is None:
                _set_metadata(connection, "schema_version", _SCHEMA_VERSION)
                connection.commit()
        except sqlite3.Error:
            connection.close()
            raise DomainError(
                "static_data_invalid", "The local TfNSW facility cache is invalid."
            ) from None
        self._connection = connection

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DomainError(
                "static_data_unavailable", "TfNSW facility cache is unavailable."
            )
        return self._connection

    def _source_updated_at(self, connection: sqlite3.Connection) -> datetime | None:
        values = [
            value
            for key in ("location_last_modified", "lifts_last_modified")
            if (value := _metadata_datetime(connection, key)) is not None
        ]
        return max(values) if values else None


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS facilities (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL, efa_id TEXT NOT NULL, tsn TEXT NOT NULL,
            address TEXT, phone TEXT, latitude REAL, longitude REAL,
            transport_modes TEXT NOT NULL, accessibility_classification TEXT NOT NULL,
            accessibility_features TEXT NOT NULL, facilities TEXT NOT NULL,
            morning_staffed_hours TEXT, afternoon_staffed_hours TEXT,
            short_platform INTEGER
        );
        CREATE INDEX IF NOT EXISTS facilities_efa_id ON facilities (efa_id);
        CREATE INDEX IF NOT EXISTS facilities_tsn ON facilities (tsn);
        CREATE TABLE IF NOT EXISTS lifts (
            id INTEGER PRIMARY KEY,
            tsn TEXT NOT NULL, functional_location_code TEXT,
            description TEXT, record_updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS lifts_tsn ON lifts (tsn);
        """
    )


def _replace_resource_rows(
    connection: sqlite3.Connection,
    facilities: tuple[FacilityRecord, ...] | None,
    lifts: tuple[tuple[str, LiftRecord], ...] | None,
    facility_download: StaticDownload,
    lift_download: StaticDownload,
) -> None:
    try:
        connection.execute("BEGIN")
        if facilities is not None:
            connection.execute("DELETE FROM facilities")
            connection.executemany(
                """
                INSERT INTO facilities (
                    name, efa_id, tsn, address, phone, latitude, longitude,
                    transport_modes, accessibility_classification,
                    accessibility_features, facilities, morning_staffed_hours,
                    afternoon_staffed_hours, short_platform
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (_facility_values(item) for item in facilities),
            )
            _set_download_metadata(
                connection, "location_last_modified", facility_download
            )
        if lifts is not None:
            connection.execute("DELETE FROM lifts")
            connection.executemany(
                """
                INSERT INTO lifts (
                    tsn, functional_location_code, description, record_updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (
                        tsn,
                        item.functional_location_code,
                        item.description,
                        item.inventory_record_updated_at.isoformat()
                        if item.inventory_record_updated_at
                        else None,
                    )
                    for tsn, item in lifts
                ),
            )
            _set_metadata(connection, "lifts_loaded", "true")
            _set_download_metadata(connection, "lifts_last_modified", lift_download)
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise DomainError(
            "static_data_invalid", "TfNSW facility data could not be indexed."
        ) from exc


def _read_facilities(path: Path) -> Iterator[FacilityRecord]:
    required = {
        "LOCATION_NAME",
        "TSN",
        "EFA_ID",
        "ACCESSIBILITY",
        "FACILITIES",
        "TRANSPORT_MODE",
    }
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not required.issubset(reader.fieldnames or ()):
                raise ValueError("location facility headers are incomplete")
            for index, row in enumerate(reader, start=1):
                if index > _MAX_CSV_ROWS:
                    raise ValueError("location facility row limit exceeded")
                if any(
                    value is not None and len(value) > _MAX_FIELD_CHARS
                    for value in row.values()
                ):
                    raise ValueError("location facility field limit exceeded")
                efa_id = _required_text(row.get("EFA_ID"))
                tsn = _required_text(row.get("TSN"))
                accessibility = _pipe_values(row.get("ACCESSIBILITY"))
                yield FacilityRecord(
                    name=_required_text(row.get("LOCATION_NAME")),
                    efa_id=efa_id,
                    tsn=tsn,
                    address=_text(row.get("ADDRESS")),
                    phone=_text(row.get("PHONE")),
                    coordinates=_coordinates(row.get("LATITUDE"), row.get("LONGITUDE")),
                    transport_modes=_comma_values(row.get("TRANSPORT_MODE")),
                    accessibility_classification=_classification(accessibility),
                    accessibility_features=accessibility[1:],
                    facilities=_pipe_values(row.get("FACILITIES")),
                    morning_staffed_hours=_text(row.get("MORNING_PEAK")),
                    afternoon_staffed_hours=_text(row.get("AFTERNOON_PEAK")),
                    short_platform=_optional_bool(row.get("SHORT_PLATFORM")),
                )
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        raise DomainError(
            "static_data_invalid", "TfNSW location-facility data is invalid."
        ) from exc


def _read_lifts(path: Path) -> Iterator[tuple[str, LiftRecord]]:
    try:
        with zipfile.ZipFile(path) as archive:
            _validate_xlsx(archive)
            shared = _shared_strings(archive)
            rows = _worksheet_rows(archive, "xl/worksheets/sheet1.xml", shared)
            header = next(rows)
            required = {
                "tsn",
                "_updated_at",
                "sydney_trains__lift_functional_location_code",
            }
            if not required.issubset(header.values()):
                raise ValueError("lift inventory headers are incomplete")
            by_name = {name: column for column, name in header.items()}
            for index, row in enumerate(rows, start=1):
                if index > _MAX_CSV_ROWS:
                    raise ValueError("lift inventory row limit exceeded")
                tsn = _text(row.get(by_name["tsn"]))
                if not tsn:
                    continue
                yield (
                    tsn,
                    LiftRecord(
                        functional_location_code=_text(
                            row.get(
                                by_name["sydney_trains__lift_functional_location_code"]
                            )
                        ),
                        description=_text(
                            row.get(by_name.get("lift_location_description", ""))
                        ),
                        inventory_record_updated_at=_xlsx_datetime(
                            row.get(by_name["_updated_at"])
                        ),
                    ),
                )
    except (OSError, KeyError, StopIteration, ValueError, zipfile.BadZipFile) as exc:
        raise DomainError(
            "static_data_invalid", "TfNSW lift inventory data is invalid."
        ) from exc


def _validate_xlsx(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > _MAX_XLSX_FILES:
        raise ValueError("lift workbook contains too many files")
    names = {item.filename for item in infos}
    required = {"xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"}
    if not required.issubset(names):
        raise ValueError("lift workbook is missing required XML")
    for item in infos:
        if item.filename.startswith("/") or ".." in Path(item.filename).parts:
            raise ValueError("lift workbook contains an unsafe path")
        if item.file_size > _MAX_XLSX_ENTRY_BYTES:
            raise ValueError("lift workbook entry is oversized")
        if item.file_size / max(item.compress_size, 1) > _MAX_XLSX_RATIO:
            raise ValueError("lift workbook compression ratio is unsafe")


def _shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return tuple(
        "".join(node.text or "" for node in item.iter(f"{{{_SHEET_NS}}}t"))[
            :_MAX_FIELD_CHARS
        ]
        for item in root.findall(f"{{{_SHEET_NS}}}si")
    )


def _worksheet_rows(
    archive: zipfile.ZipFile, name: str, shared: tuple[str, ...]
) -> Iterator[dict[str, str]]:
    root = ElementTree.fromstring(archive.read(name))
    for row in root.iter(f"{{{_SHEET_NS}}}row"):
        values: dict[str, str] = {}
        for cell in row.findall(f"{{{_SHEET_NS}}}c"):
            match = _COLUMN_RE.match(cell.attrib.get("r", ""))
            value = cell.find(f"{{{_SHEET_NS}}}v")
            if match is None or value is None or value.text is None:
                continue
            text = value.text
            if cell.attrib.get("t") == "s":
                text = shared[int(text)]
            values[match.group(1)] = text[:_MAX_FIELD_CHARS]
        yield values


def _facility_values(item: FacilityRecord) -> tuple[object, ...]:
    return (
        item.name,
        item.efa_id,
        item.tsn,
        item.address,
        item.phone,
        item.coordinates.latitude if item.coordinates else None,
        item.coordinates.longitude if item.coordinates else None,
        "\x1f".join(item.transport_modes),
        item.accessibility_classification,
        "\x1f".join(item.accessibility_features),
        "\x1f".join(item.facilities),
        item.morning_staffed_hours,
        item.afternoon_staffed_hours,
        None if item.short_platform is None else int(item.short_platform),
    )


def _facility_record(row: sqlite3.Row) -> FacilityRecord:
    coordinates = (
        FacilityCoordinates(
            latitude=float(row["latitude"]), longitude=float(row["longitude"])
        )
        if row["latitude"] is not None and row["longitude"] is not None
        else None
    )
    return FacilityRecord(
        name=str(row["name"]),
        efa_id=str(row["efa_id"]),
        tsn=str(row["tsn"]),
        address=row["address"],
        phone=row["phone"],
        coordinates=coordinates,
        transport_modes=tuple(filter(None, str(row["transport_modes"]).split("\x1f"))),
        accessibility_classification=str(row["accessibility_classification"]),
        accessibility_features=tuple(
            filter(None, str(row["accessibility_features"]).split("\x1f"))
        ),
        facilities=tuple(filter(None, str(row["facilities"]).split("\x1f"))),
        morning_staffed_hours=row["morning_staffed_hours"],
        afternoon_staffed_hours=row["afternoon_staffed_hours"],
        short_platform=(
            bool(row["short_platform"]) if row["short_platform"] is not None else None
        ),
    )


def _coordinates(
    latitude: str | None, longitude: str | None
) -> FacilityCoordinates | None:
    if not latitude or not longitude:
        return None
    lat = float(latitude)
    lon = float(longitude)
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("facility coordinates are outside WGS84 bounds")
    return FacilityCoordinates(lat, lon)


def _classification(values: tuple[str, ...]) -> str:
    first = values[0].casefold() if values else ""
    if "independent access" in first:
        return "independent_access"
    if "assisted access" in first:
        return "assisted_access"
    if "not accessible" in first:
        return "not_accessible"
    return "unknown"


def _pipe_values(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split("|") if part.strip())[:50]


def _comma_values(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split(",") if part.strip())[:20]


def _optional_bool(value: str | None) -> bool | None:
    if value in {None, ""}:
        return None
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError("facility boolean is invalid")


def _xlsx_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    except ValueError:
        return None


def _required_text(value: str | None) -> str:
    text = _text(value)
    if not text:
        raise ValueError("required facility text is absent")
    return text


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    result = " ".join(value.split())
    return result[:_MAX_FIELD_CHARS] or None


def _table_has_rows(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None


def _metadata(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = ?", (key,)
    ).fetchone()
    return str(row[0]) if row is not None else None


def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", (key, value)
    )


def _metadata_datetime(connection: sqlite3.Connection, key: str) -> datetime | None:
    return _iso_datetime(_metadata(connection, key))


def _iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _set_download_metadata(
    connection: sqlite3.Connection, key: str, download: StaticDownload
) -> None:
    if download.last_modified is not None:
        _set_metadata(connection, key, download.last_modified.isoformat())
