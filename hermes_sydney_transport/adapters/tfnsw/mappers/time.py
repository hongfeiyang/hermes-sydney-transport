"""Pure canonical timezone normalization."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def sydney_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=SYDNEY_TZ)
    return aware.astimezone(SYDNEY_TZ)


def sydney_time_required(value: datetime) -> datetime:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=SYDNEY_TZ)
    return aware.astimezone(SYDNEY_TZ)
