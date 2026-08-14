"""Bounded scalar decoders shared by structured provider codecs and stores."""

from __future__ import annotations


def delimited_text(value: str | None, *, separator: str, limit: int) -> tuple[str, ...]:
    """Decode one legacy delimited database field into a bounded typed tuple."""

    if value is None:
        return ()
    return tuple(part for raw in value.split(separator) if (part := raw.strip()))[
        :limit
    ]
