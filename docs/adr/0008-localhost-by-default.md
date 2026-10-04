# 8. The server binds to localhost by default

Date: 2026-02-13

## Status

Accepted

## Context

A server holding a Telegraph access token and reachable over the network is a
publishing capability that anyone who finds it can use. The default bind address
decides whether exposing it is a deliberate act or an accident.

Convenient deployment defaults in this space — binding `0.0.0.0` — means the
first `docker run` or remote-host launch can expose a credential-bearing service
without anyone choosing to.

## Decision

Bind to `127.0.0.1` by default. `HOST` overrides it, so exposing the server is
always an explicit configuration change.

## Consequences

Reaching the server from another machine requires setting `HOST`, which is the
point: the operator states the intent rather than discovering it.

Container-based deployment must set `HOST=0.0.0.0` explicitly, and the Docker
documentation must say so, or the container will be unreachable.