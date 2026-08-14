"""Facility repository orchestration."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ....ports.facilities import FacilitiesPort, FacilitySnapshot
from ..mappers.facilities import map_facility_snapshot
from ..stores.facilities import FacilitiesStore
from ..stores.resources import StaticResourceStore

_REFRESH_SECONDS = 24 * 60 * 60


class TfnswFacilitiesAdapter(FacilitiesPort):
    """Refresh and query exact EFA/TSN facility identifiers."""

    def __init__(self, transport: StaticResourceStore, *, database_path: Path) -> None:
        self._store = FacilitiesStore(transport, database_path)
        self._lock = threading.RLock()
        self._checked_at: float | None = None

    def get_facility(self, stop_id: str) -> FacilitySnapshot:
        with self._lock:
            now = time.monotonic()
            if self._checked_at is None or now - self._checked_at >= _REFRESH_SECONDS:
                self._store.refresh()
                self._checked_at = now
            return map_facility_snapshot(self._store.get(stop_id))

    def close(self) -> None:
        with self._lock:
            self._store.close()
