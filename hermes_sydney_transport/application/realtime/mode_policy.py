"""Data-only capability differences for one realtime pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from ...ports.realtime import TransportMode


@dataclass(frozen=True, slots=True)
class ModePolicy:
    mode: TransportMode
    supports_trip_delay: bool
    supports_update_bundles: bool
    supports_carriage_occupancy: bool
    occupancy_note: str
    position_coverage_note: str
