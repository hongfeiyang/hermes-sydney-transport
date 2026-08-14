from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from hermes_sydney_transport.adapters.tfnsw.platform import HttpPayload
from hermes_sydney_transport.adapters.tfnsw.repositories.traffic_counts import (
    TfnswTrafficCountsRepository,
)
from hermes_sydney_transport.application.traffic_counts import (
    GetHourlyTraffic,
    GetTrafficSummary,
    SearchTrafficStations,
)
from hermes_sydney_transport.models.traffic_inputs import (
    TrafficStationSearchInput,
    TrafficVolumeHourlyInput,
    TrafficVolumeSummaryInput,
)
from hermes_sydney_transport.models.traffic_outputs import (
    TrafficStationSearchResult,
    TrafficVolumeHourlyResult,
    TrafficVolumeSummaryResult,
)


class FakeClock:
    def now(self):
        return datetime(2026, 8, 12, 2, 0, tzinfo=UTC)


class FakeTrafficTransport:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.queries = []

    def fetch(self, endpoint, *, params=None, if_modified_since=None):
        self.queries.append(params["q"])
        return HttpPayload(
            json.dumps(self.payloads.pop(0)).encode(), "application/json", None
        )


def payload(rows):
    return {
        "rows": rows,
        "fields": {"station_id": {"type": "string"}},
        "total_rows": len(rows),
    }


class TrafficVolumeClientTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def test_station_search_uses_fixed_columns_and_escaped_literal(self):
        transport = FakeTrafficTransport(
            [
                payload(
                    [
                        {
                            "station_key": 15828002,
                            "station_id": "7211",
                            "name": "Lily Lane",
                            "road_name": "Lily Lane",
                            "suburb": "Adamstown",
                            "post_code": "2289",
                            "wgs84_latitude": -32.940571,
                            "wgs84_longitude": 151.71312,
                            "permanent_station": 1,
                            "vehicle_classifier": 1,
                            "quality_rating": 5,
                        }
                    ]
                )
            ]
        )
        use_case = SearchTrafficStations(
            TfnswTrafficCountsRepository(transport), self.clock
        )
        request = TrafficStationSearchInput.model_validate({"query": "O'Brien"})

        result = TrafficStationSearchResult.model_validate(use_case.execute(request))

        self.assertEqual(result.stations[0].station_key, "15828002")
        self.assertTrue(result.stations[0].permanent_station)
        sql = transport.queries[0]
        self.assertIn("O''Brien", sql)
        self.assertNotIn("SELECT *", sql.upper())
        self.assertIn("LIMIT 10", sql)

    def test_summary_normalises_quality_and_dates(self):
        transport = FakeTrafficTransport(
            [
                payload(
                    [
                        {
                            "station_key": 55318,
                            "station_id": "02015",
                            "traffic_direction_seq": 2,
                            "traffic_direction_name": "PRESCRIBED AND COUNTER",
                            "cardinal_direction_seq": 9,
                            "cardinal_direction_name": "BOTH",
                            "classification_seq": 0,
                            "classification_type": "UNCLASSIFIED",
                            "count_type": "TRAFFIC COUNT",
                            "year": 2018,
                            "period": "WEEKDAYS",
                            "partial_year": False,
                            "latest_date": "2018-12-31T00:00:00Z",
                            "traffic_count": 39273,
                            "data_start_date": None,
                            "data_end_date": None,
                            "data_duration": None,
                            "data_availability": -1,
                            "data_reliability": -1,
                            "data_quality_indicator": 0,
                        }
                    ]
                )
            ]
        )
        use_case = GetTrafficSummary(
            TfnswTrafficCountsRepository(transport), self.clock
        )
        request = TrafficVolumeSummaryInput.model_validate(
            {"station_id": "02015", "year": 2018}
        )

        result = TrafficVolumeSummaryResult.model_validate(use_case.execute(request))

        self.assertEqual(result.summaries[0].traffic_count, 39273)
        self.assertEqual(result.summaries[0].latest_date.year, 2018)
        self.assertIn("year = 2018", transport.queries[0])

    def test_hourly_supports_sample_string_fields_and_24_values(self):
        row = {
            "station_key": "58308",
            "traffic_direction_seq": "0",
            "cardinal_direction_seq": "3",
            "classification_seq": "0",
            "date": "2010-05-24 00:00:00+00",
            "year": "2010",
            "month": 5,
            "day_of_week": "1",
            "public_holiday": "false",
            "school_holiday": "false",
            "daily_total": "276",
            **{f"hour_{hour:02d}": hour for hour in range(24)},
        }
        transport = FakeTrafficTransport([payload([row])])
        use_case = GetHourlyTraffic(TfnswTrafficCountsRepository(transport), self.clock)
        request = TrafficVolumeHourlyInput.model_validate(
            {
                "station_key": "58308",
                "dataset": "sample",
                "start_date": "2010-05-24",
                "end_date": "2010-05-24",
            }
        )

        result = TrafficVolumeHourlyResult.model_validate(use_case.execute(request))

        self.assertEqual(len(result.rows[0].hourly_counts), 24)
        self.assertEqual(result.rows[0].hourly_counts[23], 23)
        self.assertIn("road_traffic_counts_hourly_sample", transport.queries[0])

    def test_inputs_reject_raw_sql_shape_and_unbounded_dates(self):
        with self.assertRaises(ValidationError):
            TrafficStationSearchInput.model_validate({})
        with self.assertRaises(ValidationError):
            TrafficStationSearchInput.model_validate({"q": "SELECT * FROM secret"})
        with self.assertRaises(ValidationError):
            TrafficVolumeHourlyInput.model_validate(
                {
                    "station_key": "1 OR 1=1",
                    "dataset": "sample",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-02",
                }
            )
        with self.assertRaises(ValidationError):
            TrafficVolumeHourlyInput.model_validate(
                {
                    "station_key": "123",
                    "dataset": "sample",
                    "start_date": "2026-01-01",
                    "end_date": "2026-03-01",
                }
            )


if __name__ == "__main__":
    unittest.main()
