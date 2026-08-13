from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from hermes_sydney_transport.adapters.tfnsw.binary_transport import BinaryResponse
from hermes_sydney_transport.adapters.tfnsw.static_gtfs import StaticGtfsRepository
from hermes_sydney_transport.models.errors import DomainError as TfnswApiError


class FakeTransport:
    def __init__(self, body: bytes):
        self.body = body
        self.calls = []

    def get(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return BinaryResponse(
            data=self.body,
            content_type="application/zip",
            last_modified="Wed, 12 Aug 2026 08:00:00 GMT",
        )


class NotModifiedTransport:
    def __init__(self):
        self.calls = []

    def get(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return BinaryResponse(
            data=None,
            content_type="application/zip",
            last_modified="Wed, 12 Aug 2026 08:00:00 GMT",
            not_modified=True,
        )


class StaticGtfsTests(unittest.TestCase):
    def test_lazy_trip_join_and_stop_metadata_are_cached(self):
        transport = FakeTransport(_bundle())
        repository = StaticGtfsRepository(transport)
        self.addCleanup(repository.close)

        trip = repository.get_trip("trip-1")
        repeated = repository.get_trip("trip-1")

        self.assertIs(trip, repeated)
        self.assertIsNotNone(trip)
        self.assertEqual(trip.route_short_name, "T1")
        self.assertEqual(trip.headsign, "Parramatta")
        self.assertEqual(len(trip.stop_times), 2)
        stops = repository.get_stop_references(("central-p1", "parra-p2"))
        self.assertEqual(stops["central-p1"].parent_station_name, "Central Station")
        self.assertEqual(stops["central-p1"].platform, "P01")
        self.assertEqual(stops["parra-p2"].parent_station_name, "Parramatta Station")
        self.assertEqual(len(transport.calls), 1)

    def test_invalid_zip_fails_closed(self):
        repository = StaticGtfsRepository(FakeTransport(b"not-a-zip"))
        self.addCleanup(repository.close)
        with self.assertRaises(TfnswApiError) as raised:
            repository.get_trip("trip-1")
        self.assertEqual(raised.exception.code, "static_data_invalid")

    def test_oversized_expanded_entry_is_rejected_before_csv_parsing(self):
        body = _bundle(extra_stops="x" * (5 * 1024 * 1024))
        repository = StaticGtfsRepository(FakeTransport(body))
        self.addCleanup(repository.close)
        with self.assertRaises(TfnswApiError) as raised:
            repository.get_trip("trip-1")
        self.assertEqual(raised.exception.code, "static_data_invalid")
        self.assertRegex(raised.exception.message, "expanded-size|compression ratio")

    def test_persistent_index_is_reused_after_conditional_not_modified(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "hermes_sydney_transport.adapters.tfnsw.static_gtfs.time.monotonic",
                side_effect=(1.0, 2.0),
            ),
        ):
            path = Path(directory) / "static.sqlite3"
            initial = StaticGtfsRepository(FakeTransport(_bundle()), database_path=path)
            self.assertIsNotNone(initial.get_trip("trip-1"))
            initial.close()

            transport = NotModifiedTransport()
            reopened = StaticGtfsRepository(transport, database_path=path)
            self.addCleanup(reopened.close)
            trip = reopened.get_trip("trip-1")

            self.assertIsNotNone(trip)
            self.assertEqual(trip.route_short_name, "T1")
            self.assertEqual(
                transport.calls[0][1]["if_modified_since"],
                "Wed, 12 Aug 2026 08:00:00 GMT",
            )


def _bundle(*, extra_stops: str = "") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "routes.txt",
            "route_id,route_short_name,route_long_name\n"
            "route-1,T1,North Shore & Western Line\n",
        )
        archive.writestr(
            "stops.txt",
            "stop_id,stop_name,parent_station,platform_code\n"
            "central,Central Station,,\n"
            "central-p1,Central Station Platform 1,central,P01\n"
            "parra,Parramatta Station,,\n"
            "parra-p2,Parramatta Station Platform 2,parra,\n" + extra_stops,
        )
        archive.writestr(
            "trips.txt",
            "route_id,service_id,trip_id,trip_headsign,direction_id,vehicle_category_id\n"
            "route-1,weekday,trip-1,Parramatta,0,B8\n",
        )
        archive.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign\n"
            "trip-1,18:00:00,18:00:00,central-p1,1,Parramatta\n"
            "trip-1,18:25:00,18:25:00,parra-p2,2,Parramatta\n",
        )
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
