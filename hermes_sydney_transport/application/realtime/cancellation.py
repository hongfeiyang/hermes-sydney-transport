"""Explicit precedence rules for TfNSW cancellation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...models.errors import DomainError
from ...ports.realtime import TripRelationship, TripUpdateRecord, UpdateBundle
from .mode_policy import ModePolicy

CancellationSource = Literal["none", "trip_update", "trip_update_and_bundle"]


@dataclass(frozen=True, slots=True)
class CancellationDecision:
    cancelled: bool
    source: CancellationSource
    warnings: tuple[str, ...]


def require_update(
    update: TripUpdateRecord | None,
    bundles: tuple[UpdateBundle, ...],
    policy: ModePolicy,
) -> TripUpdateRecord:
    relevant = bundles if policy.supports_update_bundles else ()
    if update is not None:
        return update
    if relevant:
        bundle = relevant[-1]
        raise DomainError(
            "unverified_cancellation",
            "TfNSW listed this service only in UpdateBundle "
            f"{bundle.bundle_id!r} sequence {bundle.update_sequence}, but the public "
            "static schedule does not expose a bundle identity that can bind that "
            "evidence safely. No cancellation was inferred.",
            retryable=True,
        )
    raise DomainError(
        "service_not_found",
        f"That service is not present in the current TfNSW {policy.mode.value} Trip "
        "Updates feed. It may be outside the realtime window or completed.",
    )


def decide_cancellation(
    update: TripUpdateRecord,
    bundles: tuple[UpdateBundle, ...],
    policy: ModePolicy,
) -> CancellationDecision:
    relevant = bundles if policy.supports_update_bundles else ()
    cancelled = update.relationship is TripRelationship.CANCELLED
    warnings: tuple[str, ...] = ()
    if relevant and not cancelled:
        bundle = relevant[-1]
        warnings = (
            (
                "TfNSW UpdateBundle "
                f"{bundle.bundle_id!r} sequence {bundle.update_sequence} listed the "
                "service as cancelled, but its TripUpdate is active; the service-specific "
                "TripUpdate was preferred."
            ),
        )
    source: CancellationSource = (
        "trip_update_and_bundle"
        if cancelled and relevant
        else "trip_update"
        if cancelled
        else "none"
    )
    return CancellationDecision(cancelled=cancelled, source=source, warnings=warnings)
