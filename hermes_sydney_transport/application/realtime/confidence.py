"""Pure evidence and freshness scoring."""

from __future__ import annotations

from typing import Literal

from ...models.outputs import Confidence
from .common import STALE_AFTER_SECONDS, VERY_STALE_AFTER_SECONDS


def confidence(
    *,
    entity_present: bool,
    static_join: bool,
    feed_age: int,
    realtime_detail_present: bool,
) -> Confidence:
    if not entity_present:
        return Confidence(
            level="none",
            reasons=["No matching realtime entity is currently published."],
        )
    reasons = ["The exact GTFS-Realtime service ID matched."]
    reasons.append(
        "The realtime service joined to the current static GTFS trip."
        if static_join
        else "Static GTFS enrichment was unavailable."
    )
    if feed_age > VERY_STALE_AFTER_SECONDS:
        reasons.append("The realtime feed is more than five minutes old.")
        return Confidence(level="low", reasons=reasons)
    reasons.append(
        "Fresh realtime detail is present for the requested result."
        if realtime_detail_present
        else "No realtime timing or change evidence was published; schedule data was used."
    )
    level: Literal["high", "medium"] = (
        "high"
        if static_join and realtime_detail_present and feed_age <= STALE_AFTER_SECONDS
        else "medium"
    )
    return Confidence(level=level, reasons=reasons)
