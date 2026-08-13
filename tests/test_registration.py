from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_sydney_transport import register
from hermes_sydney_transport.bootstrap import registration
from hermes_sydney_transport.bootstrap.settings import Settings


class FakeContext:
    def __init__(self):
        self.registrations = []

    def register_tool(self, **kwargs):
        self.registrations.append(kwargs)


class RegistrationTests(unittest.TestCase):
    def test_registers_twenty_two_namespaced_tools_in_two_toolsets(self):
        context = FakeContext()

        register(context)

        self.assertEqual(len(context.registrations), 22)
        names = {item["name"] for item in context.registrations}
        self.assertEqual(
            names,
            {
                "sydney_transport_search_stops",
                "sydney_transport_nearby_stops",
                "sydney_transport_departures",
                "sydney_transport_plan_trip",
                "sydney_transport_alerts",
                "sydney_transport_route_disruptions",
                "sydney_transport_stop_accessibility",
                "sydney_transport_route_timetable",
                "sydney_transport_train_service_status",
                "sydney_transport_train_vehicle_position",
                "sydney_transport_bus_service_status",
                "sydney_transport_bus_vehicle_position",
                "sydney_transport_metro_service_status",
                "sydney_transport_metro_vehicle_position",
                "sydney_transport_light_rail_service_status",
                "sydney_transport_light_rail_vehicle_position",
                "sydney_transport_ferry_service_status",
                "sydney_transport_ferry_vehicle_position",
                "nsw_live_traffic_hazards",
                "nsw_traffic_count_stations",
                "nsw_traffic_volume_summary",
                "nsw_traffic_volume_hourly",
            },
        )
        for item in context.registrations:
            self.assertIn(item["toolset"], {"sydney_transport", "nsw_traffic"})
            self.assertEqual(item["requires_env"], ["TFNSW_API_KEY"])
            self.assertEqual(item["schema"]["name"], item["name"])
            self.assertTrue(callable(item["handler"]))
            self.assertTrue(callable(item["check_fn"]))

    def test_check_function_tracks_real_environment(self):
        context = FakeContext()
        register(context)
        check_fn = context.registrations[0]["check_fn"]

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(check_fn())
        with patch.dict(os.environ, {"TFNSW_API_KEY": "configured"}, clear=True):
            self.assertTrue(check_fn())
            self.assertTrue(context.registrations[-1]["check_fn"]())

    def test_missing_protobuf_hides_only_realtime_tools(self):
        context = FakeContext()
        with (
            patch.dict(os.environ, {"TFNSW_API_KEY": "configured"}, clear=True),
            patch.object(registration, "protobuf_available", return_value=False),
        ):
            register(context)
            availability = {
                item["name"]: item["check_fn"]() for item in context.registrations
            }

        realtime = {
            "sydney_transport_route_disruptions",
            "sydney_transport_train_service_status",
            "sydney_transport_train_vehicle_position",
            "sydney_transport_bus_service_status",
            "sydney_transport_bus_vehicle_position",
            "sydney_transport_metro_service_status",
            "sydney_transport_metro_vehicle_position",
            "sydney_transport_light_rail_service_status",
            "sydney_transport_light_rail_vehicle_position",
            "sydney_transport_ferry_service_status",
            "sydney_transport_ferry_vehicle_position",
        }
        for name, available in availability.items():
            self.assertEqual(available, name not in realtime)

    def test_container_is_reused_for_identical_validated_settings(self):
        provider = registration._ContainerProvider()
        settings = Settings("secret", Path("/tmp/test-sydney-transport-cache"))
        replacement = Settings("rotated", settings.cache_directory)
        first_container = SimpleNamespace(close=lambda: None)
        second_container = SimpleNamespace(close=lambda: None)
        with patch.object(
            registration,
            "Container",
            side_effect=[first_container, second_container],
        ) as factory:
            first = provider.get(settings)
            repeated = provider.get(settings)
            replaced = provider.get(replacement)

        self.assertIs(first, first_container)
        self.assertIs(repeated, first_container)
        self.assertIs(replaced, second_container)
        self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
