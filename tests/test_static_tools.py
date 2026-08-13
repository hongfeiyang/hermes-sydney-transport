from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from hermes_sydney_transport.adapters.tfnsw.complete_gtfs import (
    CompleteGtfsTimetableAdapter,
)
from hermes_sydney_transport.adapters.tfnsw.facilities import TfnswFacilitiesAdapter
from hermes_sydney_transport.adapters.tfnsw.static_resources import StaticDownload
from hermes_sydney_transport.application.accessibility import GetStopAccessibility
from hermes_sydney_transport.application.timetable import GetRouteTimetable
from hermes_sydney_transport.models.errors import DomainError
from hermes_sydney_transport.models.static_inputs import (
    RouteTimetableInput,
    StopAccessibilityInput,
)
from hermes_sydney_transport.ports.alerts import (
    AlertQuery,
    AlertRecord,
    AlertSelector,
    AlertTimeRange,
)
from hermes_sydney_transport.ports.facilities import (
    FacilityCoordinates,
    FacilityRecord,
    FacilitySnapshot,
    LiftRecord,
)
from hermes_sydney_transport.ports.realtime import TransportMode
from hermes_sydney_transport.ports.timetable import (
    RouteTimetableSnapshot,
    TimetableRouteRecord,
    TimetableStopRecord,
    TimetableTripRecord,
)

NOW = datetime(2026, 8, 17, 0, 30, tzinfo=UTC)
UPDATED = datetime(2026, 8, 16, 22, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeFacilities:
    def get_facility(self, stop_id: str) -> FacilitySnapshot:
        return FacilitySnapshot(
            matched_by="efa_id",
            facility=FacilityRecord(
                name="Central Station",
                efa_id=stop_id,
                tsn="200060",
                address="Eddy Avenue, Haymarket",
                phone=None,
                coordinates=FacilityCoordinates(-33.883, 151.207),
                transport_modes=("Train",),
                accessibility_classification="independent_access",
                accessibility_features=("Accessible toilet",),
                facilities=("Toilets",),
                morning_staffed_hours="05:00-09:00",
                afternoon_staffed_hours=None,
                short_platform=False,
            ),
            lifts=(LiftRecord("LIFT-1", "Platform lift", UPDATED),),
            source_updated_at=UPDATED,
            cache_stale=False,
        )


class FakeAlerts:
    def __init__(self, error: bool = False) -> None:
        self.error = error
        self.query: AlertQuery | None = None

    def find_alerts(self, query: AlertQuery) -> tuple[AlertRecord, ...]:
        self.query = query
        if self.error:
            raise DomainError("realtime_feed_unavailable", "alerts unavailable")
        return (
            AlertRecord(
                id="lift-work",
                mode=TransportMode.TRAIN,
                source_feed="sydneytrains",
                title="Lift maintenance",
                description="Use the northern entrance.",
                cause="maintenance",
                effect="accessibility_issue",
                severity="warning",
                url=None,
                active_periods=(AlertTimeRange(NOW, None),),
                selectors=(AlertSelector(None, None, None, "10101100", None, None),),
                route_ids=(),
                stop_ids=("10101100",),
                trip_ids=(),
            ),
        )


class FakeTimetable:
    def __init__(self) -> None:
        self.service_date: date | None = None

    def get_route_timetable(
        self, request: RouteTimetableInput, service_date: date
    ) -> RouteTimetableSnapshot:
        self.service_date = service_date
        stop = TimetableStopRecord(
            stop_id="10101100",
            stop_name="Central Station",
            sequence=1,
            arrival=NOW,
            departure=NOW,
            pickup_type=0,
            drop_off_type=0,
        )
        trip = TimetableTripRecord(
            trip_id="complete-trip-1",
            headsign="Parramatta",
            direction_id=0,
            wheelchair_accessibility="accessible",
            first_departure=NOW,
            last_arrival=NOW,
            stop_times=(stop,),
            stop_times_truncated=False,
        )
        return RouteTimetableSnapshot(
            route=TimetableRouteRecord(
                id=request.route_id,
                agency_id="Sydney Trains",
                short_name="T1",
                long_name="North Shore & Western Line",
                description=None,
                route_type=2,
            ),
            service_date=service_date,
            trips=(trip,),
            source_updated_at=UPDATED,
            cache_stale=False,
        )


class StaticUseCaseTests(unittest.TestCase):
    def test_timetable_rejects_dates_that_cannot_safely_form_overnight_times(self):
        with self.assertRaises(ValidationError):
            RouteTimetableInput.model_validate(
                {"route_id": "R1", "service_date": "9999-12-31"}
            )

    def test_accessibility_separates_inventory_from_current_warning(self):
        alerts = FakeAlerts()
        result = GetStopAccessibility(FakeFacilities(), alerts, FixedClock()).execute(
            StopAccessibilityInput.model_validate({"stop_id": "10101100"})
        )

        self.assertEqual(result.matched_by, "efa_id")
        self.assertEqual(
            result.facility.accessibility_classification, "independent_access"
        )
        self.assertEqual(result.lifts[0].operational_status, "unknown")
        self.assertEqual(result.operational_status, "disruption_reported")
        self.assertEqual(result.current_warning_status, "warnings_reported")
        self.assertTrue(result.remote_content_is_untrusted)
        self.assertEqual(alerts.query.stop_id, "10101100")
        self.assertEqual(alerts.query.effects, ("accessibility_issue",))
        self.assertEqual(set(alerts.query.modes), set(TransportMode))

    def test_accessibility_preserves_static_result_when_alerts_fail(self):
        result = GetStopAccessibility(
            FakeFacilities(), FakeAlerts(error=True), FixedClock()
        ).execute(StopAccessibilityInput.model_validate({"stop_id": "10101100"}))

        self.assertEqual(result.current_warning_status, "unavailable")
        self.assertEqual(result.operational_status, "unknown")
        self.assertEqual(result.current_warning_count, 0)
        self.assertIsNotNone(result.facility)

    def test_timetable_defaults_to_sydney_service_date_and_marks_namespace(self):
        port = FakeTimetable()
        result = GetRouteTimetable(port, FixedClock()).execute(
            RouteTimetableInput.model_validate({"route_id": "R1"})
        )

        self.assertEqual(port.service_date, date(2026, 8, 17))
        self.assertEqual(result.identifier_namespace, "complete_gtfs")
        self.assertFalse(result.identifiers_match_realtime_feeds)
        self.assertEqual(result.trips[0].complete_gtfs_trip_id, "complete-trip-1")


class StaticAdapterTests(unittest.TestCase):
    def test_facilities_match_efa_before_tsn_and_do_not_infer_lift_status(self):
        payloads = {
            "location_facilities": _facility_csv(),
            "interchange_lifts": _lift_workbook(),
        }
        with tempfile.TemporaryDirectory() as directory:
            adapter = TfnswFacilitiesAdapter(
                FixtureTransport(payloads),
                database_path=Path(directory) / "facilities.sqlite3",
            )
            self.addCleanup(adapter.close)

            snapshot = adapter.get_facility("10101100")
            tsn_snapshot = adapter.get_facility("200060")

        self.assertEqual(snapshot.matched_by, "efa_id")
        self.assertEqual(tsn_snapshot.matched_by, "tsn")
        self.assertEqual(
            snapshot.facility.accessibility_features, ("Accessible toilet",)
        )
        self.assertEqual(snapshot.facility.facilities, ("Toilets", "Taxi rank"))
        self.assertEqual(snapshot.lifts[0].functional_location_code, "LIFT-1")

    def test_complete_gtfs_applies_calendar_exception_and_after_midnight_time(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = CompleteGtfsTimetableAdapter(
                FixtureTransport({"complete_gtfs": _complete_gtfs()}),
                database_path=Path(directory) / "complete.sqlite3",
            )
            self.addCleanup(adapter.close)
            request = RouteTimetableInput.model_validate(
                {"route_id": "R1", "service_date": "2026-08-18", "limit": 5}
            )

            snapshot = adapter.get_route_timetable(request, request.service_date)

        self.assertEqual([trip.trip_id for trip in snapshot.trips], ["trip-added"])
        self.assertEqual(snapshot.trips[0].first_departure.day, 18)
        self.assertEqual(snapshot.trips[0].last_arrival.day, 19)
        self.assertEqual(snapshot.trips[0].last_arrival.hour, 1)


class FixtureTransport:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads

    def download(
        self,
        resource: str,
        destination: Path,
        *,
        if_modified_since: datetime | None = None,
    ) -> StaticDownload:
        destination.write_bytes(self.payloads[resource])
        return StaticDownload(not_modified=False, last_modified=UPDATED)


def _facility_csv() -> bytes:
    return (
        b"LOCATION_NAME,TSN,EFA_ID,ACCESSIBILITY,FACILITIES,TRANSPORT_MODE,"
        b"ADDRESS,PHONE,LATITUDE,LONGITUDE,MORNING_PEAK,AFTERNOON_PEAK,SHORT_PLATFORM\n"
        b'Central Station,200060,10101100,"Independent Access|Accessible toilet",'
        b'"Toilets|Taxi rank",Train,"Eddy Avenue, Haymarket",, -33.883,151.207,'
        b"05:00-09:00,,False\n"
    )


def _lift_workbook() -> bytes:
    strings = (
        "tsn",
        "_updated_at",
        "sydney_trains__lift_functional_location_code",
        "lift_location_description",
        "200060",
        "2026-08-16 22:00:00 UTC",
        "LIFT-1",
        "Platform lift",
    )
    shared = "".join(f"<si><t>{value}</t></si>" for value in strings)
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>4</v></c><c r="B2" t="s"><v>5</v></c>'
        '<c r="C2" t="s"><v>6</v></c><c r="D2" t="s"><v>7</v></c></row>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared}</sst>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{rows}</sheetData></worksheet>',
        )
    return output.getvalue()


def _complete_gtfs() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "routes.txt",
            "route_id,agency_id,route_short_name,route_long_name,route_desc,route_type\n"
            "R1,Sydney Trains,T1,North Shore & Western,,2\n",
        )
        archive.writestr(
            "stops.txt",
            "stop_id,stop_name\n10101100,Central Station\n2150100,Parramatta Station\n",
        )
        archive.writestr(
            "calendar.txt",
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "base,1,1,1,1,1,0,0,20260101,20261231\n"
            "special,0,0,0,0,0,0,0,20260101,20261231\n",
        )
        archive.writestr(
            "calendar_dates.txt",
            "service_id,date,exception_type\nbase,20260818,2\nspecial,20260818,1\n",
        )
        archive.writestr(
            "trips.txt",
            "route_id,service_id,trip_id,trip_headsign,direction_id,wheelchair_accessible\n"
            "R1,base,trip-removed,Parramatta,0,1\n"
            "R1,special,trip-added,Parramatta,0,1\n",
        )
        archive.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\n"
            "trip-removed,23:00:00,23:00:00,10101100,1,0,0\n"
            "trip-added,23:55:00,23:55:00,10101100,1,0,0\n"
            "trip-added,25:05:00,25:05:00,2150100,2,0,0\n",
        )
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
