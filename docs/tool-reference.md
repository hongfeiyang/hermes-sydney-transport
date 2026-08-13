# Tool reference

This page describes the model-visible contract of Hermes Sydney Transport 0.5.0.
The executable JSON Schemas are generated from strict Pydantic models; this document
is a human-readable guide, not a second source of truth.

All handlers return a JSON string with one stable envelope:

```json
{"ok": true, "data": {}}
```

or:

```json
{"ok": false, "error": {"code": "...", "message": "..."}}
```

Unknown input fields, coercible booleans/numbers, malformed identifiers and unbounded
queries are rejected before any upstream request.

## Recommended transport workflow

1. Call `sydney_transport_search_stops` for a user-supplied place name.
2. Call `sydney_transport_departures` with the selected `stop_id`.
3. Prefer the departure's exact `service_id` for service status or vehicle position.
4. If only `trip_code` is available, pass it with the departure `stop_id`; add `at`
   when resolving a past or otherwise ambiguous service.

`service_id` is a GTFS/GTFS-Realtime trip identity. `trip_code` is a separate Trip
Planner value and is never treated as the same identifier.

## Shared transport fields

- `modes`: one or both of `train`, `bus`; defaults to both where supported.
- `at`: ISO 8601 date/time, at most one day in the past or 14 days ahead. A value
  without an offset uses `Australia/Sydney`; ambiguous DST times require an offset.
- `stop_id`: a stable identifier returned by stop search.
- `service_id`: preferred exact realtime identity returned by departures.
- `limit`: endpoint-specific hard maximum; callers cannot request unbounded output.

## Sydney transport tools

### `sydney_transport_search_stops`

Searches train stations and bus stops.

- Input: `query`, optional `modes`, optional `limit` (1–10).
- Output: ranked stops with stable ID, display names, known modes, match quality and
  optional coordinates.
- Use before departures, trip planning or stop-scoped alerts.

### `sydney_transport_nearby_stops`

Finds public-transport stops around WGS84 coordinates.

- Input: `latitude`, `longitude`, optional `radius_metres` (100–5000), optional
  `limit` (1–20).
- Output: distance, coordinates, location types and known platforms.
- Caveat: the upstream endpoint does not reliably identify mode, so results may also
  include Metro, light rail or ferry stops.

### `sydney_transport_departures`

Returns an upcoming train/bus departure board.

- Input: `stop_id`, optional `modes`, `at`, and `limit` (1–20).
- Output: planned/estimated time, derived status and delay, realtime availability,
  cancellation evidence, platform, route, destination, operator, `trip_code`, exact
  `service_id` when supplied, and linked alert IDs.
- Caveat: a missing estimate remains unknown; it is not labelled on time.

### `sydney_transport_plan_trip`

Plans train/bus journeys between two stop IDs.

- Input: `origin_stop_id`, `destination_stop_id`, optional `modes`, `at`,
  `time_mode=depart|arrive`, `wheelchair`, and `limit` (1–5).
- Output: bounded journey/leg/stop sequences, planned and estimated times, routes,
  platforms, transfers, accessibility, cancellation state, alerts and system
  messages.
- The origin and destination must differ.

### `sydney_transport_alerts`

Returns current network or stop-scoped alerts.

- Input: optional `stop_id`, optional `modes`, optional `limit` (1–20).
- Output: priority, title, bounded plaintext, affected lines/stops, validity windows,
  provider and safe URL metadata.
- Alert content is explicitly marked as untrusted remote content.

### `sydney_transport_train_service_status`

### `sydney_transport_bus_service_status`

Returns the stop-by-stop realtime state for exactly one service.

- Input: exactly one of `service_id` or `trip_code`; `trip_code` also requires
  `stop_id`; optional `at`.
- Output: resolved identity, route/service description, cancellation state, next stop,
  stop predictions, skipped stops, platform/stop changes, current progress, warnings,
  feed age and confidence evidence.
- Train and bus feeds use separate mode policies. Bus results do not consume
  train-only carriage or UpdateBundle semantics.

### `sydney_transport_train_vehicle_position`

### `sydney_transport_bus_vehicle_position`

Returns the most recent reported physical position for exactly one service.

- Input: the same exact/fallback identity fields as service status.
- Output: reported coordinates, bearing/speed when available, current/next stop
  context, vehicle identity, optional occupancy, observation age, static-join status,
  warnings and confidence.
- An absent or stale vehicle entity is reported explicitly. It is never interpreted
  as stationary, complete or empty.

## NSW traffic tools

These tools query historical road traffic-volume counts. They do not provide live
road conditions, incidents, journey times or congestion predictions.

### `nsw_traffic_count_stations`

Finds official count sites and the `station_key` required by hourly data.

- Input: `query` or exact `station_id`, optional `permanent_only`, optional `limit`
  (1–50).
- Output: station key/ID, road/site/suburb, coordinates, station type and quality.

### `nsw_traffic_volume_summary`

Returns published yearly aggregates for a station.

- Input: `station_id`, optional `year` (2006–2100), optional `limit` (1–100).
- Output: direction/classification, count type, year/period, partial-year state,
  traffic count, observation range, availability, reliability and quality fields.

### `nsw_traffic_volume_hourly`

Returns bounded daily rows containing 24 hourly count values.

- Input: `station_key`, `dataset=permanent|sample`, `start_date`, `end_date`, optional
  direction/classification sequence and `limit` (1–500).
- Dates are strict `YYYY-MM-DD`, the range is inclusive and cannot exceed 31 days.
- Output: per-day totals, 24 hourly values, direction/classification, holiday flags
  and data-quality notes.

The upstream API accepts a PostgreSQL-shaped query string, but this plugin does not.
It constructs fixed column, table, predicate, ordering and limit templates internally.

## Provenance and uncertainty

Every top-level result includes `fetched_at`, `source` and `attribution`. Realtime
results additionally include feed/observation age, static join success, whether a
prediction or inference was used, warnings and a confidence level. Preserve these
fields when summarizing results for a user.
