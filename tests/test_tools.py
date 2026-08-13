from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from hermes_sydney_transport import register
from hermes_sydney_transport.application.capabilities import Capability
from hermes_sydney_transport.models.errors import DomainError
from hermes_sydney_transport.presentation import envelopes
from hermes_sydney_transport.presentation.catalog import TOOL_SPECS
from hermes_sydney_transport.presentation.handlers import handler_for

SPECS = {spec.capability: spec for spec in TOOL_SPECS}
METADATA = {
    "fetched_at": "2026-08-12T12:00:00+10:00",
    "source": "TfNSW test source",
    "attribution": "Transport for NSW Open Data",
}


def dispatch(capability, request):
    if capability == Capability.DEPARTURES:
        return {
            **METADATA,
            "stop_id": request.stop_id,
            "requested_modes": request.modes,
            "station": None,
            "requested_at": "2026-08-12T12:00:00+10:00",
            "departures": [],
            "count": 0,
            "realtime_note": "No estimate does not mean on time.",
        }
    if capability == Capability.NEARBY_STOPS:
        return {
            **METADATA,
            "query": {
                "latitude": request.latitude,
                "longitude": request.longitude,
                "radius_metres": request.radius_metres,
            },
            "stops": [],
            "count": 0,
            "mode_note": "Public-transport stops; mode is not guaranteed.",
        }
    if capability == Capability.PLAN_TRIP:
        return {
            **METADATA,
            "origin_stop_id": request.origin_stop_id,
            "destination_stop_id": request.destination_stop_id,
            "requested_at": "2026-08-12T12:00:00+10:00",
            "time_mode": request.time_mode,
            "wheelchair_requested": request.wheelchair,
            "requested_modes": request.modes,
            "journeys": [],
            "count": 0,
            "system_messages": [],
            "mode_note": "Requested modes only.",
        }
    if capability in {
        Capability.TRAIN_SERVICE_STATUS,
        Capability.BUS_SERVICE_STATUS,
    }:
        mode = "bus" if capability == Capability.BUS_SERVICE_STATUS else "train"
        return {
            **METADATA,
            "query": _query(request, mode),
            "feed_timestamp": "2026-08-12T02:00:00+00:00",
            "observation_timestamp": "2026-08-12T02:00:00+00:00",
            "service": _service(request, mode),
            "state": "unknown",
            "is_cancelled": False,
            "cancellation_source": "none",
            "next_stop": None,
            "last_passed_stop": None,
            "stop_updates": [],
            "stop_count": 0,
            "skipped_stops": [],
            "stop_changes": [],
            "confidence": {"level": "medium", "reasons": ["Exact ID matched."]},
            "data_quality": _quality(),
            "coverage_note": "Realtime state may be incomplete.",
        }
    if capability in {
        Capability.TRAIN_VEHICLE_POSITION,
        Capability.BUS_VEHICLE_POSITION,
    }:
        mode = "bus" if capability == Capability.BUS_VEHICLE_POSITION else "train"
        return {
            **METADATA,
            "query": _query(request, mode),
            "feed_timestamp": "2026-08-12T02:00:00+00:00",
            "service": _service(request, mode),
            "available": False,
            "vehicle": None,
            "position": None,
            "current_status": "unknown",
            "stop_context": {
                "at_stop": None,
                "last_passed_stop": None,
                "target_stop": None,
                "inferred": False,
            },
            "occupancy": {
                "reported": False,
                "level": None,
                "source": "none",
                "carriages": [],
                "coverage_note": "Missing does not mean empty.",
            },
            "confidence": {"level": "none", "reasons": ["No vehicle entity."]},
            "data_quality": _quality(entity=False),
            "coverage_note": "Vehicle coverage is incomplete.",
        }
    raise AssertionError(f"unexpected test capability: {capability}")


def _query(request, mode):
    return {
        "mode": mode,
        "requested_service_id": request.service_id,
        "trip_code": request.trip_code,
        "stop_id": request.stop_id,
        "requested_at": None,
        "resolved_service_id": request.service_id or "resolved-service",
        "resolution": "service_id" if request.service_id else "trip_code",
    }


def _service(request, mode):
    return {
        "mode": mode,
        "service_id": request.service_id or "resolved-service",
        "route_id": None,
        "agency_id": None,
        "route_type": None,
        "route_short_name": None,
        "route_long_name": None,
        "headsign": None,
        "start_date": "2026-08-12",
        "start_time": None,
        "schedule_relationship": "scheduled",
    }


def _quality(*, entity=True):
    return {
        "feed_age_seconds": 0,
        "observation_age_seconds": None,
        "feed_is_stale": False,
        "realtime_entity_present": entity,
        "static_join_successful": False,
        "used_prediction": False,
        "used_inference": False,
        "warnings": [],
    }


def tool_handler(capability, custom_dispatch=dispatch):
    return handler_for(SPECS[capability], custom_dispatch)


class FakeContext:
    def __init__(self):
        self.registrations = []

    def register_tool(self, **kwargs):
        self.registrations.append(kwargs)


class HandlerTests(unittest.TestCase):
    def test_success_is_a_json_string(self):
        result = json.loads(
            tool_handler(Capability.DEPARTURES)({"stop_id": "200060", "limit": 3})
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["stop_id"], "200060")

    def test_new_handlers_return_json_strings(self):
        nearby = json.loads(
            tool_handler(Capability.NEARBY_STOPS)(
                {"latitude": -33.88, "longitude": 151.2}
            )
        )
        trip = json.loads(
            tool_handler(Capability.PLAN_TRIP)(
                {"origin_stop_id": "200060", "destination_stop_id": "215020"}
            )
        )
        self.assertEqual(nearby["data"]["query"]["radius_metres"], 1000)
        self.assertEqual(trip["data"]["time_mode"], "depart")

    def test_realtime_handlers_return_validated_json_strings(self):
        status = json.loads(
            tool_handler(Capability.TRAIN_SERVICE_STATUS)({"service_id": "service-1"})
        )
        position = json.loads(
            tool_handler(Capability.TRAIN_VEHICLE_POSITION)({"service_id": "service-1"})
        )
        self.assertEqual(status["data"]["state"], "unknown")
        self.assertFalse(position["data"]["available"])

    def test_handler_rejects_invalid_client_output(self):
        with self.assertLogs(envelopes.logger, level="ERROR"):
            raw = tool_handler(
                Capability.DEPARTURES,
                lambda capability, request: {"stop_id": request.stop_id},
            )({"stop_id": "200060"})
        self.assertEqual(json.loads(raw)["error"]["code"], "invalid_upstream_response")

    def test_handler_maps_invalid_output_timestamp_to_contract_error(self):
        def invalid_timestamp(capability, request):
            result = dispatch(capability, request)
            result["fetched_at"] = "1786500000"
            return result

        with self.assertLogs(envelopes.logger, level="ERROR"):
            raw = tool_handler(Capability.DEPARTURES, invalid_timestamp)(
                {"stop_id": "200060"}
            )
        self.assertEqual(json.loads(raw)["error"]["code"], "invalid_upstream_response")

    def test_api_error_is_structured_json(self):
        def fail(capability, request):
            raise DomainError("upstream_http_error", "TfNSW is unavailable.", True, 503)

        result = json.loads(tool_handler(Capability.ALERTS, fail)({}))
        self.assertEqual(result["error"]["http_status"], 503)
        self.assertTrue(result["error"]["retryable"])

    def test_missing_key_fails_closed_even_if_handler_is_called_directly(self):
        context = FakeContext()
        register(context)
        with patch.dict(os.environ, {}, clear=True):
            result = json.loads(
                context.registrations[0]["handler"]({"query": "Central"})
            )
        self.assertEqual(result["error"]["code"], "missing_configuration")


if __name__ == "__main__":
    unittest.main()
