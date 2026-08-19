from __future__ import annotations

import unittest

from pydantic import TypeAdapter

from hermes_sydney_transport.adapters.tfnsw.wire.trip_planner import (
    JourneyPayloadWire,
)


class TripPlannerWireContractTests(unittest.TestCase):
    def test_journey_leg_declares_array_shaped_realtime_status(self):
        payload = b'{"journeys":[{"legs":[{"realtimeStatus":["MONITORED"]}]}]}'

        decoded = TypeAdapter(JourneyPayloadWire).validate_json(payload)

        self.assertEqual(
            decoded.journeys[0].legs[0].realtime_status,
            ("MONITORED",),
        )


if __name__ == "__main__":
    unittest.main()
