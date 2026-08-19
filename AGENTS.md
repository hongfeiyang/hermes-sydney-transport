# Sydney Transport engineering contract

These instructions apply to the entire standalone repository.

## Required workflow

For every runtime change:

1. Read `docs/architecture.md` and `architecture.toml`.
2. Identify the one vertical use case being changed.
3. Add or update its Pydantic request/result contract first.
4. Change only the required port, application use case, adapter, presentation catalog,
   and bootstrap wiring.
5. Run `./scripts/verify.sh architecture` immediately.
6. Add deterministic tests with fake ports and a fixed clock.
7. Run `./scripts/verify.sh` before handoff.

If the architecture check fails, fix the design. Do not add an exception, increase a
budget, or weaken typing unless the user explicitly approves a new ADR.

## One extension path

Every model-visible capability is one `ToolSpec` in the presentation catalog backed
by exactly one application use case. Only bootstrap registration may call Hermes
`ctx.register_tool`. Schemas and handlers are generated from `ToolSpec`; do not create
parallel handwritten schemas, bespoke handlers, client factories, or direct Hermes
registrations.

Every realtime transport mode is one `ModeSpec` in `bootstrap/modes.py`. That row
owns its mode, cache namespace, policy, Alerts source names, complete endpoint bundle,
service-status capability, and vehicle-position capability. Repositories require these
bindings by injection. Do not add per-mode construction branches, defaults, or a second
mode registry.

Dependencies flow:

```text
presentation -> application -> ports <- adapters
                         ^                 ^
                         |                 |
                      contracts       generated

bootstrap is the only composition root and may wire every layer.
```

## Layer rules

- `models/`: canonical Pydantic requests/results/errors; deterministic, no I/O.
- `ports/`: consumer-owned Protocols and frozen, slotted dataclass records; no I/O,
  `Any`, `TypedDict`, mutable record dictionaries, or infrastructure parameters.
- `application/`: business policy and orchestration; injected ports/clock only.
- `adapters/tfnsw/`: provider code must use exactly this grammar:
  `catalogs -> platform -> codecs -> wire -> mappers -> stores -> repositories`.
  A module at the provider root, a feature-owned HTTP client/parser, or an additional
  role directory is forbidden.
- `presentation/`: `ToolSpec`, generated schemas, generic Hermes JSON handler.
- `bootstrap/`: settings, concrete construction, availability, registration.
- `proto/`: generated code only; never hand-edit.

Use Python 3.12 PEP 695 type-parameter lists for generics. Do not declare module-level
`TypeVar` objects or inherit from `Generic` outside generated code.

Raw mappings, HTTP responses, protobuf messages, file handles, vendor exceptions,
environment reads, and secrets must not cross an adapter boundary. Application and
port public APIs must be fully typed and must not use `Any`.

Only `platform/http.py` may perform network I/O or construct the API-key header. Only
declared codec modules may parse JSON, protobuf, CSV, ZIP, or XLSX/XML. `wire/` owns
Pydantic vendor schemas, `mappers/` contains small pure wire-to-domain functions,
`stores/` owns transactional persistence, and `repositories/` only composes those
pieces into semantic ports. Repositories and mappers may not catch exceptions or parse
bytes, line-oriented text, HTML, timestamps, or dictionary-shaped models.
Every public class under `wire/` must belong to the shared Pydantic model family;
`Any` and `TypedDict` are forbidden outside the dynamic protobuf codec boundary.
JSON-native wire modules are declaration-only: express alternate shapes through
bounded Pydantic unions and containers, never handwritten functions, lambdas, or
validator callbacks. Normalize already validated alternatives in pure mappers.
Expected partial-source failure crosses application boundaries as typed
`Availability[T]`, never as exception-driven normal control flow.

Application modules may not parse timestamps, contain physical feed identifiers,
exceed 250 lines, or exceed the configured complexity limit. Realtime changes must
pass through the semantic repository and the resolve/snapshot/join/timeline/policy
pipeline. Do not reintroduce transport or decoder dependencies into application code.

## Safety and data semantics

- Never hardcode, print, log, or commit `TFNSW_API_KEY`.
- Reject redirects on authenticated requests.
- Keep hosts, paths, tables, selected columns, query templates, response sizes,
  retries, and row limits allowlisted and bounded.
- Never expose raw SQL or a generic URL/endpoint argument.
- Preserve missing and uncertain data; do not invent on-time, empty, stationary,
  uncancelled, zero, or complete coverage.
- Keep `trip_code` distinct from GTFS `service_id`.
- Use an injected clock in application code and aware timestamps in canonical output.

## Required validation

```bash
./scripts/verify.sh architecture
./scripts/verify.sh types
./scripts/verify.sh test
./scripts/verify.sh
```

The final command runs architecture, formatting/lint, type checking, tests, and
packaging checks. Credentialed live tests are separate deployment gates.
