"""Complete GTFS timetable repository orchestration."""

from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path

from ....models.static_inputs import RouteTimetableInput
from ....ports.timetable import RouteTimetablePort, RouteTimetableSnapshot
from ..stores.complete_gtfs import CompleteGtfsStore
from ..stores.resources import StaticResourceStore

_REFRESH_SECONDS = 6 * 60 * 60


class CompleteGtfsTimetableAdapter(RouteTimetablePort):
    """Refresh and query the indexed Complete GTFS dataset."""

    def __init__(self, transport: StaticResourceStore, *, database_path: Path) -> None:
        self._store = CompleteGtfsStore(transport, database_path)
        self._lock = threading.RLock()
        self._checked_at: float | None = None

    def get_route_timetable(
        self, request: RouteTimetableInput, service_date: date
    ) -> RouteTimetableSnapshot:
        with self._lock:
            now = time.monotonic()
            if self._checked_at is None or now - self._checked_at >= _REFRESH_SECONDS:
                self._store.refresh()
                self._checked_at = now
            return self._store.snapshot(request, service_date)

    def close(self) -> None:
        with self._lock:
            self._store.close()
