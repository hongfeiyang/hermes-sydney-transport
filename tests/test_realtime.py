from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from hermes_sydney_transport.adapters.tfnsw.codecs.protobuf import (
    ProtobufRealtimeDecoder,
    decode_alerts,
    decode_trip_updates,
    decode_vehicle_positions,
)
from hermes_sydney_transport.adapters.tfnsw.platform import HttpPayload
from hermes_sydney_transport.adapters.tfnsw.repositories.realtime import (
    TfnswRealtimeRepository,
)
from hermes_sydney_transport.application.realtime import (
    GetServiceStatus,
    GetVehiclePosition,
)
from hermes_sydney_transport.bootstrap.modes import MODE_SPECS
from hermes_sydney_transport.models.availability import Availability, Unavailable
from hermes_sydney_transport.models.errors import DomainError as TfnswApiError
from hermes_sydney_transport.models.inputs import (
    BusServiceStatusInput,
    BusVehiclePositionInput,
    FerryServiceStatusInput,
    LightRailVehiclePositionInput,
    MetroServiceStatusInput,
    ServiceStatusInput,
    VehiclePositionInput,
)
from hermes_sydney_transport.models.outputs import (
    ServiceStatusResult,
    VehiclePositionResult,
)
from hermes_sydney_transport.ports.realtime import (
    GtfsTime,
    StaticStopReference,
    StaticStopTime,
    StaticTrip,
    TransportMode,
)
from hermes_sydney_transport.ports.trip_planner import ServiceResolution
from hermes_sydney_transport.proto import tfnsw_gtfs_realtime_pb2 as pb

SYDNEY = ZoneInfo("Australia/Sydney")
SERVICE_ID = "203M.2012.101.16.H.8.91818386"


def _mode_spec(mode: str = "train"):
    selected = TransportMode(mode)
    return next(item for item in MODE_SPECS if item.mode is selected)


class FixedClock:
    def __init__(self, now):
        self._now = now

    def now(self):
        return self._now()


class RealtimeClient:
    """Test composition that preserves the former dict-returning convenience API."""

    def __init__(
        self,
        api_key,
        *,
        transport,
        trip_planner,
        static_gtfs,
        now,
        mode="train",
    ):
        spec = _mode_spec(mode)
        repository = TfnswRealtimeRepository(
            transport,
            ProtobufRealtimeDecoder(),
            feeds=spec.feeds,
            cache_seconds=0,
        )
        clock = FixedClock(now)
        self._status = GetServiceStatus(
            repository, trip_planner, static_gtfs, clock, spec.policy
        )
        self._position = GetVehiclePosition(
            repository, trip_planner, static_gtfs, clock, spec.policy
        )

    def service_status_request(self, request):
        return self._status.execute(request).model_dump(mode="json")

    def vehicle_position_request(self, request):
        return self._position.execute(request).model_dump(mode="json")


class FakeBinaryTransport:
    def __init__(self, **feeds):
        self.feeds = feeds
        self.calls = []

    def fetch(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        kind = "trip_updates" if "updates" in endpoint.id else "vehicle_positions"
        payload = self.feeds[kind]
        items = payload if isinstance(payload, tuple) else (payload,)
        marker = "updates" if kind == "trip_updates" else "vehicles"
        index = sum(1 for previous, _ in self.calls if marker in previous.id) - 1
        return HttpPayload(items[min(index, len(items) - 1)], endpoint.accept, None)


class FakeTripPlanner:
    def __init__(self):
        self.calls = []

    def resolve_service_id(self, trip_code, stop_id, at, mode="train"):
        self.calls.append((trip_code, stop_id, at))
        return ServiceResolution(service_id=SERVICE_ID, planned_time=None)


class FakeStaticGtfs:
    def __init__(self):
        self.refs = {
            "central-p1": self._ref(
                "central-p1",
                "Central Station Platform 1",
                "central",
                "Central Station",
                "1",
            ),
            "strath-p2": self._ref(
                "strath-p2",
                "Strathfield Station Platform 2",
                "strath",
                "Strathfield Station",
                "2",
            ),
            "strath-p3": self._ref(
                "strath-p3",
                "Strathfield Station Platform 3",
                "strath",
                "Strathfield Station",
                "3",
            ),
            "burwood-p4": self._ref(
                "burwood-p4",
                "Burwood Station Platform 4",
                "burwood",
                "Burwood Station",
                "4",
            ),
            "parra-p2": self._ref(
                "parra-p2",
                "Parramatta Station Platform 2",
                "parra",
                "Parramatta Station",
                "2",
            ),
        }
        self.trip = StaticTrip(
            service_id=SERVICE_ID,
            service_calendar_id="weekday",
            route_id="NTH_2a",
            agency_id=None,
            route_type=2,
            route_short_name="T1",
            route_long_name="North Shore & Western Line",
            headsign="Parramatta",
            direction_id="0",
            vehicle_category_id="B8",
            stop_times=(
                self._stop("central-p1", 1, "18:00:00"),
                self._stop("strath-p2", 2, "18:10:00"),
                self._stop("burwood-p4", 3, "18:15:00"),
                self._stop("parra-p2", 4, "18:25:00"),
            ),
            last_modified=None,
        )

    def get_trip(self, service_id):
        return self.trip if service_id == SERVICE_ID else None

    def get_stop_references(self, stop_ids):
        return {
            stop_id: self.refs.get(
                stop_id, StaticStopReference(stop_id, None, None, None, None)
            )
            for stop_id in stop_ids
        }

    def lookup_trip(self, service_id):
        return Availability(value=self.get_trip(service_id))

    def lookup_stop_references(self, stop_ids):
        return Availability(value=self.get_stop_references(stop_ids))

    @staticmethod
    def _ref(stop_id, name, parent_id, parent_name, platform):
        return StaticStopReference(stop_id, name, parent_id, parent_name, platform)

    @staticmethod
    def _stop(stop_id, sequence, scheduled):
        hour, minute, second = (int(part) for part in scheduled.split(":"))
        value = GtfsTime(hour * 3600 + minute * 60 + second)
        return StaticStopTime(stop_id, sequence, value, value, None)


class UnavailableStaticGtfs:
    def get_trip(self, service_id):
        raise TfnswApiError(
            "static_data_unavailable", "Static timetable is unavailable.", True
        )

    def get_stop_references(self, stop_ids):
        raise TfnswApiError(
            "static_data_unavailable", "Static timetable is unavailable.", True
        )

    def lookup_trip(self, service_id):
        return Availability(
            value=None,
            unavailable=Unavailable(
                "static_data_unavailable", "Static timetable is unavailable.", True
            ),
        )

    def lookup_stop_references(self, stop_ids):
        return Availability(
            value=None,
            unavailable=Unavailable(
                "static_data_unavailable", "Static timetable is unavailable.", True
            ),
        )


class RealtimeClientTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 12, 18, 5, tzinfo=SYDNEY)
        self.static = FakeStaticGtfs()
        self.planner = FakeTripPlanner()

    def test_service_status_reports_next_stop_skip_cancel_and_platform_change(self):
        transport = FakeBinaryTransport(trip_updates=_trip_update_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        request = ServiceStatusInput.model_validate({"service_id": SERVICE_ID})

        raw = client.service_status_request(request)
        result = ServiceStatusResult.model_validate(raw)

        self.assertEqual(result.state, "in_progress")
        self.assertEqual(result.next_stop.current_stop.id, "strath-p3")
        self.assertEqual(result.next_stop.arrival_predicted.minute, 12)
        self.assertEqual(result.service.schedule_relationship, "replacement")
        self.assertEqual([stop.id for stop in result.skipped_stops], ["burwood-p4"])
        self.assertEqual(len(result.stop_changes), 1)
        self.assertEqual(result.stop_changes[0].change_type, "platform")
        self.assertEqual(result.stop_changes[0].planned_stop.platform, "2")
        self.assertEqual(result.stop_changes[0].current_stop.platform, "3")
        self.assertEqual(result.confidence.level, "high")
        self.assertTrue(result.data_quality.static_join_successful)
        self.assertTrue(result.data_quality.used_prediction)

    def test_trip_code_fallback_is_resolved_before_feed_lookup(self):
        transport = FakeBinaryTransport(trip_updates=_trip_update_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        request = ServiceStatusInput.model_validate(
            {"trip_code": "639", "stop_id": "200060"}
        )

        result = ServiceStatusResult.model_validate(
            client.service_status_request(request)
        )

        self.assertEqual(result.query.resolution, "trip_code")
        self.assertEqual(result.query.resolved_service_id, SERVICE_ID)
        self.assertEqual(self.planner.calls[0][:2], ("639", "200060"))

    def test_vehicle_position_reports_coordinates_and_carriage_occupancy(self):
        transport = FakeBinaryTransport(vehicle_positions=_vehicle_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        request = VehiclePositionInput.model_validate({"service_id": SERVICE_ID})

        result = VehiclePositionResult.model_validate(
            client.vehicle_position_request(request)
        )

        self.assertTrue(result.available)
        self.assertAlmostEqual(result.position.coordinates.latitude, -33.8837, places=3)
        self.assertEqual(result.current_status, "in_transit_to")
        self.assertIsNone(result.stop_context.at_stop)
        self.assertEqual(result.stop_context.last_passed_stop.id, "central-p1")
        self.assertEqual(result.stop_context.target_stop.id, "strath-p2")
        self.assertTrue(result.stop_context.inferred)
        self.assertTrue(result.vehicle.wheelchair_accessible)
        self.assertEqual(result.occupancy.source, "vehicle_and_carriage")
        self.assertEqual(result.occupancy.level, "many_seats_available")
        self.assertEqual(len(result.occupancy.carriages), 2)

    def test_missing_vehicle_is_successful_unavailable_not_empty(self):
        transport = FakeBinaryTransport(vehicle_positions=_empty_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        request = VehiclePositionInput.model_validate({"service_id": SERVICE_ID})

        result = VehiclePositionResult.model_validate(
            client.vehicle_position_request(request)
        )

        self.assertFalse(result.available)
        self.assertFalse(result.occupancy.reported)
        self.assertIsNone(result.occupancy.level)
        self.assertEqual(result.confidence.level, "none")
        self.assertIn("incomplete", result.coverage_note.lower())

    def test_invalid_protobuf_is_a_structured_feed_error(self):
        with self.assertRaises(TfnswApiError) as raised:
            decode_trip_updates(b"not-a-protobuf")
        self.assertEqual(raised.exception.code, "invalid_realtime_feed")

    def test_alert_decoder_preserves_v2_selectors_period_and_severity(self):
        records = decode_alerts(_alert_feed(), TransportMode.TRAIN, "sydneytrains")

        self.assertEqual(len(records), 1)
        alert = records[0]
        self.assertEqual(alert.id, "trackwork-1")
        self.assertEqual(alert.source_feed, "sydneytrains")
        self.assertEqual(alert.cause, "maintenance")
        self.assertEqual(alert.effect, "modified_service")
        self.assertEqual(alert.severity, "warning")
        self.assertEqual(alert.route_ids, ("T1",))
        self.assertEqual(alert.stop_ids, ("G204313",))
        self.assertEqual(alert.trip_ids, (SERVICE_ID,))
        self.assertEqual(
            alert.active_periods[0].start,
            datetime(2026, 8, 12, 7, 0, tzinfo=UTC),
        )

    def test_realtime_gateway_fetches_and_decodes_once_per_cache_window(self):
        transport = FakeBinaryTransport(trip_updates=_trip_update_feed())
        repository = TfnswRealtimeRepository(
            transport,
            ProtobufRealtimeDecoder(),
            feeds=_mode_spec().feeds,
            cache_seconds=15,
        )

        first = repository.service_snapshot(SERVICE_ID)
        second = repository.service_snapshot(SERVICE_ID)

        self.assertIs(first.update, second.update)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(repository.stats().trip_fetches, 1)
        self.assertEqual(repository.stats().trip_cache_hits, 1)

    def test_realtime_gateway_single_flights_concurrent_readers(self):
        transport = FakeBinaryTransport(trip_updates=_trip_update_feed())
        repository = TfnswRealtimeRepository(
            transport,
            ProtobufRealtimeDecoder(),
            feeds=_mode_spec().feeds,
            cache_seconds=15,
        )

        with ThreadPoolExecutor(max_workers=8) as executor:
            snapshots = list(
                executor.map(
                    lambda unused: repository.service_snapshot(SERVICE_ID), range(16)
                )
            )

        self.assertTrue(all(item.update is snapshots[0].update for item in snapshots))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(repository.stats().trip_cache_hits, 15)

    def test_realtime_gateway_keeps_first_feed_when_service_id_repeats(self):
        transport = FakeBinaryTransport(
            trip_updates=(
                _trip_update_feed(route_id="route-first"),
                _trip_update_feed(route_id="route-second"),
            )
        )
        repository = TfnswRealtimeRepository(
            transport,
            ProtobufRealtimeDecoder(),
            feeds=_mode_spec().feeds,
            cache_seconds=0,
        )

        snapshot = repository.service_snapshot(SERVICE_ID)

        self.assertIsNotNone(snapshot.update)
        self.assertEqual(snapshot.update.route_id, "route-first")

    def test_realtime_gateway_keeps_first_vehicle_when_service_id_repeats(self):
        transport = FakeBinaryTransport(
            vehicle_positions=(
                _vehicle_feed(route_id="route-first", label="first"),
                _vehicle_feed(route_id="route-second", label="second"),
            )
        )
        repository = TfnswRealtimeRepository(
            transport,
            ProtobufRealtimeDecoder(),
            feeds=_mode_spec().feeds,
            cache_seconds=0,
        )

        snapshot = repository.vehicle_snapshot(SERVICE_ID)

        self.assertIsNotNone(snapshot.vehicle)
        self.assertEqual(snapshot.vehicle.route_id, "route-first")
        self.assertEqual(snapshot.vehicle.label, "first")

    def test_cancelled_trip_and_static_failure_degrade_without_guessing(self):
        transport = FakeBinaryTransport(trip_updates=_cancelled_trip_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=UnavailableStaticGtfs(),
            now=lambda: self.now,
        )
        request = ServiceStatusInput.model_validate({"service_id": SERVICE_ID})

        result = ServiceStatusResult.model_validate(
            client.service_status_request(request)
        )

        self.assertTrue(result.is_cancelled)
        self.assertEqual(result.state, "cancelled")
        self.assertEqual(result.cancellation_source, "trip_update")
        self.assertIsNone(result.next_stop)
        self.assertIsNone(result.last_passed_stop)
        self.assertFalse(result.data_quality.static_join_successful)
        self.assertEqual(result.stop_updates[0].current_stop.id, "central-p1")
        self.assertIsNone(result.stop_updates[0].current_stop.name)
        self.assertIn("Static GTFS join unavailable", result.data_quality.warnings[0])

    def test_stale_entity_time_bounds_progress_and_confidence(self):
        transport = FakeBinaryTransport(trip_updates=_stale_trip_update_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )

        result = ServiceStatusResult.model_validate(
            client.service_status_request(
                ServiceStatusInput.model_validate({"service_id": SERVICE_ID})
            )
        )

        self.assertEqual(result.state, "scheduled")
        self.assertEqual(result.next_stop.current_stop.id, "central-p1")
        self.assertEqual(result.observation_timestamp.astimezone(SYDNEY).hour, 17)
        self.assertEqual(result.data_quality.observation_age_seconds, 35 * 60)
        self.assertEqual(result.confidence.level, "low")

    def test_bundle_only_cancellation_fails_closed_without_bundle_identity(self):
        transport = FakeBinaryTransport(trip_updates=_bundle_cancellation_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )

        with self.assertRaises(TfnswApiError) as raised:
            client.service_status_request(
                ServiceStatusInput.model_validate({"service_id": SERVICE_ID})
            )
        self.assertEqual(raised.exception.code, "unverified_cancellation")
        self.assertIn("bundle-20260812", raised.exception.message)
        self.assertIn("No cancellation was inferred", raised.exception.message)

    def test_unverified_bundle_cancellation_fails_closed(self):
        client = RealtimeClient(
            "test-key",
            transport=FakeBinaryTransport(trip_updates=_bundle_cancellation_feed()),
            trip_planner=self.planner,
            static_gtfs=UnavailableStaticGtfs(),
            now=lambda: self.now,
        )

        with self.assertRaises(TfnswApiError) as raised:
            client.service_status_request(
                ServiceStatusInput.model_validate({"service_id": SERVICE_ID})
            )
        self.assertEqual(raised.exception.code, "unverified_cancellation")

    def test_active_trip_update_wins_over_conflicting_bundle(self):
        client = RealtimeClient(
            "test-key",
            transport=FakeBinaryTransport(
                trip_updates=_trip_update_feed(include_bundle_cancellation=True)
            ),
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )

        result = ServiceStatusResult.model_validate(
            client.service_status_request(
                ServiceStatusInput.model_validate({"service_id": SERVICE_ID})
            )
        )

        self.assertFalse(result.is_cancelled)
        self.assertEqual(result.cancellation_source, "none")
        self.assertIn("preferred", result.data_quality.warnings[-1])

    def test_tfnsw_wheelchair_enum_zero_means_unavailable(self):
        decoded = decode_vehicle_positions(_vehicle_feed(wheelchair=0))
        descriptor = decoded.vehicles[SERVICE_ID].descriptor
        self.assertIsNotNone(descriptor)
        self.assertFalse(descriptor.wheelchair_accessible)

    def test_output_contract_rejects_false_occupancy_claim(self):
        transport = FakeBinaryTransport(vehicle_positions=_empty_feed())
        client = RealtimeClient(
            "test-key",
            transport=transport,
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        raw = client.vehicle_position_request(
            VehiclePositionInput.model_validate({"service_id": SERVICE_ID})
        )
        raw["occupancy"]["reported"] = True
        raw["occupancy"]["source"] = "none"
        with self.assertRaises(ValidationError):
            VehiclePositionResult.model_validate(raw)

    def test_bus_status_uses_bus_identity_and_not_train_trip_delay(self):
        client = RealtimeClient(
            "test-key",
            mode="bus",
            transport=FakeBinaryTransport(trip_updates=_trip_delay_feed()),
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        result = ServiceStatusResult.model_validate(
            client.service_status_request(
                BusServiceStatusInput.model_validate({"service_id": SERVICE_ID})
            )
        )

        self.assertEqual(result.query.mode, "bus")
        self.assertEqual(result.service.mode, "bus")
        self.assertEqual(result.stop_updates[0].prediction_source, "schedule")

    def test_bus_vehicle_ignores_train_carriage_extension(self):
        client = RealtimeClient(
            "test-key",
            mode="bus",
            transport=FakeBinaryTransport(vehicle_positions=_vehicle_feed()),
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        result = VehiclePositionResult.model_validate(
            client.vehicle_position_request(
                BusVehiclePositionInput.model_validate({"service_id": SERVICE_ID})
            )
        )

        self.assertEqual(result.service.mode, "bus")
        self.assertEqual(result.occupancy.source, "vehicle")
        self.assertEqual(result.occupancy.carriages, [])
        self.assertIn("bus", result.occupancy.coverage_note.lower())

    def test_metro_status_uses_metro_mode_without_trip_delay_fallback(self):
        client = RealtimeClient(
            "test-key",
            mode="metro",
            transport=FakeBinaryTransport(trip_updates=_trip_delay_feed()),
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        result = ServiceStatusResult.model_validate(
            client.service_status_request(
                MetroServiceStatusInput.model_validate({"service_id": SERVICE_ID})
            )
        )

        self.assertEqual(result.query.mode, "metro")
        self.assertEqual(result.service.mode, "metro")
        self.assertEqual(result.stop_updates[0].prediction_source, "schedule")

    def test_light_rail_vehicle_ignores_train_carriage_extension(self):
        client = RealtimeClient(
            "test-key",
            mode="light_rail",
            transport=FakeBinaryTransport(vehicle_positions=_vehicle_feed()),
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        result = VehiclePositionResult.model_validate(
            client.vehicle_position_request(
                LightRailVehiclePositionInput.model_validate({"service_id": SERVICE_ID})
            )
        )

        self.assertEqual(result.service.mode, "light_rail")
        self.assertEqual(result.occupancy.source, "vehicle")
        self.assertEqual(result.occupancy.carriages, [])

    def test_ferry_status_uses_ferry_mode_without_trip_delay_fallback(self):
        client = RealtimeClient(
            "test-key",
            mode="ferry",
            transport=FakeBinaryTransport(trip_updates=_trip_delay_feed()),
            trip_planner=self.planner,
            static_gtfs=self.static,
            now=lambda: self.now,
        )
        result = ServiceStatusResult.model_validate(
            client.service_status_request(
                FerryServiceStatusInput.model_validate({"service_id": SERVICE_ID})
            )
        )

        self.assertEqual(result.query.mode, "ferry")
        self.assertEqual(result.service.mode, "ferry")
        self.assertEqual(result.stop_updates[0].prediction_source, "schedule")


def _feed_header(feed):
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(datetime(2026, 8, 12, 8, 5, tzinfo=UTC).timestamp())


def _empty_feed() -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    return feed.SerializeToString()


def _alert_feed() -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    entity = feed.entity.add()
    entity.id = "trackwork-1"
    alert = entity.alert
    period = alert.active_period.add()
    period.start = int(datetime(2026, 8, 12, 7, 0, tzinfo=UTC).timestamp())
    period.end = int(datetime(2026, 8, 12, 9, 0, tzinfo=UTC).timestamp())
    selector = alert.informed_entity.add()
    selector.route_id = "T1"
    selector.stop_id = "G204313"
    selector.trip.trip_id = SERVICE_ID
    alert.cause = alert.MAINTENANCE
    alert.effect = alert.MODIFIED_SERVICE
    alert.severity_level = alert.WARNING
    alert.header_text.translation.add(text="Trackwork")
    alert.description_text.translation.add(text="Use alternative transport")
    alert.url.translation.add(text="https://transportnsw.info/alerts")
    return feed.SerializeToString()


def _trip_update_feed(
    *, include_bundle_cancellation: bool = False, route_id: str = "NTH_2a"
) -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    entity = feed.entity.add()
    entity.id = "trip-1"
    update = entity.trip_update
    update.trip.trip_id = SERVICE_ID
    update.trip.route_id = route_id
    update.trip.schedule_relationship = update.trip.REPLACEMENT

    first = update.stop_time_update.add()
    first.stop_sequence = 1
    first.stop_id = "central-p1"
    second = update.stop_time_update.add()
    second.stop_sequence = 2
    second.stop_id = "strath-p3"
    second.arrival.time = int(datetime(2026, 8, 12, 8, 12, tzinfo=UTC).timestamp())
    third = update.stop_time_update.add()
    third.stop_sequence = 3
    third.stop_id = "burwood-p4"
    third.schedule_relationship = third.SKIPPED
    fourth = update.stop_time_update.add()
    fourth.stop_sequence = 4
    fourth.stop_id = "parra-p2"
    fourth.departure.delay = 300
    if include_bundle_cancellation:
        _add_bundle_cancellation(feed)
    return feed.SerializeToString()


def _trip_delay_feed() -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    entity = feed.entity.add()
    entity.id = "bus-trip-delay"
    update = entity.trip_update
    update.trip.trip_id = SERVICE_ID
    update.trip.route_id = "route-333"
    update.delay = 600
    return feed.SerializeToString()


def _vehicle_feed(
    *,
    wheelchair: int = 1,
    route_id: str = "NTH_2a",
    label: str = "18:00 Central to Parramatta",
) -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    entity = feed.entity.add()
    entity.id = "vehicle-1"
    vehicle = entity.vehicle
    vehicle.trip.trip_id = SERVICE_ID
    vehicle.trip.route_id = route_id
    vehicle.vehicle.label = label
    detail = vehicle.vehicle.Extensions[pb.tfnsw_vehicle_descriptor]
    detail.vehicle_model = "Waratah B Set"
    detail.air_conditioned = True
    detail.wheelchair_accessible = wheelchair
    vehicle.position.latitude = -33.8837
    vehicle.position.longitude = 151.2065
    vehicle.position.bearing = 275.0
    vehicle.current_stop_sequence = 2
    vehicle.current_status = vehicle.IN_TRANSIT_TO
    vehicle.timestamp = int(datetime(2026, 8, 12, 8, 4, 30, tzinfo=UTC).timestamp())
    vehicle.occupancy_status = vehicle.MANY_SEATS_AVAILABLE
    for position, occupancy in (
        (1, pb.CarriageDescriptor.MANY_SEATS_AVAILABLE),
        (2, pb.CarriageDescriptor.FEW_SEATS_AVAILABLE),
    ):
        carriage = vehicle.Extensions[pb.consist].add()
        carriage.position_in_consist = position
        carriage.occupancy_status = occupancy
    return feed.SerializeToString()


def _cancelled_trip_feed() -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    entity = feed.entity.add()
    entity.id = "cancelled-trip"
    update = entity.trip_update
    update.trip.trip_id = SERVICE_ID
    update.trip.schedule_relationship = update.trip.CANCELED
    stop = update.stop_time_update.add()
    stop.stop_sequence = 1
    stop.stop_id = "central-p1"
    return feed.SerializeToString()


def _bundle_cancellation_feed() -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    _add_bundle_cancellation(feed)
    return feed.SerializeToString()


def _add_bundle_cancellation(feed) -> None:
    entity = feed.entity.add()
    entity.id = "bundle-cancellation"
    bundle = entity.Extensions[pb.update]
    bundle.GTFSStaticBundle = "bundle-20260812"
    bundle.update_sequence = 7
    bundle.cancelled_trip.append(SERVICE_ID)


def _stale_trip_update_feed() -> bytes:
    feed = pb.FeedMessage()
    _feed_header(feed)
    entity = feed.entity.add()
    entity.id = "stale-trip"
    update = entity.trip_update
    update.trip.trip_id = SERVICE_ID
    update.timestamp = int(datetime(2026, 8, 12, 7, 30, tzinfo=UTC).timestamp())
    for sequence, stop_id in enumerate(
        ("central-p1", "strath-p2", "burwood-p4", "parra-p2"), start=1
    ):
        stop = update.stop_time_update.add()
        stop.stop_sequence = sequence
        stop.stop_id = stop_id
    return feed.SerializeToString()


if __name__ == "__main__":
    unittest.main()
