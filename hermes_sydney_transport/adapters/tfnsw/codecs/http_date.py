"""HTTP date metadata codec."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime


class HttpDateCodec:
    def encode(self, value: datetime | None) -> str | None:
        return (
            format_datetime(value.astimezone(UTC), usegmt=True)
            if value is not None
            else None
        )

    def decode(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return aware.astimezone(UTC)

    def __call__(self, value: str | None) -> datetime | None:
        return self.decode(value)
