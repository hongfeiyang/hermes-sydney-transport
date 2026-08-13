# Contributing

Read [`docs/architecture.md`](docs/architecture.md) before changing runtime code.
Its MUST/MUST NOT statements are project contracts, not suggestions.

## Where code belongs

- public Pydantic request/result: `hermes_sydney_transport/models/`
- consumer-owned Protocol or typed port DTO: `hermes_sydney_transport/ports/`
- use-case orchestration and policy: `hermes_sydney_transport/application/`
- TfNSW HTTP/protobuf/GTFS/Traffic Volume details: `hermes_sydney_transport/adapters/`
- Hermes schema/handler/envelope: `hermes_sydney_transport/presentation/`
- configuration, object construction, registration: `hermes_sydney_transport/bootstrap/`
- generated protobuf only: `hermes_sydney_transport/proto/`

Do not add a flat package module. Add a capability only through
`presentation/catalog.py`, bind it to one application use case in
`bootstrap/container.py`, and keep the existing generic handler and registrar. Do not
pass `Any`, `TypedDict`, mutable record dictionaries, protobuf messages, HTTP
responses, file handles, or vendor exceptions across a port. Ports use frozen,
slotted dataclasses; adapters parse strings into typed dates/times before returning.
Generic classes and functions use Python 3.12 PEP 695 type-parameter lists; do not
restore module-level `TypeVar` or inherit from `Generic`.

Realtime application modules use the single semantic repository and the
resolve/snapshot/join/timeline/policy pipeline. The architecture checker rejects
endpoint literals, manual timestamp parsing, oversized modules, and excessive branch
complexity in application code.

## Required checks

```bash
./scripts/verify.sh all
git diff --check
```

Architecture checks run both directly and inside the unit suite. Changing
`architecture.toml` or adding an exception requires an ADR in `docs/adr/`.
