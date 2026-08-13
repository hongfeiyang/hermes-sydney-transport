"""Production implementation of the Clock port."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SYDNEY_TZ = ZoneInfo("Australia/Sydney")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(SYDNEY_TZ)
