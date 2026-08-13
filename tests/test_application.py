from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from hermes_sydney_transport.application.trip_planner import (
    GetAlerts,
    GetDepartures,
    SearchStops,
)
from hermes_sydney_transport.application.trip_planner_policy import (
    journey_from_candidate,
)
from hermes_sydney_transport.models.inputs import (
    AlertsInput,
    DeparturesInput,
    StationSearchInput,
)
from hermes_sydney_transport.models.outputs import Alert, Route, Station, TripLeg
from hermes_sydney_transport.ports.trip_planner import (
    DepartureBoard,
    DepartureCandidate,
    JourneyCandidate,
)


class FixedClock:
    def now(self):
        return datetime(2026, 8, 12, 2, 0, tzinfo=UTC)


class TripPlannerApplicationTests(unittest.TestCase):
    def test_search_policy_filters_modes_sorts_and_limits(self):
        port = SimpleNamespace(
            station_candidates=lambda request: (
                _station("bus", "Bus stop", [5], 100, True),
                _station("second", "Central B", [1], 80, False),
                _station("best", "Central A", [1], 90, True),
            )
        )
        request = StationSearchInput.model_validate(
            {"query": "Central", "modes": ["train"], "limit": 2}
        )

        result = SearchStops(port, FixedClock()).execute(request)

        self.assertEqual(
            [station.id for station in result.stations], ["best", "second"]
        )

    def test_departure_policy_derives_delay_and_preserves_unknown(self):
        planned = datetime(2026, 8, 12, 2, 10, tzinfo=UTC)
        port = SimpleNamespace(
            departure_candidates=lambda request: DepartureBoard(
                station=None,
                candidates=(
                    _departure("train", planned, None),
                    _departure(
                        "train", planned, datetime(2026, 8, 12, 2, 16, tzinfo=UTC)
                    ),
                    _departure("bus", planned, planned),
                ),
            )
        )
        request = DeparturesInput.model_validate(
            {"stop_id": "200060", "modes": ["train"]},
            context={"now": FixedClock().now()},
        )

        result = GetDepartures(port, FixedClock()).execute(request)

        self.assertEqual(
            [item.status for item in result.departures], ["unknown", "delayed"]
        )
        self.assertEqual(result.departures[1].delay_minutes, 6)

    def test_alert_policy_keeps_latest_revision_then_applies_priority(self):
        port = SimpleNamespace(
            alert_candidates=lambda request: (
                _alert("same", 1, "veryHigh", "Old"),
                _alert("same", 2, "low", "New"),
                _alert("other", 1, "high", "Other"),
            )
        )

        result = GetAlerts(port, FixedClock()).execute(
            AlertsInput.model_validate({"modes": ["train"]})
        )

        self.assertEqual([item.id for item in result.alerts], ["other", "same"])
        self.assertEqual(result.alerts[1].title, "New")

    def test_journey_interchanges_count_every_supported_transit_mode(self):
        candidate = JourneyCandidate(
            legs=(
                _leg("metro"),
                _leg("walk"),
                _leg("light_rail"),
                _leg("ferry"),
            ),
            declared_interchanges=None,
            rating=None,
        )

        result = journey_from_candidate(candidate)

        self.assertEqual(result.interchanges, 2)


def _station(
    station_id: str, name: str, modes: list[int], quality: int, best: bool
) -> Station:
    return Station(
        id=station_id,
        name=name,
        short_name=None,
        parent_name=None,
        modes=modes,
        match_quality=quality,
        is_best=best,
        coordinates=None,
    )


def _departure(mode, planned, estimated):
    return DepartureCandidate(
        mode=mode,
        planned_time=planned,
        estimated_time=estimated,
        cancelled=None,
        platform=None,
        route=Route(
            id=None,
            number=None,
            name=None,
            icon_id=None,
            product_class=1 if mode == "train" else 5,
        ),
        destination=None,
        operator=None,
        trip_code=None,
        service_id=None,
        alert_ids=(),
    )


def _alert(alert_id, version, priority, title):
    return Alert(
        id=alert_id,
        version=version,
        priority=priority,
        type=None,
        title=title,
        content="",
        sms_summary="",
        affected_lines=[],
        affected_stops=[],
        created_at=None,
        last_modified=datetime(2026, 8, 12, version, tzinfo=UTC),
        validity=[],
        availability=[],
        provider=None,
        source_name=None,
        url=None,
        url_text="",
    )


def _leg(mode: str) -> TripLeg:
    stop = {
        "id": None,
        "name": None,
        "short_name": None,
        "parent_id": None,
        "platform": None,
        "departure_time_planned": None,
        "departure_time_estimated": None,
        "arrival_time_planned": None,
        "arrival_time_estimated": None,
        "wheelchair_accessible": None,
        "coordinates": None,
    }
    return TripLeg.model_validate(
        {
            "mode": mode,
            "duration_seconds": 60,
            "duration_minutes": 1,
            "distance_metres": None,
            "is_realtime_controlled": None,
            "realtime_status": None,
            "cancelled": None,
            "origin": stop,
            "destination": stop,
            "route": {
                "id": None,
                "number": None,
                "name": None,
                "description": None,
                "product_class": None,
            },
            "operator": None,
            "service_destination": None,
            "stop_count": 0,
            "stops": [],
            "alert_ids": [],
            "hints": [],
        }
    )


if __name__ == "__main__":
    unittest.main()
