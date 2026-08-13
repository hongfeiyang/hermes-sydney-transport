"""NSW Roads Traffic Volume Counts use cases."""

from __future__ import annotations

from datetime import UTC

from ..models.metadata import ATTRIBUTION
from ..models.traffic_inputs import (
    TrafficStationSearchInput,
    TrafficVolumeHourlyInput,
    TrafficVolumeSummaryInput,
)
from ..models.traffic_outputs import (
    TrafficStationSearchResult,
    TrafficVolumeHourlyResult,
    TrafficVolumeSummaryResult,
)
from ..ports.clock import Clock
from ..ports.traffic_counts import (
    HourlyQuery,
    StationQuery,
    SummaryQuery,
    TrafficCountsPort,
)

_SOURCE = "TfNSW NSW Roads Traffic Volume Counts API"
_QUALITY_NOTE = (
    "Traffic counts are published monthly from roadside devices. TfNSW documents "
    "coverage and quality checks, but weather, power or device faults can affect "
    "counts and heavy-vehicle classification is intermittent."
)


class SearchTrafficStations:
    def __init__(self, port: TrafficCountsPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: TrafficStationSearchInput) -> TrafficStationSearchResult:
        page = self._port.search_stations(
            StationQuery(
                text=request.query,
                station_id=request.station_id,
                permanent_only=request.permanent_only,
                limit=request.limit,
            )
        )
        return TrafficStationSearchResult(
            fetched_at=self._clock.now().astimezone(UTC),
            source=_SOURCE,
            attribution=ATTRIBUTION,
            query=request.query,
            station_id=request.station_id,
            permanent_only=request.permanent_only,
            stations=list(page.records),
            count=len(page.records),
            upstream_total_rows=page.total_rows,
            quality_note=_QUALITY_NOTE,
        )


class GetTrafficSummary:
    def __init__(self, port: TrafficCountsPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: TrafficVolumeSummaryInput) -> TrafficVolumeSummaryResult:
        page = self._port.summaries(
            SummaryQuery(
                station_id=request.station_id,
                year=request.year,
                limit=request.limit,
            )
        )
        return TrafficVolumeSummaryResult(
            fetched_at=self._clock.now().astimezone(UTC),
            source=_SOURCE,
            attribution=ATTRIBUTION,
            station_id=request.station_id,
            requested_year=request.year,
            summaries=list(page.records),
            count=len(page.records),
            upstream_total_rows=page.total_rows,
            quality_note=_QUALITY_NOTE,
        )


class GetHourlyTraffic:
    def __init__(self, port: TrafficCountsPort, clock: Clock) -> None:
        self._port = port
        self._clock = clock

    def execute(self, request: TrafficVolumeHourlyInput) -> TrafficVolumeHourlyResult:
        page = self._port.hourly(
            HourlyQuery(
                station_key=request.station_key,
                dataset=request.dataset,
                start_date=request.start_date,
                end_date=request.end_date,
                traffic_direction_seq=request.traffic_direction_seq,
                classification_seq=request.classification_seq,
                limit=request.limit,
            )
        )
        return TrafficVolumeHourlyResult(
            fetched_at=self._clock.now().astimezone(UTC),
            source=_SOURCE,
            attribution=ATTRIBUTION,
            station_key=request.station_key,
            dataset=request.dataset,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            rows=list(page.records),
            count=len(page.records),
            upstream_total_rows=page.total_rows,
            quality_note=_QUALITY_NOTE,
        )
