from __future__ import annotations

import unittest
from dataclasses import fields

from hermes_sydney_transport.bootstrap.modes import MODE_SPECS
from hermes_sydney_transport.ports.realtime import TransportMode


class FeedCatalogTests(unittest.TestCase):
    def test_every_mode_has_the_complete_feed_vocabulary(self) -> None:
        expected = {
            "alerts",
            "trip_updates",
            "vehicle_positions",
            "static_schedule",
        }

        for mode in TransportMode:
            with self.subTest(mode=mode):
                spec = next(item for item in MODE_SPECS if item.mode is mode)
                self.assertEqual({item.name for item in fields(spec.feeds)}, expected)
                self.assertTrue(all(spec.feeds.groups()))

    def test_feed_endpoints_are_unique_validated_and_bounded(self) -> None:
        endpoints = [
            endpoint
            for spec in MODE_SPECS
            for group in spec.feeds.groups()
            for endpoint in group
        ]

        self.assertEqual(len({endpoint.id for endpoint in endpoints}), len(endpoints))
        self.assertTrue(
            all(
                endpoint.url.startswith("https://api.transport.nsw.gov.au/")
                for endpoint in endpoints
            )
        )
        self.assertTrue(
            all(endpoint.max_bytes <= 128 * 1_024 * 1_024 for endpoint in endpoints)
        )

    def test_light_rail_and_ferry_multi_feed_coverage_is_explicit(self) -> None:
        self.assertEqual(
            len(
                next(
                    item for item in MODE_SPECS if item.mode is TransportMode.LIGHT_RAIL
                ).feeds.trip_updates
            ),
            4,
        )
        self.assertEqual(
            next(item for item in MODE_SPECS if item.mode is TransportMode.LIGHT_RAIL)
            .feeds.trip_updates[0]
            .url,
            "https://api.transport.nsw.gov.au/v2/gtfs/realtime/lightrail/innerwest",
        )
        self.assertEqual(
            len(
                next(
                    item for item in MODE_SPECS if item.mode is TransportMode.FERRY
                ).feeds.vehicle_positions
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
