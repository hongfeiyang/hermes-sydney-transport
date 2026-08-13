# Architecture contract

Status: **normative**
Owner: repository maintainers
Policy source: [`architecture.toml`](../architecture.toml)
Enforcement: [`tests/test_architecture.py`](../tests/test_architecture.py)

## 1. Intent

The plugin is a data pipeline implemented with ports and adapters. Every stage has one
responsibility, a typed boundary, and a one-way dependency. A feature is not complete
when it merely returns the right JSON; it must travel through the same pipeline and
respect the same contracts as every other feature.

```text
Hermes args
   │
   ▼
Presentation ── validates ──► Request model
                                  │
                                  ▼
Application use case ── calls ──► Port
                                  ▲
                                  │ implemented by
                              Adapter
                                  │
                   HTTP / protobuf / ZIP / upstream JSON

Adapter typed record ── application policy ──► Result model
                                                    │
                                                    ▼
Presentation ── validates + envelopes ────────► JSON string
```

Dependencies point inward. Application code knows what data it needs through ports;
it does not know TfNSW URLs, protobuf classes, SQL, Hermes, environment variables, or
filesystem details.

## 2. Layer contracts

### 2.1 Contracts — `models/`

Owns the canonical request and result language of the plugin.

Must:

- use Pydantic models with `extra="forbid"` and strict fields by default;
- express enums, ranges, cross-field invariants, timezone rules, and result counts;
- contain descriptions from which Hermes JSON Schema is generated;
- represent uncertainty explicitly with `None`, confidence, source, or quality fields;
- remain deterministic and side-effect free.

Must not read configuration, time, files, network data, or protobuf; import Hermes;
or know upstream field names that are not intentionally part of the public contract.

Boundary:

```text
untrusted dict -> RequestModel
canonical values -> ResultModel -> JSON-compatible canonical values
```

### 2.2 Ports — `ports/`

Owns the capabilities required by use cases, expressed as Python `Protocol`s and
typed DTOs. Ports are defined by consumers, not by TfNSW clients.

Examples are `TripPlannerPort`, `RealtimeRepository`, `StaticSchedulePort`,
`TrafficCountsPort`, and `Clock`.

Must:

- accept typed query objects and return frozen, slotted dataclass records or canonical models;
- expose semantic operations such as `find_departures`, never generic `get(url)` or
  `execute_sql`;
- make absence, pagination/bounds, freshness, and provenance explicit;
- use domain error types, not `HTTPError`, protobuf exceptions, or vendor messages.

Must not perform I/O or import adapters.

Boundary:

```text
typed semantic query -> typed record/result or declared domain error
```

`Any`, `TypedDict`, and mutable dictionary records are forbidden at port boundaries.
An adapter may use dynamic types while reading a vendor library, but only immutable
records containing typed `datetime`, `date`, `timedelta`, enum, scalar, and tuple
values may cross into application code.

### 2.3 Application — `application/`

Owns one use case per module or cohesive use-case group. It orchestrates ports and
implements business policy: identity resolution, train/bus differences, confidence,
progress, cancellation precedence, and bounds that span multiple sources.

Must:

- accept one validated request model and return one validated result model;
- receive ports, clock, and settings through constructor injection;
- be deterministic for a fixed request, port responses, and clock;
- name use cases after user intent, for example `GetBusServiceStatus`;
- map source records into canonical output without retaining untrusted fields.

Must not import `os`, Hermes, `urllib`, protobuf, ZIP/CSV parsers, concrete adapters,
or generated clients. It never serializes the Hermes envelope. It also may not parse
timestamps, name physical feed endpoints, use `Any`/`TypedDict`, exceed 250 lines per
module, or exceed the configured branch-complexity ceiling.

Boundary:

```text
RequestModel + injected ports -> ResultModel or DomainError
```

### 2.4 Adapters — `adapters/`

Owns all external-system details. Organize adapters by provider and transport, for
example `adapters/tfnsw/trip_planner_http.py` and
`adapters/tfnsw/gtfs_realtime_decoder.py`.

Must:

- implement a port explicitly;
- own fixed URLs, auth headers, macro/query construction, redirects, retries,
  deadlines, byte/row/archive limits, and conditional requests;
- validate untrusted wire data into typed source DTOs before returning;
- translate transport/decode failures into the shared domain error taxonomy;
- keep credentials in headers and redact secrets from errors/logs.

Only this layer may understand HTTP status codes, TfNSW JSON keys, protobuf extension
fields, GTFS CSV columns, or the Traffic Volume API's SQL-shaped wire protocol.

The realtime adapter exposes a semantic repository, not transport and decoder ports.
It owns the short-lived, thread-safe feed cache and indexes each decoded feed by exact
service ID. The static GTFS adapter owns its download transport and atomically builds
a bounded SQLite index; application code never passes one adapter into another.

The Traffic Volume adapter may generate SQL only from constant templates and encoded
validated literals. No port, request model, or tool may accept raw SQL.

Boundary:

```text
typed port query -> bounded I/O -> validated source DTO or DomainError
```

### 2.5 Presentation — `presentation/`

Owns Hermes-facing schemas and handlers.

Must:

- generate tool parameters from request models;
- implement `(args: dict, **kwargs) -> str`;
- validate args once, invoke exactly one application use case, validate its result,
  and return `{ok,data|error}` as a JSON string;
- convert `ValidationError` to `invalid_argument` and declared domain errors to the
  stable error envelope;
- treat unexpected exceptions as `internal_error` and log the traceback without
  secrets.

Must not make HTTP calls, decode protobuf, inspect environment variables, implement
transport policy, or contain TfNSW response keys.

Boundary:

```text
Hermes dict -> RequestModel -> use case -> ResultModel -> JSON string
```

### 2.6 Bootstrap — `bootstrap/` and package `register(ctx)`

Owns wiring and lifecycle only.

Must:

- read `TFNSW_API_KEY` and other deployment configuration;
- construct concrete adapters, repositories, clocks, and use cases;
- register tools/toolsets and availability checks;
- avoid business decisions and data normalization.

This is the only layer allowed to select concrete adapter implementations. Imports
may point to all layers, but no other layer may import bootstrap. The package root is
only a two-symbol import surface (`register`, `__version__`).

The composition root is reused across handler calls for an unchanged validated
settings object. This makes transport, realtime-feed, and static-index caches live for
the gateway lifetime while still replacing the container after a configuration change.

## 2.7 The single extension path

A capability has exactly one legal route into the runtime:

1. add its request/result contract under `models/`;
2. add or reuse one semantic port;
3. implement one application use case;
4. add one `Capability` enum member;
5. add one `ToolSpec` row in `presentation/catalog.py`;
6. bind that capability to its use case in `bootstrap/container.py`.

The generic handler is generated from `ToolSpec`, and
`bootstrap/registration.py` iterates the same catalog. There is no second schema
registry, handler list, or registration table to update. Handwritten Hermes handlers
and additional `ctx.register_tool` call sites are architecture violations.

### 2.8 Generated — `proto/`

Contains generated source only. Generated files are never edited manually and are
used only by protobuf adapters/decoders.

## 3. Stage-level data rules

Every feature follows these stages in order:

1. **Validate input** — shape, enums, bounds, cross-field rules.
2. **Build semantic query** — no URL, header, raw SQL, or vendor parameter escapes.
3. **Acquire** — bounded I/O through one or more ports.
4. **Decode** — bytes/JSON/CSV become typed source DTOs; unknown shape fails closed.
5. **Normalize** — deterministic mapping into canonical IDs, modes, timestamps,
   units, source, confidence, and quality.
6. **Validate output** — the result model is the executable contract.
7. **Present** — stable Hermes JSON envelope.

An object may cross a layer only if its type is owned by `models/`, `ports/`, or the
shared error module. Raw mappings, response objects, protobuf messages, open files,
and exceptions from vendor libraries remain inside adapters.

For realtime capabilities the required internal stages are `resolve -> snapshot ->
static join -> timeline -> policy -> result`. Train and bus both traverse these stages;
their differences are values in one `ModePolicy`, not parallel implementations.

## 4. Error contract

The stable public codes are owned by the domain/application contract:

| Code | Owner and meaning | Retryable |
|---|---|---|
| `invalid_argument` | Presentation rejected model input | No |
| `missing_configuration` | Bootstrap/adapter lacks required secret | No |
| `authentication_failed` | Adapter received 401/403 | No |
| `upstream_unavailable` | Timeout/network/retryable service failure | Yes |
| `upstream_http_error` | Non-auth upstream HTTP failure | Depends on status |
| `response_too_large` | Adapter bound was exceeded | No |
| `invalid_upstream_response` | Decode/wire/output contract failed | No |
| `service_not_found` | Use case cannot bind requested service | Usually no |
| `ambiguous_service` | More than one valid service identity | No |
| `unverified_cancellation` | Evidence cannot be safely attributed | Yes |
| `internal_error` | Unexpected defect caught at presentation | No |

Adapters attach safe metadata such as HTTP status but never response bodies or
credentials. Use cases may translate low-level domain errors only when they add a
more precise semantic meaning; they do not swallow warnings or fabricate success.

## 5. Time, identity, and provenance

- Current time comes from an injected `Clock`, never a direct call in application
  logic.
- Public time inputs are ISO 8601. Sydney-local naive values must pass DST gap/fold
  validation. Canonical timestamps are timezone aware.
- `trip_code` and GTFS `service_id` are distinct types and must never be joined by
  string similarity.
- Every result declares source and attribution; realtime results also declare feed
  and observation age, static-join status, inference, and confidence.
- Missing data remains missing. It is never converted to on-time, empty, stationary,
  not-cancelled, or zero unless the upstream contract explicitly says so.

## 6. Dependency matrix

| From \ To | Contracts | Ports | Application | Adapters | Presentation | Bootstrap | Generated |
|---|---:|---:|---:|---:|---:|---:|---:|
| Contracts | ✓ | — | — | — | — | — | — |
| Ports | ✓ | ✓ | — | — | — | — | — |
| Application | ✓ | ✓ | ✓ | — | — | — | — |
| Adapters | ✓ | ✓ | — | ✓ | — | — | ✓ |
| Presentation | ✓ | — | ✓ | — | ✓ | — | — |
| Bootstrap | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Generated | — | — | — | — | — | — | ✓ |

A source file may import left-to-right only where the table has ✓. Passing a concrete
adapter into application code at runtime is allowed; importing its class there is not.

## 7. Zero-exception enforcement

The 0.4 mixed root modules have been removed. Only package `__init__.py` may live at
the runtime package root. `architecture.toml` has no legacy module list or line-count
budget: architecture conformance is binary.

The checker enforces layer ownership, dependency direction, forbidden capabilities,
the sole registration call site, the root-module set, forbidden legacy package paths,
PEP 695 generic syntax, and the raw-SQL adapter boundary. Any exception requires an
ADR and an explicit policy change; “it was faster” is not sufficient justification.

## 8. Definition of done for a feature

A feature PR must include:

- request and result models;
- a semantic port or an intentional reuse of an existing port;
- application use-case tests with fake ports and a fixed clock;
- adapter contract tests using sanitized fixtures/mocked transport;
- presentation schema/envelope tests;
- architecture tests, full unit tests, lint, and package smoke;
- documentation of uncertainty, provenance, and source-specific limitations.

Live credential tests verify deployment but never replace deterministic tests.
