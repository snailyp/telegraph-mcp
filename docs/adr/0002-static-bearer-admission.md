# 2. MCP admission uses a single static bearer credential

Date: 2026-02-13

## Status

Accepted

## Context

The server may be reachable over a network, so callers must be authenticated.
The candidates were a single static bearer credential, a table of named
credentials for per-client revocation, or full OAuth.

This is a self-hosted tool with a small, known set of callers. OAuth would mean
running authorization-server and discovery-metadata machinery to protect a
service whose entire value is one API call. A credential table's only advantage
over a single secret is independent revocation, which matters only once callers
are many.

## Decision

A single shared bearer credential in `MCP_AUTH_TOKEN`, compared in constant time
to avoid a timing side channel, enforced by a `TokenVerifier` subclass whose
`verify_token` returns an `AccessToken` on match and `None` otherwise.

## Consequences

Revocation is all-or-nothing: rotating the secret disconnects every caller at
once. Promoting to per-client credentials later means replacing the comparison
against one string with a lookup into a table — the verifier interface does not
change, so the upgrade is contained.

Because `TokenVerifier` serves no OAuth discovery metadata, clients must be
configured with the bearer credential directly rather than discovering it.