"""Public GTFS-Realtime codec facade used by semantic repositories."""

from __future__ import annotations

from ....ports.alerts import AlertRecord
from ....ports.realtime import TransportMode, TripUpdatesFeed, VehiclePositionsFeed
from .protobuf_alerts import decode_alerts
from .protobuf_core import protobuf_available
from .protobuf_realtime import decode_trip_updates, decode_vehicle_positions


class ProtobufRealtimeDecoder:
    def trip_updates(self, raw: bytes) -> TripUpdatesFeed:
        return decode_trip_updates(raw)

    def vehicle_positions(self, raw: bytes) -> VehiclePositionsFeed:
        return decode_vehicle_positions(raw)

    def alerts(
        self, raw: bytes, mode: TransportMode, source_feed: str | None = None
    ) -> tuple[AlertRecord, ...]:
        return decode_alerts(raw, mode, source_feed)


__all__ = [
    "ProtobufRealtimeDecoder",
    "decode_alerts",
    "decode_trip_updates",
    "decode_vehicle_positions",
    "protobuf_available",
]
