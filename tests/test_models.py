from __future__ import annotations

import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from hermes_sydney_transport.application.capabilities import Capability
from hermes_sydney_transport.models.inputs import (
    AlertsInput,
    BusServiceStatusInput,
    BusVehiclePositionInput,
    DeparturesInput,
    NearbyStopsInput,
    ServiceStatusInput,
    StationSearchInput,
    TripPlanInput,
    VehiclePositionInput,
)
from hermes_sydney_transport.models.outputs import (
    AlertsResult,
    NearbyStopsResult,
    StationSearchResult,
)
from hermes_sydney_transport.models.traffic_inputs import (
    TrafficStationSearchInput,
    TrafficVolumeHourlyInput,
    TrafficVolumeSummaryInput,
)
from hermes_sydney_transport.presentation.catalog import TOOL_SPECS
from hermes_sydney_transport.presentation.handlers import handler_for

SYDNEY = ZoneInfo("Australia/Sydney")
SPECS = {spec.capability: spec for spec in TOOL_SPECS}


class InputModelTests(unittest.TestCase):
    def test_hermes_parameters_are_generated_from_pydantic_models(self):
        expected_models = {
            StationSearchInput,
            NearbyStopsInput,
            DeparturesInput,
            TripPlanInput,
            AlertsInput,
            ServiceStatusInput,
            VehiclePositionInput,
            BusServiceStatusInput,
            BusVehiclePositionInput,
            TrafficStationSearchInput,
            TrafficVolumeSummaryInput,
            TrafficVolumeHourlyInput,
        }
        self.assertEqual({spec.input_model for spec in TOOL_SPECS}, expected_models)
        for spec in TOOL_SPECS:
            schema = spec.schema()
            model = spec.input_model
            expected = model.model_json_schema(mode="validation")
            expected.pop("title", None)
            self.assertEqual(schema["parameters"], expected)
            self.assertFalse(schema["parameters"]["additionalProperties"])

    def test_pydantic_rejects_extra_handler_arguments(self):
        handler = handler_for(
            SPECS[Capability.SEARCH_STOPS],
            lambda capability, request: self.fail("invalid input reached dispatch"),
        )
        result = json.loads(handler({"query": "Central", "unexpected": "value"}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_argument")
        self.assertEqual(result["error"]["details"][0]["field"], "unexpected")

    def test_generated_schema_and_runtime_share_strict_stop_id_contract(self):
        stop_schema = SPECS[Capability.DEPARTURES].schema()["parameters"]["properties"][
            "stop_id"
        ]
        self.assertEqual(stop_schema["pattern"], r"^[A-Za-z0-9:_-]+$")
        with self.assertRaises(ValidationError):
            DeparturesInput.model_validate({"stop_id": "Central station"})
        with self.assertRaises(ValidationError):
            NearbyStopsInput.model_validate(
                {"latitude": "-33.88408", "longitude": 151.20629}
            )

    def test_time_model_normalises_sydney_timezone_with_context(self):
        request = DeparturesInput.model_validate(
            {"stop_id": "200060", "at": "2026-10-04T03:15:00"},
            context={
                "now": datetime(2026, 10, 4, 1, 30, tzinfo=SYDNEY),
            },
        )
        self.assertEqual(request.at.isoformat(), "2026-10-04T03:15:00+11:00")

    def test_time_contract_rejects_non_datetime_and_dst_edge_cases(self):
        at_schema = SPECS[Capability.DEPARTURES].schema()["parameters"]["properties"][
            "at"
        ]
        self.assertEqual(at_schema["anyOf"][0]["format"], "date-time")

        for invalid in (1786500000, "1786500000", "2026-08-12"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                DeparturesInput.model_validate(
                    {"stop_id": "200060", "at": invalid},
                    context={
                        "now": datetime(2026, 8, 12, 9, 30, tzinfo=SYDNEY),
                    },
                )

        with self.assertRaises(ValidationError):
            DeparturesInput.model_validate(
                {"stop_id": "200060", "at": "2026-10-04T02:30:00"},
                context={"now": datetime(2026, 10, 4, 1, 30, tzinfo=SYDNEY)},
            )
        with self.assertRaises(ValidationError):
            DeparturesInput.model_validate(
                {"stop_id": "200060", "at": "2026-04-05T02:30:00"},
                context={"now": datetime(2026, 4, 5, 1, 30, tzinfo=SYDNEY)},
            )

        explicit = DeparturesInput.model_validate(
            {"stop_id": "200060", "at": "2026-04-05T02:30:00+10:00"},
            context={"now": datetime(2026, 4, 5, 1, 30, tzinfo=SYDNEY)},
        )
        self.assertEqual(explicit.at.isoformat(), "2026-04-05T02:30:00+10:00")

    def test_realtime_service_reference_is_unambiguous(self):
        direct = ServiceStatusInput.model_validate({"service_id": "203M.2012.101"})
        self.assertEqual(direct.service_id, "203M.2012.101")

        fallback = VehiclePositionInput.model_validate(
            {"trip_code": "639", "stop_id": "200060"}
        )
        self.assertEqual(fallback.trip_code, "639")

        for invalid in (
            {},
            {"trip_code": "639"},
            {"service_id": "service", "trip_code": "639"},
            {"service_id": "service", "stop_id": "200060"},
            {"service_id": 639},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                ServiceStatusInput.model_validate(invalid)


class OutputModelTests(unittest.TestCase):
    def test_output_contract_rejects_unknown_fields_and_invalid_counts(self):
        valid = {
            "query": "Central",
            "requested_modes": ["train", "bus"],
            "stations": [],
            "count": 0,
            "fetched_at": "2026-08-12T12:00:00+10:00",
            "source": "TfNSW Trip Planner API",
            "attribution": "Transport for NSW Open Data",
        }
        with self.assertRaises(ValidationError):
            StationSearchResult.model_validate({**valid, "unknown": True})
        with self.assertRaises(ValidationError):
            StationSearchResult.model_validate({**valid, "count": -1})
        with self.assertRaises(ValidationError):
            StationSearchResult.model_validate({**valid, "count": "0"})
        with self.assertRaises(ValidationError):
            StationSearchResult.model_validate({**valid, "count": 1})
        with self.assertRaises(ValidationError):
            StationSearchResult.model_validate({**valid, "fetched_at": "not-a-time"})
        with self.assertRaises(ValidationError):
            StationSearchResult.model_validate({**valid, "fetched_at": "1786500000"})
        with self.assertRaises(ValidationError):
            StationSearchResult.model_validate(
                {**valid, "fetched_at": "2026-08-12T12:00:00"}
            )

        nearby = {
            "query": {"latitude": -33.88, "longitude": 151.2, "radius_metres": 500},
            "stops": [],
            "count": 0,
            "mode_note": "Mode is not guaranteed.",
            "fetched_at": "2026-08-12T12:00:00+10:00",
            "source": "TfNSW Trip Planner API",
            "attribution": "Transport for NSW Open Data",
        }
        with self.assertRaises(ValidationError):
            NearbyStopsResult.model_validate(
                {**nearby, "query": {**nearby["query"], "latitude": 91}}
            )

    def test_alert_time_ranges_preserve_external_aliases(self):
        result = AlertsResult.model_validate(
            {
                "scope": {"network": "tfnsw_train_mode"},
                "requested_modes": ["train"],
                "alerts": [
                    {
                        "id": "alert-1",
                        "version": 1,
                        "priority": "normal",
                        "type": "lineInfo",
                        "title": "Trackwork",
                        "content": "Buses replace trains.",
                        "sms_summary": "",
                        "affected_lines": [],
                        "affected_stops": [],
                        "created_at": None,
                        "last_modified": None,
                        "validity": [
                            {
                                "from": "2026-08-12T09:00:00+10:00",
                                "to": "2026-08-12T12:00:00+10:00",
                            }
                        ],
                        "availability": [],
                        "provider": None,
                        "source_name": None,
                        "url": None,
                        "url_text": "",
                    }
                ],
                "count": 1,
                "remote_content_is_untrusted": True,
                "fetched_at": "2026-08-12T12:00:00+10:00",
                "source": "TfNSW Trip Planner API",
                "attribution": "Transport for NSW Open Data",
            }
        )
        dumped = result.model_dump(mode="json", by_alias=True)
        self.assertEqual(
            dumped["alerts"][0]["validity"][0]["from"],
            "2026-08-12T09:00:00+10:00",
        )


if __name__ == "__main__":
    unittest.main()
