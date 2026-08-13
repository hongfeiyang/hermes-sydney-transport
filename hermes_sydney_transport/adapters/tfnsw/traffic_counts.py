"""TfNSW NSW Roads Traffic Volume Counts adapter."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    Request,
    build_opener,
)

from ...models.errors import DomainError
from ...models.metadata import USER_AGENT
from ...models.outputs import Coordinates
from ...models.traffic_outputs import (
    HourlyTrafficCount,
    TrafficStation,
    TrafficVolumeSummary,
)
from ...ports.traffic_counts import (
    HourlyQuery,
    Page,
    StationQuery,
    SummaryQuery,
)

_ENDPOINT = "https://api.transport.nsw.gov.au/v1/traffic_volume"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_STATION_COLUMNS = (
    "station_key, station_id, name, road_name, suburb, post_code, "
    "wgs84_latitude, wgs84_longitude, permanent_station, "
    "vehicle_classifier, quality_rating"
)
_SUMMARY_COLUMNS = (
    "station_key, station_id, traffic_direction_seq, traffic_direction_name, "
    "cardinal_direction_seq, cardinal_direction_name, classification_seq, "
    "classification_type, count_type, year, period, partial_year, latest_date, "
    "traffic_count, data_start_date, data_end_date, data_duration, "
    "data_availability, data_reliability, data_quality_indicator"
)
_HOURLY_COLUMNS = ", ".join(
    [
        "station_key",
        "traffic_direction_seq",
        "cardinal_direction_seq",
        "classification_seq",
        "date",
        "year",
        "month",
        "day_of_week",
        "public_holiday",
        "school_holiday",
        "daily_total",
        *(f"hour_{hour:02d}" for hour in range(24)),
    ]
)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class TrafficVolumeTransport:
    """Authenticated JSON transport for one allowlisted TfNSW endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
        opener: OpenerDirector | None = None,
    ) -> None:
        if not api_key.strip():
            raise DomainError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        if timeout_seconds <= 0 or max_attempts < 1:
            raise ValueError("timeout_seconds and max_attempts must be positive")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._random_source = random_source
        self._opener = opener or build_opener(_RejectRedirects())

    def query(self, sql: str) -> Mapping[str, Any]:
        url = f"{_ENDPOINT}?{urlencode({'format': 'json', 'q': sql})}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"apikey {self._api_key}",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        for attempt in range(self._max_attempts):
            try:
                with self._opener.open(
                    request, timeout=self._timeout_seconds
                ) as response:
                    raw = response.read(_MAX_RESPONSE_BYTES + 1)
                    if len(raw) > _MAX_RESPONSE_BYTES:
                        raise DomainError(
                            "response_too_large",
                            "TfNSW returned more traffic data than can be processed safely.",
                        )
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise DomainError(
                            "invalid_upstream_response",
                            "TfNSW returned invalid Traffic Volume JSON.",
                        ) from exc
                    if not isinstance(payload, Mapping):
                        raise DomainError(
                            "invalid_upstream_response",
                            "TfNSW returned an unexpected Traffic Volume response.",
                        )
                    _validate_payload_shape(payload)
                    return payload
            except HTTPError as exc:
                try:
                    retryable = exc.code in _RETRYABLE_STATUS
                    if retryable and attempt + 1 < self._max_attempts:
                        self._sleeper(
                            self._retry_delay(attempt, exc.headers.get("Retry-After"))
                        )
                        continue
                    raise DomainError(
                        "authentication_failed"
                        if exc.code in {401, 403}
                        else "upstream_http_error",
                        "TfNSW rejected the API credential."
                        if exc.code in {401, 403}
                        else f"TfNSW Traffic Volume request failed with HTTP {exc.code}.",
                        retryable=retryable,
                        http_status=exc.code,
                    ) from exc
                finally:
                    exc.close()
            except DomainError:
                raise
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self._max_attempts:
                    self._sleeper(self._retry_delay(attempt, None))
                    continue
                raise DomainError(
                    "upstream_unavailable",
                    "TfNSW Traffic Volume data could not be reached before the deadline.",
                    retryable=True,
                ) from exc
        raise DomainError(
            "upstream_unavailable",
            "TfNSW traffic request attempts were exhausted.",
            retryable=True,
        )

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 5.0)
            except ValueError:
                pass
        jitter = float(self._random_source()) * 0.1
        return float(min(0.25 * (2**attempt) + jitter, 2.0))


class TfnswTrafficCountsAdapter:
    """Maps fixed SQL responses into typed, vendor-neutral records."""

    def __init__(self, transport: TrafficVolumeTransport) -> None:
        self._transport = transport

    def search_stations(self, query: StationQuery) -> Page[TrafficStation]:
        clauses: list[str] = []
        if query.text:
            term = _sql_literal(f"%{query.text}%")
            clauses.append(
                f"(name ILIKE {term} OR road_name ILIKE {term} "
                f"OR suburb ILIKE {term} OR full_name ILIKE {term})"
            )
        if query.station_id:
            clauses.append(f"station_id = {_sql_literal(query.station_id)}")
        if query.permanent_only:
            clauses.append("permanent_station = 1")
        where = " WHERE " + " AND ".join(clauses)
        sql = (
            f"SELECT {_STATION_COLUMNS} FROM road_traffic_counts_station_reference"
            f"{where} ORDER BY station_id LIMIT {query.limit}"
        )
        payload = self._transport.query(sql)
        return Page(
            tuple(_station(row) for row in _rows(payload)),
            _optional_int(payload.get("total_rows")),
        )

    def summaries(self, query: SummaryQuery) -> Page[TrafficVolumeSummary]:
        clauses = [f"station_id = {_sql_literal(query.station_id)}"]
        if query.year is not None:
            clauses.append(f"year = {query.year}")
        sql = (
            f"SELECT {_SUMMARY_COLUMNS} FROM road_traffic_counts_yearly_summary "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY year DESC, traffic_direction_seq, classification_seq "
            f"LIMIT {query.limit}"
        )
        payload = self._transport.query(sql)
        return Page(
            tuple(_summary(row) for row in _rows(payload)),
            _optional_int(payload.get("total_rows")),
        )

    def hourly(self, query: HourlyQuery) -> Page[HourlyTrafficCount]:
        table = f"road_traffic_counts_hourly_{query.dataset}"
        exclusive_end = query.end_date.fromordinal(query.end_date.toordinal() + 1)
        clauses = [
            f"station_key::text = {_sql_literal(query.station_key)}",
            f"date >= {_sql_literal(query.start_date.isoformat())}",
            f"date < {_sql_literal(exclusive_end.isoformat())}",
        ]
        if query.traffic_direction_seq is not None:
            clauses.append(
                "traffic_direction_seq::text = "
                f"{_sql_literal(str(query.traffic_direction_seq))}"
            )
        if query.classification_seq is not None:
            clauses.append(
                "classification_seq::text = "
                f"{_sql_literal(str(query.classification_seq))}"
            )
        sql = (
            f"SELECT {_HOURLY_COLUMNS} FROM {table} WHERE {' AND '.join(clauses)} "
            "ORDER BY date, traffic_direction_seq, classification_seq "
            f"LIMIT {query.limit}"
        )
        payload = self._transport.query(sql)
        return Page(
            tuple(_hourly(row) for row in _rows(payload)),
            _optional_int(payload.get("total_rows")),
        )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_payload_shape(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload.get("rows"), list) or not isinstance(
        payload.get("fields"), Mapping
    ):
        raise DomainError(
            "invalid_upstream_response",
            "TfNSW returned an unexpected Traffic Volume response shape.",
        )


def _rows(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = payload["rows"]
    if not isinstance(value, list) or not all(
        isinstance(row, Mapping) for row in value
    ):
        raise DomainError(
            "invalid_upstream_response", "TfNSW returned an invalid traffic row."
        )
    return tuple(value)


def _station(row: Mapping[str, Any]) -> TrafficStation:
    latitude = _optional_float(row.get("wgs84_latitude"))
    longitude = _optional_float(row.get("wgs84_longitude"))
    coordinates = (
        Coordinates(latitude=latitude, longitude=longitude)
        if latitude is not None and longitude is not None
        else None
    )
    return TrafficStation(
        station_key=str(row.get("station_key") or ""),
        station_id=str(row.get("station_id") or ""),
        name=_optional_text(row.get("name")),
        road_name=_optional_text(row.get("road_name")),
        suburb=_optional_text(row.get("suburb")),
        post_code=_optional_text(row.get("post_code")),
        coordinates=coordinates,
        permanent_station=_optional_bool(row.get("permanent_station")),
        vehicle_classifier=_optional_bool(row.get("vehicle_classifier")),
        quality_rating=_optional_float(row.get("quality_rating")),
    )


def _summary(row: Mapping[str, Any]) -> TrafficVolumeSummary:
    year = _optional_int(row.get("year"))
    if year is None:
        raise DomainError(
            "invalid_upstream_response", "TfNSW omitted the traffic summary year."
        )
    return TrafficVolumeSummary(
        station_key=str(row.get("station_key") or ""),
        station_id=str(row.get("station_id") or ""),
        traffic_direction_seq=_optional_int(row.get("traffic_direction_seq")),
        traffic_direction_name=_optional_text(row.get("traffic_direction_name")),
        cardinal_direction_seq=_optional_int(row.get("cardinal_direction_seq")),
        cardinal_direction_name=_optional_text(row.get("cardinal_direction_name")),
        classification_seq=_optional_int(row.get("classification_seq")),
        classification_type=_optional_text(row.get("classification_type")),
        count_type=_optional_text(row.get("count_type")),
        year=year,
        period=_optional_text(row.get("period")),
        partial_year=_optional_bool(row.get("partial_year")),
        latest_date=_timestamp(row.get("latest_date")),
        traffic_count=_optional_float(row.get("traffic_count")),
        data_start_date=_timestamp(row.get("data_start_date")),
        data_end_date=_timestamp(row.get("data_end_date")),
        data_duration=_optional_float(row.get("data_duration")),
        data_availability=_optional_float(row.get("data_availability")),
        data_reliability=_optional_float(row.get("data_reliability")),
        data_quality_indicator=_optional_float(row.get("data_quality_indicator")),
    )


def _hourly(row: Mapping[str, Any]) -> HourlyTrafficCount:
    year = _optional_int(row.get("year"))
    month = _optional_int(row.get("month"))
    timestamp = _timestamp(row.get("date"))
    if year is None or month is None or timestamp is None:
        raise DomainError(
            "invalid_upstream_response", "TfNSW omitted a required hourly field."
        )
    return HourlyTrafficCount(
        station_key=str(row.get("station_key") or ""),
        traffic_direction_seq=_optional_int(row.get("traffic_direction_seq")),
        cardinal_direction_seq=_optional_int(row.get("cardinal_direction_seq")),
        classification_seq=_optional_int(row.get("classification_seq")),
        date=timestamp,
        year=year,
        month=month,
        day_of_week=_optional_int(row.get("day_of_week")),
        public_holiday=_optional_bool(row.get("public_holiday")),
        school_holiday=_optional_bool(row.get("school_holiday")),
        daily_total=_optional_float(row.get("daily_total")),
        hourly_counts=[
            _optional_float(row.get(f"hour_{hour:02d}")) for hour in range(24)
        ],
    )


def _timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DomainError(
            "invalid_upstream_response", "TfNSW returned an invalid traffic date."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_text(value: object) -> str | None:
    if value is None or value == "" or value == "NULL":
        return None
    return str(value)[:500]


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return int(float(value))
    except ValueError as exc:
        raise DomainError(
            "invalid_upstream_response", "TfNSW returned an invalid integer field."
        ) from exc
    raise DomainError(
        "invalid_upstream_response", "TfNSW returned an invalid integer field."
    )


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return float(value)
    except ValueError as exc:
        raise DomainError(
            "invalid_upstream_response", "TfNSW returned an invalid numeric field."
        ) from exc
    raise DomainError(
        "invalid_upstream_response", "TfNSW returned an invalid numeric field."
    )


def _optional_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if value == 1 or value in {"1", "true", "True"}:
        return True
    if value == 0 or value in {"0", "false", "False"}:
        return False
    raise DomainError(
        "invalid_upstream_response", "TfNSW returned an invalid boolean field."
    )
