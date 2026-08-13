# Engineering notes

Research and validation date: 14 August 2026 (Australia/Sydney).

## Architecture

This is a standalone native Hermes plugin because TfNSW access needs executable
tools, a credential, bounded HTTP behavior, protobuf decoding, static-resource
indexing, and deterministic normalization. It supports both official reusable forms:

1. repository-root native plugin: `plugin.yaml` and root `__init__.py`;
2. pip package: `hermes_agent.plugins` entry point `sydney-transport` targeting
   `hermes_sydney_transport`.

The directory is an independent Git repository. The only import and extension path is
`hermes_sydney_transport`; the pre-0.4 `hermes_sydney_trains` compatibility package was
removed so the repository cannot acquire a second architecture by accident.

The plugin now registers 22 tools across two cohesive toolsets:

- `sydney_transport`: Trip Planner, GTFS-Realtime route disruptions, stop
  accessibility, route timetable, and mode-specific realtime tools;
- `nsw_traffic`: live road hazards and historical NSW Roads Traffic Volume Counts.

Inputs, outputs, static-resource models, and road-specific models are separated under
`models/`. Schemas are generated from Pydantic, handlers validate once at the
boundary, and normalized upstream results are validated again before serialization.
Handlers follow Hermes' `(args: dict, **kwargs) -> str` contract on every success and
error path.

## Hermes runtime and secret handling

The installed target is Hermes 0.20.0 on Python 3.13.5. Its directory and entry-point
loaders match the official contract. The runtime does not enforce manifest
`requires_env` as a complete availability gate, so the implementation intentionally
uses three layers:

- secret metadata in `plugin.yaml`;
- tool registration `requires_env` plus `check_fn`;
- client-side structured rejection when the secret is absent.

`TFNSW_API_KEY` is stored only in Hermes' private environment configuration and is
not hardcoded. Redirects are rejected by every transport so the `Authorization`
header cannot be forwarded to another origin.

## Transport design

Trip Planner mode classes are train `1`, metro `2`, light rail `4`, bus `5`, and
ferry `9`. Search, departures, journey planning, and Trip Planner alerts accept an
explicit unique mode list; the default remains train plus bus for backward
compatibility. Nearby-stop search is broader because the upstream coordinate endpoint
does not reliably expose one exact public-transport mode.

The JSON flow uses fixed routes and endpoint-specific macros:

```text
stop_finder(TfNSWSF)
departure_mon(departureMonitorMacro + TfNSWDM)
coord(PoisOnMapMacro)
trip(depArrMacro + TfNSWTR)
add_info(filterMOTType)
```

Realtime service tools are mode-specific for train, bus, metro, light rail, and
ferry. Route disruptions use GTFS-Realtime Alerts v2 and preserve feed provenance
such as `sydneytrains`, `nswtrains`, `regionbuses`, and `lightrail`.

Trip Planner `tripCode` is not a GTFS trip ID. The observed `RealtimeTripId` becomes
`service_id`, which joins Trip Updates, Vehicle Positions, and `trips.txt`. The
fallback resolver re-queries departures by `trip_code + stop_id (+ at)` and rejects
missing or ambiguous matches.

Train UpdateBundle cancellation evidence is retained with provenance and fails closed
when it appears without a matching service-specific TripUpdate. Train-specific TfNSW
extensions are not projected onto non-train modes. Static GTFS repositories and
caches remain separate by mode.

## Static accessibility and timetable design

Stop accessibility uses two independently versioned static TfNSW resources:

- location facilities;
- interchange lifts.

They are indexed into SQLite for exact stop lookup. Current accessibility warnings
reuse the semantic alerts port with `effect=accessibility_issue`, which keeps static
inventory and current warnings separate in the result contract.

Route timetable uses the Complete GTFS bundle rather than mode-specific schedule
archives. The adapter builds a bounded SQLite index and keeps Complete GTFS route,
trip, and stop identifiers distinct from realtime service IDs. The public contract
explicitly warns that published timetables are schedule data, not live evidence that
services are operating.

The Complete GTFS index is intentionally persistent but expensive to create. An
August 2026 production smoke downloaded a roughly 286 MB ZIP, indexed 5,003,732
`stop_times` into a roughly 515 MB SQLite database, and took about 28 seconds. A
refresh can temporarily hold the archive, old database, and replacement database at
the same time, so deployments should reserve at least 1.36 GB of working space and
pre-warm the route-timetable cache before latency-sensitive use.

## Live Traffic hazards

Live Traffic hazards are treated as strict GeoJSON, not free-form JSON. The adapter:

- queries only allowlisted `/open` hazard endpoints;
- validates FeatureCollection and Feature shapes with adapter-local Pydantic wire
  models;
- bounds feature counts, response bytes, advisory text and safe links;
- supports coordinate+radius or exact suburb filtering only;
- reports current road-network impacts, not travel-time routing.

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

Tables, selected columns, casts, ordering, and `LIMIT` are constants. Text literals
use one internal PostgreSQL literal encoder after length/shape validation. Hourly
ranges are limited to 31 days and 500 rows. Only JSON is requested; arbitrary
aggregate queries and export formats are not exposed.

## Verification policy

Unit tests use mocked HTTP, generated protobuf fixtures, strict GeoJSON wire models,
and synthetic static-resource samples. CI covers Python 3.12–3.13, declared minimum
dependencies, wheel packaging, and the Hermes entry point.

Deployment additionally requires credentialed live checks for:

- Trip Planner stop search, departures, planning, and Trip Planner alerts;
- GTFS-Realtime route disruptions across representative feeds;
- one service-status and one vehicle-position path per supported realtime mode;
- stop accessibility static lookups plus current warning integration;
- one Complete GTFS route timetable lookup;
- live hazard filtering;
- traffic station, yearly summary, and both hourly table shapes;
- real Hermes `PluginManager` discovery and registry dispatch.

The 0.6.0 deployment gate ran the real Hermes 0.20.0 directory loader, registered all
22 tools with no plugin error, and completed bounded Trip Planner, Alerts v2, Live
Traffic, accessibility, and Complete GTFS calls without logging credentials or
response bodies.

No background polling or persistent external database is created. Users should
implement opt-in monitoring through Hermes cron.
