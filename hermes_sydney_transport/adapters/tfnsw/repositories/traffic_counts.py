"""Semantic repository for NSW Traffic Volume Counts."""

from __future__ import annotations

from ....models.errors import DomainError
from ....models.traffic_outputs import (
    HourlyTrafficCount,
    TrafficStation,
    TrafficVolumeSummary,
)
from ....ports.traffic_counts import HourlyQuery, Page, StationQuery, SummaryQuery
from ..catalogs.endpoints import TRAFFIC_VOLUME_ENDPOINT
from ..catalogs.traffic_counts import (
    HOURLY_COLUMNS,
    HOURLY_TABLES,
    STATION_COLUMNS,
    SUMMARY_COLUMNS,
    projection,
)
from ..codecs import JsonModelCodec
from ..mappers.traffic_counts import map_hourly, map_station, map_summary
from ..platform import HttpTransport
from ..wire.traffic_counts import (
    HourlyTrafficWire,
    TrafficResponseWire,
    TrafficStationWire,
    TrafficSummaryWire,
)


class TfnswTrafficCountsRepository:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport
        self._stations = JsonModelCodec(
            TrafficResponseWire[TrafficStationWire], source="Traffic station search"
        )
        self._summaries = JsonModelCodec(
            TrafficResponseWire[TrafficSummaryWire], source="Traffic yearly summary"
        )
        self._hourly = JsonModelCodec(
            TrafficResponseWire[HourlyTrafficWire], source="Traffic hourly counts"
        )

    def search_stations(self, query: StationQuery) -> Page[TrafficStation]:
        clauses = tuple(
            clause
            for clause in (
                _station_text_clause(query.text),
                f"station_id = {_sql_literal(query.station_id)}"
                if query.station_id
                else None,
                "permanent_station = 1" if query.permanent_only else None,
            )
            if clause is not None
        )
        sql = (
            f"SELECT {projection(STATION_COLUMNS)} "
            "FROM road_traffic_counts_station_reference"
            f"{_where(clauses)} ORDER BY station_id LIMIT {query.limit}"
        )
        payload = self._fetch(sql)
        response = self._stations(payload)
        return Page(
            tuple(map_station(row) for row in response.rows), response.total_rows
        )

    def summaries(self, query: SummaryQuery) -> Page[TrafficVolumeSummary]:
        clauses = [f"station_id = {_sql_literal(query.station_id)}"]
        if query.year is not None:
            clauses.append(f"year = {query.year}")
        sql = (
            f"SELECT {projection(SUMMARY_COLUMNS)} "
            "FROM road_traffic_counts_yearly_summary "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY year DESC, traffic_direction_seq, classification_seq "
            f"LIMIT {query.limit}"
        )
        response = self._summaries(self._fetch(sql))
        return Page(
            tuple(map_summary(row) for row in response.rows), response.total_rows
        )

    def hourly(self, query: HourlyQuery) -> Page[HourlyTrafficCount]:
        exclusive_end = query.end_date.fromordinal(query.end_date.toordinal() + 1)
        clauses = [
            f"station_key::text = {_sql_literal(query.station_key)}",
            f"date >= {_sql_literal(query.start_date.isoformat())}",
            f"date < {_sql_literal(exclusive_end.isoformat())}",
            *_optional_number_clause(
                "traffic_direction_seq", query.traffic_direction_seq
            ),
            *_optional_number_clause("classification_seq", query.classification_seq),
        ]
        sql = (
            f"SELECT {projection(HOURLY_COLUMNS)} FROM {HOURLY_TABLES[query.dataset]} "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY date, traffic_direction_seq, classification_seq "
            f"LIMIT {query.limit}"
        )
        response = self._hourly(self._fetch(sql))
        return Page(
            tuple(map_hourly(row) for row in response.rows), response.total_rows
        )

    def _fetch(self, sql: str) -> bytes:
        payload = self._transport.fetch(
            TRAFFIC_VOLUME_ENDPOINT,
            params={"format": "json", "q": sql},
        )
        if payload.body is None:
            raise DomainError(
                "invalid_upstream_response",
                "TfNSW Traffic Volume response did not contain a body.",
            )
        return payload.body


def _station_text_clause(text: str | None) -> str | None:
    if text is None:
        return None
    term = _sql_literal(f"%{text}%")
    return (
        f"(name ILIKE {term} OR road_name ILIKE {term} "
        f"OR suburb ILIKE {term} OR full_name ILIKE {term})"
    )


def _where(clauses: tuple[str, ...]) -> str:
    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def _optional_number_clause(column: str, value: int | None) -> tuple[str, ...]:
    return (
        (f"{column}::text = {_sql_literal(str(value))}",) if value is not None else ()
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
