# telegraph-mcp

An MCP server that turns a Markdown document into a [Telegraph](https://telegra.ph)
page and hands back the URL.

Built on [FastMCP](https://gofastmcp.com), speaking Streamable HTTP, gated behind
a bearer credential.

## What it does

Two tools:

- **`publish_markdown`** — converts a Markdown document to Telegraph's node
  format, publishes it, and returns the page URL. Pass the `path` from a
  previous publish to update that page in place instead of creating a new one.
- **`get_page`** — reads an existing page's metadata and URL.

## Setup

### 1. Create a Telegraph account

Publishing requires a Telegraph access token, which determines whose account the
pages belong to:

```bash
uv run telegraph-mcp bootstrap
```

This creates an account once and prints the token. It is the only time the token
is shown — save it now. The command also prints a login URL (single-use, valid
five minutes) if you want to manage the account in a browser afterwards.

The token is never created automatically at startup, so you will never end up
with accounts you did not ask for, and a lost token will never silently orphan
pages you still want to edit.

### 2. Configure

Copy `.env.example` to `.env` and fill it in:

| Variable                 | Required | Purpose                                                    |
| ------------------------ | -------- | ---------------------------------------------------------- |
| `TELEGRAPH_ACCESS_TOKEN` | yes      | Whose Telegraph account published pages belong to          |
| `MCP_AUTH_TOKEN`         | yes      | The secret clients present to call this server             |
| `TELEGRAPH_AUTHOR_NAME`  | no       | Byline applied to published pages                          |
| `TELEGRAPH_AUTHOR_URL`   | no       | Author link applied to published pages                     |
| `HOST`                   | no       | Bind address; defaults to `127.0.0.1`                      |
| `PORT`                   | no       | Bind port; defaults to `8000`                              |
| `MCP_PATH`               | no       | MCP endpoint path; defaults to `/mcp`                      |

These two credentials do different jobs. `TELEGRAPH_ACCESS_TOKEN` decides whose
account a page belongs to. `MCP_AUTH_TOKEN` decides who is allowed to call the
server at all. Keeping them distinct matters: leaking the first lets someone
else publish as you, leaking the second lets someone else use your server.

Generate the admission secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The server refuses to start if either required variable is missing, and names
the missing one in the error.

### 3. Run

```bash
uv run telegraph-mcp serve
```

Serves Streamable HTTP at `http://127.0.0.1:8000/mcp` by default, stateless, so
it sits behind a reverse proxy or scales horizontally without coordination.

It binds to localhost on purpose. Exposing it to a network is a deliberate
change: set `HOST=0.0.0.0`, and keep it behind TLS.

## Connecting a client

Both examples send the admission secret as a bearer credential.

**Claude Code**

```bash
claude mcp add --transport http telegraph \
  http://127.0.0.1:8000/mcp \
  --header "Authorization: Bearer $MCP_AUTH_TOKEN"
```

**Cursor** (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "telegraph": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

## Markdown support

Telegraph accepts a fixed set of node types, narrower than Markdown. Anything it
cannot represent is converted to the nearest equivalent rather than dropped — a
document that publishes successfully is a document whose content survived.

| Markdown                  | Published as                                          |
| ------------------------- | ----------------------------------------------------- |
| `# Heading`               | The page title (not repeated in the body)             |
| `## Heading`              | `h3`                                                  |
| `### Heading`             | `h4`                                                  |
| `####`–`######`           | `h4`                                                  |
| Table                     | A preformatted code block containing the table        |
| Footnote reference        | Numbered link to the footnote                         |
| Footnote definition       | Link list appended at the end of the page             |
| Task list `- [x]` / `- [ ]` | `☑` / `☐` marker inside the list item               |
| Raw HTML                  | Escaped, shown as literal text                        |
| Image                     | `figure` with the image; alt text kept as a caption   |

Headings below `h3` collapse to `h4`, and table alignment is lost in the code
block. Those are the costs of publishing into a fixed node set; the text, which
is what a reader needs, survives.

### Title

The title comes from the `title` argument, or from the document's first level-1
heading if the argument is omitted. If neither exists the call fails rather than
inventing a title from the opening line of prose.

### Size limit

Telegraph pages hold up to 64 KB of content. A document that exceeds it fails
with the actual size and the limit. It is not truncated and not split, because
the tool's contract is one page URL per call — split the document and publish
the parts yourself if you need to.

## Development

```bash
uv sync --extra dev
uv run pytest
```

Tests never touch the real Telegraph API: the converter is tested directly, HTTP
interactions are stubbed with `respx`, and tools run in-process through
FastMCP's client. Admission control is tested against the Starlette app instead,
because the in-process client bypasses the HTTP middleware that enforces the
bearer credential.

Design decisions are recorded in [`docs/adr/`](docs/adr/), and the project's
vocabulary is defined in [`CONTEXT.md`](CONTEXT.md).

## Running in Docker

```bash
docker build -t telegraph-mcp .
docker run --rm -p 8000:8000 \
  -e HOST=0.0.0.0 \
  -e TELEGRAPH_ACCESS_TOKEN=... \
  -e MCP_AUTH_TOKEN=... \
  telegraph-mcp
```

`HOST=0.0.0.0` is required inside a container, or the port mapping reaches
nothing.

## License

MIT