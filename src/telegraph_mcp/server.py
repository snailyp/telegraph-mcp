"""The MCP surface: two tools, both of which speak in Pages."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .auth import StaticBearerVerifier
from .config import Settings, get_settings
from .errors import (
    TELEGRAPH_CONTENT_LIMIT_BYTES,
    TELEGRAPH_TITLE_LIMIT_CHARS,
    DocumentTooLargeError,
    TitleTooLongError,
)
from .markdown import convert_markdown, resolve_title, serialize
from .telegraph import ReadOnlyClient, WritableClient


class PageResult(BaseModel):
    """A published page, as returned to a caller.

    `url` answers "where is it"; `path` is the durable handle for updating this
    page later without creating a duplicate. See ADR 5.
    """

    url: str = Field(description="Public address of the page on telegra.ph")
    path: str = Field(description="Page path; pass it back to update this page")
    title: str = Field(description="Title the page was published under")
    description: str = Field(default="", description="Short blurb derived from the body")
    updated: bool = Field(
        default=False, description="True when an existing page was updated in place"
    )


def _prepare_title(explicit: str | None, from_document: str | None) -> str:
    title = resolve_title(explicit, from_document)
    if len(title) > TELEGRAPH_TITLE_LIMIT_CHARS:
        raise TitleTooLongError(len(title), TELEGRAPH_TITLE_LIMIT_CHARS)
    return title


def _prepare_content(markdown: str) -> tuple[str, str | None]:
    """Convert Markdown and enforce the single-page size limit.

    Exceeding the limit is a reported failure rather than a silent split: the
    tool's contract is one page URL per document. See ADR 4.
    """

    result = convert_markdown(markdown)
    payload = serialize(result.nodes)
    size = len(payload.encode("utf-8"))
    if size > TELEGRAPH_CONTENT_LIMIT_BYTES:
        raise DocumentTooLargeError(size, TELEGRAPH_CONTENT_LIMIT_BYTES)
    return payload, result.title


def build_server(settings: Settings | None = None) -> FastMCP:
    """Construct the MCP server, with admission control attached."""

    config = settings or get_settings()
    mcp = FastMCP(
        name="telegraph-mcp",
        instructions=(
            "Publishes Markdown documents as Telegraph pages and returns the "
            "page URL. Pass `path` to update an existing page instead of "
            "creating a new one."
        ),
        auth=StaticBearerVerifier(config.mcp_auth_token),
    )

    def _author_fields() -> dict[str, str]:
        fields: dict[str, str] = {}
        if config.telegraph_author_name:
            fields["author_name"] = config.telegraph_author_name
        if config.telegraph_author_url:
            fields["author_url"] = config.telegraph_author_url
        return fields

    @mcp.tool
    async def publish_markdown(
        markdown: Annotated[
            str,
            Field(
                description=(
                    "The Markdown document to publish. GFM is supported; "
                    "constructs Telegraph cannot represent (tables, footnotes, "
                    "h1/h2, task lists, raw HTML) are converted rather than "
                    "dropped."
                )
            ),
        ],
        title: Annotated[
            str | None,
            Field(
                description=(
                    "Page title. When omitted, the document's first level-1 "
                    "heading is used; if there is none, the call fails."
                )
            ),
        ] = None,
        path: Annotated[
            str | None,
            Field(
                description=(
                    "Path or URL of an existing page to update in place. When "
                    "omitted a new page is created."
                )
            ),
        ] = None,
    ) -> PageResult:
        """Publish a Markdown document as a Telegraph page and return its URL.

        Use this to turn Markdown into a shareable link. Publishing the same
        document twice creates two pages; to revise a page, pass the `path` that
        a previous publish returned.
        """

        content, from_document = _prepare_content(markdown)
        resolved_title = _prepare_title(title, from_document)

        async with WritableClient() as client:
            if path:
                page = await client.edit_page(
                    access_token=config.telegraph_access_token,
                    path_or_url=path,
                    title=resolved_title,
                    content=content,
                    **_author_fields(),
                )
                return PageResult(
                    url=page.url,
                    path=page.path,
                    title=page.title,
                    description=page.description,
                    updated=True,
                )

            page = await client.create_page(
                access_token=config.telegraph_access_token,
                title=resolved_title,
                content=content,
                **_author_fields(),
            )
        return PageResult(
            url=page.url,
            path=page.path,
            title=page.title,
            description=page.description,
            updated=False,
        )

    @mcp.tool
    async def get_page(
        path: Annotated[
            str, Field(description="Path or URL of the Telegraph page to read.")
        ],
    ) -> PageResult:
        """Read an existing Telegraph page's metadata and URL."""

        async with ReadOnlyClient() as client:
            page = await client.get_page(path)
        return PageResult(
            url=page.url,
            path=page.path,
            title=page.title,
            description=page.description,
            updated=False,
        )

    return mcp


def build_server_if_ready(settings: Settings | None = None) -> FastMCP:
    """Build the server, refusing to start on incomplete configuration.

    Missing credentials are a startup failure, not a surprise raised on the
    first request. See ADR 1 and ADR 2.
    """

    config = settings or get_settings()
    config.require_startup_ready()
    return build_server(config)


__all__ = ["PageResult", "build_server", "build_server_if_ready"]