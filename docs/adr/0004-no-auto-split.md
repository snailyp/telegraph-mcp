# 4. An oversized document is reported, not split or truncated

Date: 2026-02-13

## Status

Accepted

## Context

Telegraph documents a content limit of "up to 64 KB" for `createPage`. The
documentation states no node-count limit, so size is the binding constraint.
Long documents will exceed it.

Three responses are possible: report the failure, split the document across
multiple Pages, or truncate it.

Truncation is indefensible — it publishes a document that looks complete and is
not.

Splitting is more tempting, since it "works". But it changes the tool's contract
from one URL to a variable-length list of URLs, forcing every caller to handle
both shapes. It also requires decisions the converter has no standing to make:
where to cut, whether the title repeats, how a table of contents spans the
split. Those are authorial choices.

## Decision

A document exceeding the limit fails, and the error reports both the actual
serialized size and the documented limit, so the caller knows how much to cut.
The tool returns exactly one page URL, always.

## Consequences

Callers publishing long documents must split them and issue several calls. The
return shape stays stable for everyone else, which is the property that makes
the tool composable.

If automatic splitting is ever wanted, it belongs behind an explicit opt-in
argument so the default contract is unchanged.