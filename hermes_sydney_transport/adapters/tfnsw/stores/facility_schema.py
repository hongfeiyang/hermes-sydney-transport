"""SQLite schema lifecycle for the reproducible facilities cache."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = "2"


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS facilities (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, efa_id TEXT NOT NULL,
            tsn TEXT NOT NULL, address TEXT, phone TEXT, latitude REAL, longitude REAL,
            transport_modes TEXT, accessibility TEXT, facilities TEXT,
            morning_staffed_hours TEXT, afternoon_staffed_hours TEXT,
            short_platform INTEGER
        );
        CREATE INDEX IF NOT EXISTS facilities_efa_id ON facilities (efa_id);
        CREATE INDEX IF NOT EXISTS facilities_tsn ON facilities (tsn);
        CREATE TABLE IF NOT EXISTS lifts (
            id INTEGER PRIMARY KEY, tsn TEXT NOT NULL,
            functional_location_code TEXT, description TEXT, record_updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS lifts_tsn ON lifts (tsn);
        """
    )


def recreate_schema(connection: sqlite3.Connection) -> None:
    """Discard an obsolete, fully reproducible cache before the next refresh."""

    connection.executescript(
        """
        DROP TABLE IF EXISTS lifts;
        DROP TABLE IF EXISTS facilities;
        DROP TABLE IF EXISTS metadata;
        """
    )
    create_schema(connection)
