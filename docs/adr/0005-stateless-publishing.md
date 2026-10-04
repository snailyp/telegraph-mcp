# 5. Publishing is stateless; updates are explicit

Date: 2026-02-13

## Status

Accepted

## Context

Publishing the same Markdown document twice could create a second Page or update
the first. The latter requires remembering a mapping from document to `path`,
which means persistent storage: a location to configure, state lost when a
container is rebuilt, divergence between replicas.

The benefit of that storage is that the caller does not have to pass a `path`.

## Decision

The server stores nothing. Re-publishing creates a new Page. Updating an
existing Page is an explicit act: `publish_markdown` accepts an optional `path`,
and when it is present the Page at that path is updated in place — URL unchanged
— instead of a new Page being created.

The URL returned by a publish doubles as the handle for a later update.

## Consequences

Callers that want to update a Page must carry its `path` themselves, which in
practice means an agent reads it back from the previous result or from the URL.

In exchange the server has no storage to configure, survives restarts with no
data loss, and scales horizontally without coordination. Adding a document-to-
path mapping later is additive: it introduces a new lookup key without changing
the tool signature.