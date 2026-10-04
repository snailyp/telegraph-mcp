# 6. Async HTTP, with automatic retry confined to safe reads

Date: 2026-02-13

## Status

Accepted

## Context

FastMCP tools are async, so a synchronous HTTP client would occupy a worker
thread for the duration of every Telegraph call. `httpx` provides an async
client.

Retrying failed calls is usually cheap insurance. Here it is not. `createPage`
is not idempotent and Telegraph offers no idempotency key, so a request that
timed out may well have created the Page. Retrying it produces a second Page,
hands the caller the second URL, and leaves an orphan the caller has no handle
on and cannot delete — the API has no delete.

## Decision

Use `httpx.AsyncClient` for all Telegraph calls.

Automatic retry applies only where repetition is provably harmless: read
operations such as `getPage`, and failures occurring while establishing a
connection (where no request reached the server).

`createPage` and `editPage` timeouts are reported as failures. The caller
decides whether to retry.

## Consequences

A transient network blip during publishing surfaces as an error rather than
being papered over. That is the intended trade: an error the caller can reason
about is better than a duplicate Page nobody knows about.

Retryable exceptions must be classified, not matched loosely — a connection
error and a read timeout both look like "a network problem" but only the former
guarantees no request was processed.