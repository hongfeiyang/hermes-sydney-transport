from __future__ import annotations

import unittest
from datetime import UTC, datetime

from hermes_sydney_transport.adapters.tfnsw.alerts import TfnswAlertsAdapter
from hermes_sydney_transport.adapters.tfnsw.binary_transport import BinaryResponse
from hermes_sydney_transport.adapters.tfnsw.live_traffic import TfnswLiveTrafficAdapter
from hermes_sydney_transport.adapters.tfnsw.live_traffic_wire import (
    FeatureCollectionWire,
)
from hermes_sydney_transport.application.alerts import GetRouteDisruptions
from hermes_sydney_transport.application.live_traffic import GetLiveTrafficHazards
from hermes_sydney_transport.models.disruption_inputs import RouteDisruptionsInput
from hermes_sydney_transport.models.errors import DomainError
from hermes_sydney_transport.models.live_traffic_inputs import LiveTrafficHazardsInput
from hermes_sydney_transport.ports.alerts import (
    AlertQuery,
    AlertRecord,
    AlertSelector,
    AlertTimeRange,
)
from hermes_sydney_transport.ports.live_traffic import HazardQuery
from hermes_sydney_transport.ports.realtime import TransportMode


class FakeAlertsTransport:
    def __init__(self, responses):
        self.responses = responses

    def get_all(self, endpoint, *, if_modified_since=None):
        self.endpoint = endpoint
        return self.responses


class FakeAlertsDecoder:
    def alerts(self, raw, mode, source_feed=None):
        if source_feed == "sydneytrains":
            return (
                _alert("dup", mode, source_feed, route_id="T1"),
                _alert("dup", mode, source_feed, route_id="T1"),
            )
        return (_alert("regional", mode, source_feed, route_id="T1"),)


class FakeLiveTrafficTransport:
    def __init__(self, collection):
        self.collection = collection
        self.calls = 0

    def get_collection(self, path):
        self.calls += 1
        self.path = path
        return self.collection


class FixedClock:
    def now(self):
        return datetime(2026, 8, 13, 2, 0, tzinfo=UTC)


class RouteDisruptionTests(unittest.TestCase):
    def test_input_supports_all_public_modes(self):
        request = RouteDisruptionsInput.model_validate(
            {"modes": ["train", "bus", "metro", "light_rail", "ferry"]}
        )
        self.assertEqual(len(request.modes), 5)

    def test_alert_adapter_dedupes_and_keeps_source_feed_provenance(self):
        adapter = TfnswAlertsAdapter(
            {
                TransportMode.TRAIN: FakeAlertsTransport(
                    [BinaryResponse(b"1", None, None), BinaryResponse(b"2", None, None)]
                )
            },
            FakeAlertsDecoder(),
        )

        result = adapter.find_alerts(
            AlertQuery(
                modes=(TransportMode.TRAIN,),
                stop_id=None,
                route_id="T1",
                trip_id=None,
                causes=(),
                effects=(),
                active_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
            )
        )

        self.assertEqual([item.id for item in result], ["regional", "dup"])
        self.assertEqual(
            [item.source_feed for item in result], ["nswtrains", "sydneytrains"]
        )

    def test_alert_adapter_fails_closed_on_missing_feed(self):
        adapter = TfnswAlertsAdapter(
            {
                TransportMode.TRAIN: FakeAlertsTransport(
                    [BinaryResponse(b"1", None, None)]
                )
            },
            FakeAlertsDecoder(),
        )

        with self.assertRaises(DomainError):
            adapter.find_alerts(
                AlertQuery(
                    modes=(TransportMode.TRAIN,),
                    stop_id=None,
                    route_id=None,
                    trip_id=None,
                    causes=(),
                    effects=(),
                    active_at=None,
                )
            )

    def test_route_disruptions_use_case_sorts_by_severity_then_time(self):
        class FakeAlertsPort:
            def find_alerts(self, query):
                return (
                    _alert("later", TransportMode.TRAIN, "sydneytrains", "T1"),
                    _alert(
                        "severe",
                        TransportMode.TRAIN,
                        "sydneytrains",
                        "T1",
                        severity="severe",
                    ),
                )

        result = GetRouteDisruptions(FakeAlertsPort(), FixedClock()).execute(
            RouteDisruptionsInput.model_validate(
                {"modes": ["train"], "route_id": "T1", "limit": 1}
            )
        )

        self.assertEqual(
            [item["id"] for item in result.model_dump(mode="json")["disruptions"]],
            ["severe"],
        )


class LiveTrafficTests(unittest.TestCase):
    def test_suburb_query_clears_radius(self):
        request = LiveTrafficHazardsInput.model_validate({"suburb": "Parramatta"})
        self.assertIsNone(request.radius_metres)

    def test_live_traffic_adapter_filters_by_radius_and_preserves_coordinates(self):
        collection = FeatureCollectionWire.model_validate(
            {
                "type": "FeatureCollection",
                "layerName": "Incident",
                "lastPublished": 1755043200000,
                "features": [
                    {
                        "type": "Feature",
                        "id": 10,
                        "geometry": {
                            "type": "Point",
                            "coordinates": [151.0, -33.8],
                        },
                        "properties": {
                            "impactingNetwork": True,
                            "ended": False,
                            "isMajor": True,
                            "displayName": "CRASH 2 cars",
                            "headline": "",
                            "mainCategory": "CRASH",
                            "incidentKind": "Unplanned",
                            "adviceA": "Exercise caution",
                            "roads": [
                                {"mainStreet": "Parramatta Road", "suburb": "Granville"}
                            ],
                            "webLinks": [],
                        },
                    }
                ],
            }
        )
        transport = FakeLiveTrafficTransport(collection)
        adapter = TfnswLiveTrafficAdapter(transport)

        result = adapter.find_hazards(
            HazardQuery(
                latitude=-33.8,
                longitude=151.0,
                radius_metres=200,
                suburb=None,
                hazard_types=("incident",),
                limit=5,
            )
        )
        adapter.find_hazards(
            HazardQuery(
                latitude=-33.8,
                longitude=151.0,
                radius_metres=200,
                suburb=None,
                hazard_types=("incident",),
                limit=5,
            )
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].latitude, -33.8)
        self.assertEqual(result[0].longitude, 151.0)
        self.assertEqual(result[0].distance_metres, 0)
        self.assertEqual(transport.calls, 1)

    def test_live_traffic_adapter_matches_suburb_before_bounded_projection(self):
        collection = FeatureCollectionWire.model_validate(
            {
                "type": "FeatureCollection",
                "layerName": "Incident",
                "lastPublished": 1755043200000,
                "features": [
                    {
                        "type": "Feature",
                        "id": 12.5,
                        "geometry": {
                            "type": "Point",
                            "coordinates": [151.0, -33.8],
                        },
                        "properties": {
                            "impactingNetwork": True,
                            "ended": False,
                            "isMajor": False,
                            "displayName": "MULTI-ROAD INCIDENT",
                            "headline": "",
                            "mainCategory": "INCIDENT",
                            "incidentKind": "Unplanned",
                            "roads": [
                                {"mainStreet": "First Road", "suburb": "One"},
                                {"mainStreet": "Second Road", "suburb": "Two"},
                                {"mainStreet": "Third Road", "suburb": "Three"},
                                {"mainStreet": "Fourth Road", "suburb": "Parramatta"},
                            ],
                            "webLinks": [],
                        },
                    }
                ],
            }
        )
        adapter = TfnswLiveTrafficAdapter(FakeLiveTrafficTransport(collection))

        result = adapter.find_hazards(
            HazardQuery(
                latitude=None,
                longitude=None,
                radius_metres=None,
                suburb="Parramatta",
                hazard_types=("incident",),
                limit=5,
            )
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "12.5")
        self.assertEqual(len(result[0].roads), 3)

    def test_live_traffic_use_case_returns_quality_note_and_count(self):
        collection = FeatureCollectionWire.model_validate(
            {
                "type": "FeatureCollection",
                "layerName": "Incident",
                "lastPublished": 1755043200000,
                "features": [
                    {
                        "type": "Feature",
                        "id": 11,
                        "geometry": {
                            "type": "Point",
                            "coordinates": [151.0, -33.8],
                        },
                        "properties": {
                            "impactingNetwork": True,
                            "ended": False,
                            "isMajor": False,
                            "displayName": "BREAKDOWN Car",
                            "headline": "",
                            "mainCategory": "BREAKDOWN",
                            "incidentKind": "Unplanned",
                            "adviceA": "Exercise caution",
                            "roads": [
                                {"mainStreet": "Parramatta Road", "suburb": "Granville"}
                            ],
                            "webLinks": [],
                        },
                    }
                ],
            }
        )
        adapter = TfnswLiveTrafficAdapter(FakeLiveTrafficTransport(collection))

        result = GetLiveTrafficHazards(adapter, FixedClock()).execute(
            LiveTrafficHazardsInput.model_validate(
                {"latitude": -33.8, "longitude": 151.0, "hazard_types": ["incident"]}
            )
        )

        dumped = result.model_dump(mode="json")
        self.assertEqual(dumped["count"], 1)
        self.assertIn("live operational data", dumped["quality_note"])


def _alert(alert_id, mode, source_feed, route_id, severity="warning"):
    return AlertRecord(
        id=alert_id,
        mode=mode,
        source_feed=source_feed or mode.value,
        title="Trackwork",
        description="<p>Use an alternative service</p>",
        cause="construction",
        effect="modified_service",
        severity=severity,
        url="https://transportnsw.info/alerts",
        active_periods=(AlertTimeRange(start=None, end=None),),
        selectors=(
            AlertSelector(
                agency_id=None,
                route_id=route_id,
                route_type=None,
                stop_id=None,
                trip_id=None,
                direction_id=None,
            ),
        ),
        route_ids=(route_id,),
        stop_ids=(),
        trip_ids=(),
    )


if __name__ == "__main__":
    unittest.main()
