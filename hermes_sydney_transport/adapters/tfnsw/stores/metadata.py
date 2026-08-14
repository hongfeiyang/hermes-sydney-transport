"""Shared SQLite metadata value encoding for persistent adapter stores."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def read_metadata(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM metadata WHERE key=?", (key,)
    ).fetchone()
    return str(row[0]) if row is not None else None


def write_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)", (key, value)
    )


def metadata_datetime(connection: sqlite3.Connection, key: str) -> datetime | None:
    return stored_datetime(read_metadata(connection, key))


def stored_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def latest_metadata_datetime(
    connection: sqlite3.Connection, keys: tuple[str, ...]
) -> datetime | None:
    values = tuple(
        value
        for key in keys
        if (value := metadata_datetime(connection, key)) is not None
    )
    return max(values) if values else None
