# Tool reference

This page describes the model-visible contract of Hermes Sydney Transport 0.6.0.
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

Unknown input fields, coercible booleans/numbers, malformed identifiers and
unbounded queries are rejected before any upstream request.

## Recommended transport workflow

1. Call `sydney_transport_search_stops` for a user-supplied place name.
2. Call `sydney_transport_departures` with the selected `stop_id`.
3. Prefer the departure's exact `service_id` for service status or vehicle position.
4. If only `trip_code` is available, pass it with the departure `stop_id`; add `at`
   when resolving a past or otherwise ambiguous service.
5. Use `sydney_transport_route_disruptions` for route/network disruption context.
6. Use `sydney_transport_stop_accessibility` for exact-stop facilities or current
   accessibility warnings.
7. Use `sydney_transport_route_timetable` only with exact Complete GTFS route and
   stop IDs; do not reuse those IDs as realtime `service_id` values.

`service_id` is a GTFS/GTFS-Realtime trip identity. `trip_code` is a separate Trip
Planner value and is never treated as the same identifier.

## Shared transport fields

- `modes`: any unique selection of `train`, `bus`, `metro`, `light_rail`, and
  `ferry`; defaults to train and bus where supported.
- `at`: ISO 8601 date/time, at most one day in the past or 14 days ahead. A value
  without an offset uses `Australia/Sydney`; ambiguous DST times require an offset.
- `stop_id`: a stable identifier returned by stop search.
- `service_id`: preferred exact realtime identity returned by departures.
- `limit`: endpoint-specific hard maximum; callers cannot request unbounded output.

## Mode coverage

| Tool family | Supported modes |
|---|---|
| Search / departures / trip plan / Trip Planner alerts | `train`, `bus`, `metro`, `light_rail`, `ferry` |
| Route disruptions | `train`, `bus`, `metro`, `light_rail`, `ferry` |
| Service status / vehicle position | mode-specific train, bus, metro, light rail, ferry |
| Stop accessibility / route timetable | not mode-selected; exact stop/route lookups |

## Sydney transport tools

### `sydney_transport_search_stops`

Searches stops for any supported public-transport mode.

- Input: `query`, optional `modes`, optional `limit` (1–10).
- Output: ranked stops with stable ID, display names, known modes, match quality and
  optional coordinates.
- Use before departures, trip planning or stop-scoped tools.

### `sydney_transport_nearby_stops`

Finds public-transport stops around WGS84 coordinates.

- Input: `latitude`, `longitude`, optional `radius_metres` (100–5000), optional
  `limit` (1–20).
- Output: distance, coordinates, location types and known platforms.
- Caveat: the upstream endpoint does not reliably identify mode, so results may also
  include Metro, light rail or ferry stops.

### `sydney_transport_departures`

Returns an upcoming departure board for the selected public-transport modes.

- Input: `stop_id`, optional `modes`, optional `at`, optional `limit` (1–20).
- Output: planned/estimated time, derived status and delay, realtime availability,
  cancellation evidence, platform, route, destination, operator, `trip_code`, exact
  `service_id` when supplied, and linked alert IDs.
- Caveat: a missing estimate remains unknown; it is not labelled on time.

### `sydney_transport_plan_trip`

Plans journeys across the selected public-transport modes between two stop IDs.

- Input: `origin_stop_id`, `destination_stop_id`, optional `modes`, optional `at`,
  `time_mode=depart|arrive`, `wheelchair`, and `limit` (1–5).
- Output: bounded journey/leg/stop sequences, planned and estimated times, routes,
  platforms, cancellation state, alerts and system messages.
- The origin and destination must differ.

### `sydney_transport_alerts`

Returns current Trip Planner alerts for the selected public-transport modes.

- Input: optional `stop_id`, optional `modes`, optional `limit` (1–20).
- Output: priority, title, bounded plaintext, affected lines/stops, validity windows,
  provider and safe URL metadata.
- Alert content is explicitly marked as untrusted remote content.

### `sydney_transport_route_disruptions`

Returns GTFS-Realtime Alerts v2 route disruptions across five public-transport modes.

- Input: optional `modes`, `stop_id`, `route_id`, `trip_id`, `causes`, `effects`,
  optional `at`, and `limit` (1–20).
- Output: `mode`, exact `source_feed`, title, description, cause, effect, severity,
  active periods, selectors, route IDs, stop IDs and trip IDs.
- Preserves exact feed provenance such as `sydneytrains`, `nswtrains`, `buses`,
  `regionbuses`, `metro`, `lightrail`, and `ferries`.
- This tool is for route/service disruptions, not single-vehicle tracking.

### `sydney_transport_stop_accessibility`

Returns exact-stop accessibility inventory, optionally with current warnings.

- Input: exact `stop_id`, optional `include_current_warnings`, optional
  `warning_limit` (1–10).
- Output: static facility classification, facilities, staffed hours, coordinates,
  lift inventory, and optional current accessibility warnings.
- Static lift presence never proves current lift operation.
- Current warnings come from GTFS-Realtime Alerts v2 `effect=accessibility_issue`.

### `sydney_transport_route_timetable`

Returns a bounded published timetable for one exact Complete GTFS route.

- Input: exact `route_id`, optional `service_date`, optional `direction_id`, optional
  exact Complete GTFS `stop_id`, optional `limit`.
- Output: route metadata, requested service date, ordered trips, stop times and
  wheelchair-accessibility values.
- Route/trip/stop IDs are from the Complete GTFS namespace and must not be reused as
  realtime identifiers.
- This is published schedule data, not evidence that a service is currently running.

### `sydney_transport_train_service_status`
### `sydney_transport_bus_service_status`
### `sydney_transport_metro_service_status`
### `sydney_transport_light_rail_service_status`
### `sydney_transport_ferry_service_status`

Returns the stop-by-stop realtime state for exactly one service.

- Input: exactly one of `service_id` or `trip_code`; `trip_code` also requires
  `stop_id`; optional `at`.
- Output: resolved identity, route/service description, cancellation state, next stop,
  stop predictions, skipped stops, platform/stop changes, current progress, feed age,
  warnings and confidence evidence.
- Each mode uses its own feed and policy. Missing or partial realtime evidence remains
  explicit.

### `sydney_transport_train_vehicle_position`
### `sydney_transport_bus_vehicle_position`
### `sydney_transport_metro_vehicle_position`
### `sydney_transport_light_rail_vehicle_position`
### `sydney_transport_ferry_vehicle_position`

Returns the most recent reported physical position for exactly one service.

- Input: the same exact/fallback identity fields as service status.
- Output: reported coordinates, bearing/speed when available, current/next stop
  context, vehicle identity, optional occupancy, observation age, static-join status,
  warnings and confidence.
- An absent or stale vehicle entity is reported explicitly. It is never interpreted
  as stationary, complete or empty.

## NSW traffic tools

These tools cover live road hazards and historical road traffic-volume counts.

### `nsw_live_traffic_hazards`

Returns current Live Traffic hazards near a coordinate or in one suburb.

- Input: either (`latitude`, `longitude`, optional `radius_metres`) or exact
  `suburb`, plus `hazard_types` and `limit`.
- Output: hazard type, incident kind, display name, categories, bounded advice,
  network impact, timing, coordinates, optional distance, affected roads and safe
  web links.
- Uses current `/open` hazard feeds only. This is live road-hazard data, not
  turn-by-turn routing or travel-time prediction.

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

The upstream Roads API accepts a PostgreSQL-shaped query string, but this plugin does
not. It constructs fixed column, table, predicate, ordering and limit templates
internally.

## Provenance and uncertainty

Every top-level result includes `fetched_at`, `source` and `attribution`. Realtime
results additionally include feed/observation age, static join success, whether a
prediction or inference was used, warnings and a confidence level. Preserve these
fields when summarizing results for a user.
