# Domain: telegraph-mcp

## What this is

An MCP server that takes a Markdown document and publishes it as a **Telegraph
page**, returning the page's URL. Built on the FastMCP framework, speaking
Streamable HTTP, gated behind a bearer credential.

It exists because publishing a document to a shareable, readable URL is a
recurring need, and Telegraph is a zero-friction host for it. The MCP surface
means an agent can publish on the user's behalf without a browser.

## Language

Two credentials meet in this system and must never be conflated. They have
different scopes, different blast radii, and different rotation stories.

**MCP client credential** — the shared secret a client presents to *call this
server*. Guards admission. A leak lets someone else spend your Telegraph quota
under your identity. Configured as `MCP_AUTH_TOKEN`.

**Telegraph access token** — the credential that determines *which Telegraph
account a published page belongs to*. Guards authorship. A leak lets someone
else publish and edit pages as you. Configured as `TELEGRAPH_ACCESS_TOKEN`.

Never abbreviate either to just "token" in code, config, docs, or tool
descriptions. `MCP_AUTH_TOKEN` is not a Telegraph token and vice versa.

**Markdown document** — the *input*: a blob of Markdown text.

**Page** — the *output resource* created on Telegraph. It has a `path`, a `url`,
and a `title`. This is the noun the tools speak in.

**Page URL** — the address returned to the caller, `https://telegra.ph/<path>`.

Do not use "article" or "doc" — they are synonyms for "Page" and "Markdown
document" respectively and their presence signals a vocabulary leak.

## Pages are the identity-bearing resource

Everything the tools do is expressed as operations on Pages:

- publishing a Markdown document *creates* a Page
- re-publishing with a `path` *updates* that Page in place, URL unchanged
- the `path` is the durable handle; the URL is human-facing

This vocabulary is binding. When a concept called "Page" in the spec is missing
from the code, that is a signal to stop and reconcile rather than invent a local
synonym.

## Rules

These are transitions and invariants, not definitions. Each is a place where
the code must enforce something.

- **Telegraph token never leaves the process.** It must not appear in tool
  return values, in error messages, or in logs. Authentication failures must not
  echo the received value. This holds for `MCP_AUTH_TOKEN` as well.
- **Missing required configuration is a startup failure, not a runtime
  surprise.** A server without `TELEGRAPH_ACCESS_TOKEN` or `MCP_AUTH_TOKEN` must
  refuse to start, with an error naming the missing variable and how to obtain
  it.
- **`createPage` is never automatically retried.** It is not idempotent and
  Telegraph offers no idempotency key; a timeout may mean the Page was created
  successfully. A retry would mint a duplicate Page and hand the caller the
  second URL while the first becomes an orphan. Timeouts are reported as
  failures and the decision returns to the caller.
- **Content that Telegraph cannot represent is degraded, never silently
  dropped.** A user who sees "published" must be able to trust that the content
  survived. The per-construct mapping lives in
  [`docs/adr/0003-markdown-degradation.md`](docs/adr/0003-markdown-degradation.md).
- **A document exceeding the single-page limit is a reported failure.** It is
  not truncated and not auto-split, because both would break the one-URL
  contract or corrupt document structure without the author's consent.
- **Publishing is stateless.** The server keeps no record mapping a Markdown
  document to a Page. Updating is an explicit act: the caller passes the `path`.
