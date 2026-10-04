# 1. Telegraph access token is operator-configured, and has no fallback

Date: 2026-02-13

## Status

Accepted

## Context

Publishing a Page requires a Telegraph access token, which determines the
account the Page belongs to. Three sources are conceivable: configured by the
operator, created automatically on first startup, or supplied per-call by the
MCP client.

Per-call tokens would let any client publish under any identity, and would
route the token through MCP request bodies and client-side logs. Automatic
account creation would silently mint accounts the operator never asked for, and
a lost token makes every Page published under it permanently uneditable.

## Decision

The token comes from the `TELEGRAPH_ACCESS_TOKEN` environment variable. When it
is absent the server refuses to start, and the error names the variable and how
to obtain it.

A separate one-shot `bootstrap` command wraps Telegraph's `createAccount` and
prints the token for the operator to paste into their configuration. It is not
run as part of server startup.

## Consequences

Every Page served by one deployment belongs to one Telegraph account. Rotating
the account means republishing, because existing Pages stay tied to the old
token.

Operators get an explicit, visible step for obtaining a token instead of
discovering accounts after the fact. The bootstrap command is the only path
that creates accounts, and it only runs when a human asks it to.