# 7. Testing is layered, and never touches the real Telegraph API

Date: 2026-02-13

## Status

Accepted

## Context

The project has three areas with different failure modes: Markdown-to-node
conversion (pure logic, many edge cases), Telegraph HTTP interaction (I/O,
dictated by a third party), and MCP tool wiring (integration, auth).

A test suite that calls the real Telegraph API would depend on a third party's
availability, mutate real accounts, and be slow.

## Decision

Four layers, each covering what the others cannot:

1. **Converter unit tests** — the bulk of the suite. One test per Markdown
   construct and, per ADR 3, one per degradation path. Pure functions in, node
   trees out, no network.
2. **HTTP layer tests** with `respx` — assert the outgoing request body matches
   the Telegraph contract, with responses stubbed. No network.
3. **Tool tests in-process** — FastMCP's `Client` accepts the server object
   directly, so tools are exercised without a listener: publishing, updating,
   reading, the size and title failures, the advertised tool surface, and the
   rule that no message echoes a credential.
4. **Admission tests over ASGI** — the bearer credential is enforced by HTTP
   middleware, which the in-process client bypasses entirely, so a test written
   against it would pass whether or not admission worked. These drive the real
   Starlette app from `http_app()` through `TestClient`: the HTTP stack without a
   socket, which is where admission actually happens. `TestClient` rather than a
   bare `httpx.ASGITransport`, because the streamable-HTTP session manager is
   created inside the app's lifespan — skip the lifespan and every request fails
   with "Task group is not initialized", which looks like an auth failure and is
   not one.

## Consequences

Tests run in milliseconds and are deterministic, so they can be run on every
save without friction — which matters, because the converter's edge cases only
stay correct if they are cheap to re-verify.

Testing admission through the in-process client is a trap worth naming: it
produces a green suite that proves nothing about authentication. The ASGI layer
exists so the guarantee is tested where it is implemented.

Telegraph-side changes will not be caught by CI. That risk is accepted: it is
detectable the first time a publish is attempted, and the alternative is a suite
that fails for reasons outside the project's control.