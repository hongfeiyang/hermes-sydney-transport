# Engineering notes

Research and validation date: 12 August 2026 (Australia/Sydney).

## Architecture

This is a standalone native Hermes plugin because TfNSW access needs executable
tools, a credential, bounded HTTP behavior, protobuf decoding, and deterministic
normalization. It supports both official reusable forms:

1. repository-root native plugin: `plugin.yaml` and root `__init__.py`;
2. pip package: `hermes_agent.plugins` entry point `sydney-transport` targeting
   `hermes_sydney_transport`.

The directory is an independent Git repository. The only import and extension path is
`hermes_sydney_transport`; the pre-0.4 `hermes_sydney_trains` compatibility package was
removed so the repository cannot acquire a second architecture by accident.

The plugin registers two cohesive toolsets:

- `sydney_transport`: Trip Planner, train/bus alerts, and mode-specific GTFS-R tools;
- `nsw_traffic`: historical NSW Roads Traffic Volume Counts.

Inputs, outputs, and road-specific models are separated under `models/`. Schemas are
generated from Pydantic, handlers validate once at the boundary, and normalized
upstream results are validated again before serialization. Handlers follow Hermes'
`(args: dict, **kwargs) -> str` contract on every success and error path.

## Hermes runtime and secret handling

The installed target is Hermes 0.20.0 on Python 3.13.5. Its directory and entry-point
loaders match the official contract. The runtime does not enforce manifest
`requires_env` as a complete availability gate, so the implementation intentionally
uses three layers:

- secret metadata in `plugin.yaml`;
- tool registration `requires_env` plus `check_fn`;
- client-side structured rejection when the secret is absent.

`TFNSW_API_KEY` is stored only in Hermes' private `/opt/data/.env`, configured via
`hermes config set`. It is not hardcoded. Redirects are rejected by every transport so
the Authorization header cannot be forwarded to another origin.

## Transit design

Trip Planner modes are train `1` and bus `5`. Search, departures, trip planning, and
alerts accept an explicit unique mode list, defaulting to both. The plugin also filters
normalized responses by exact product class and fails closed when an event has no
usable mode.

The JSON flow uses fixed routes and endpoint-specific macros:

```text
stop_finder(TfNSWSF)
departure_mon(departureMonitorMacro + TfNSWDM)
coord(PoisOnMapMacro)
trip(depArrMacro + TfNSWTR)
add_info(filterMOTType)
```

Realtime is mode-specific:

| Feed | Train | Bus |
|---|---|---|
| Static GTFS | `/v1/gtfs/schedule/sydneytrains` | `/v1/gtfs/schedule/buses` |
| Trip Updates | `/v2/gtfs/realtime/sydneytrains` | `/v1/gtfs/realtime/buses` |
| Vehicle Positions | `/v2/gtfs/vehiclepos/sydneytrains` | `/v1/gtfs/vehiclepos/buses` |

Trip Planner `tripCode` is not a GTFS trip ID. The observed `RealtimeTripId` becomes
`service_id`, which joins Trip Updates, Vehicle Positions, and `trips.txt`. The
fallback resolver re-queries departures by `trip_code + stop_id (+ at)` and rejects
missing or ambiguous matches.

Train UpdateBundle cancellation evidence is retained with provenance and fails closed
when it appears without a matching service-specific TripUpdate. Bus cancellation uses
only its service-specific TripUpdate. Bus trip-level delay is not trusted; bus
predictions require stop-level evidence. Train carriage extensions are ignored for
bus occupancy, which is whole-vehicle only.

Static GTFS repositories and caches are separate per mode. Route enrichment preserves
`agency_id` and raw extended `route_type`, important because TfNSW bus routes can use
extended 700-series route types.

## NSW Roads Traffic Volume Counts

The supplied official Swagger defines one endpoint:

```text
GET /v1/traffic_volume?format=json&q=<PostgreSQL query>
```

Exposing `q` would be an unsafe and hard-to-maintain agent interface. The plugin
therefore never accepts SQL. Three Pydantic requests map to fixed templates over the
four documented tables:

- `road_traffic_counts_station_reference`;
- `road_traffic_counts_yearly_summary`;
- `road_traffic_counts_hourly_permanent`;
- `road_traffic_counts_hourly_sample`.

Tables, selected columns, casts, ordering, and LIMIT are constants. Text literals use
one internal PostgreSQL literal encoder after length/shape validation. Hourly ranges
are limited to 31 days and 500 rows. Only JSON is requested; filename/export formats
and arbitrary aggregate queries are not exposed.

The permanent and sample tables have different runtime types for several fields, so
the normalizer deliberately handles numeric and textual representations before strict
Pydantic output validation. All dates become aware ISO timestamps. A malformed shape,
number, boolean, or timestamp is an upstream contract error rather than silently
passing through.

The official dataset guide says the series starts in 2006 and is aggregated monthly.
It documents minimum observation coverage and outlier checks, while warning about
roadside-device, weather, power, double-counting, and intermittent heavy-vehicle
classification limitations. Outputs always include a concise quality note and retain
the upstream availability, reliability, quality, and partial-year fields.

## Legacy source audit

The legacy application used Trip Planner `stop_finder -> departure_mon -> add_info`,
refreshed every 60 seconds. Its GTFS alert and vehicle routes were placeholders and
were not reused. No credential or application source was copied into this plugin.

Only official Trip Planner/protobuf contracts, macro definitions and NSW Roads
dataset specifications informed the implementation. Production transports, models,
joins, confidence rules and normalization are original.

## Verification policy

Unit tests use mocked HTTP and generated protobuf fixtures. CI covers Python
3.12–3.13, the declared minimum dependencies, wheel packaging, and the Hermes entry
point. Deployment additionally requires credentialed live checks for:

- bus stop search, departures and alerts;
- one bus service joined across Trip Updates and static GTFS;
- one bus Vehicle Position and occupancy result;
- traffic station, yearly summary, and both hourly table shapes;
- real Hermes PluginManager discovery and registry dispatch.

No background polling or persistent database is created. Users should implement
opt-in monitoring through Hermes cron.
