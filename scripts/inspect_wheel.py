#!/usr/bin/env python3
"""Verify that a built wheel contains the reusable Hermes plugin contract."""

from __future__ import annotations

import sys
import zipfile
from email.parser import Parser
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect_wheel.py PATH_TO_WHEEL")
    wheel = Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        entry_points = archive.read(entry_points_name).decode("utf-8")
        metadata = archive.read(metadata_name).decode("utf-8")

    required = {
        "hermes_sydney_transport/__init__.py",
        "hermes_sydney_transport/py.typed",
        "hermes_sydney_transport/bootstrap/registration.py",
        "hermes_sydney_transport/presentation/catalog.py",
        "hermes_sydney_transport/proto/tfnsw_gtfs_realtime.proto",
        "hermes_sydney_transport/proto/tfnsw_gtfs_realtime_pb2.py",
    }
    missing = required - names
    if missing:
        raise SystemExit(f"wheel is missing required files: {sorted(missing)}")
    if "[hermes_agent.plugins]" not in entry_points or (
        "sydney-transport = hermes_sydney_transport" not in entry_points
    ):
        raise SystemExit("wheel is missing the Hermes plugin entry point")
    requires_python = Parser().parsestr(metadata).get("Requires-Python", "")
    if {part.strip() for part in requires_python.split(",")} != {
        ">=3.12",
        "<3.14",
    }:
        raise SystemExit("wheel has unexpected Python compatibility metadata")
    print(f"Wheel contract: OK ({wheel.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
