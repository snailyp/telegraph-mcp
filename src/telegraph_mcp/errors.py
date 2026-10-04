"""Failure types, and the one rule that governs their messages.

Every message raised from here is shown to a caller over MCP. None of them may
contain a Telegraph access token or an MCP client credential, including the
messages that report a rejected credential — a failed authentication attempt is
exactly when echoing the received value would be most useful to an attacker.
"""

from __future__ import annotations

TELEGRAPH_CONTENT_LIMIT_BYTES = 64 * 1024
TELEGRAPH_TITLE_LIMIT_CHARS = 256

TELEGRAPH_HOST = "telegra.ph"
TELEGRAPH_API_BASE = f"https://api.{TELEGRAPH_HOST}"
ACCOUNT_PATH = "/createAccount"
PAGE_PATH = "/createPage"
EDIT_PATH = "/editPage"


class TelegraphMCPError(Exception):
    """Base class for every failure this server reports to a caller."""


class ConfigurationError(TelegraphMCPError):
    """The server is missing configuration it cannot run without."""


class TelegraphAPIError(TelegraphMCPError):
    """Telegraph answered, and the answer was an error."""


class TelegraphUnreachableError(TelegraphMCPError):
    """No usable answer came back from Telegraph."""


class MarkdownError(TelegraphMCPError):
    """The Markdown document could not be turned into a page body."""


class DocumentTooLargeError(MarkdownError):
    """The serialized page body exceeds the single-page limit."""

    def __init__(self, actual_bytes: int, limit_bytes: int) -> None:
        self.actual_bytes = actual_bytes
        self.limit_bytes = limit_bytes
        excess = actual_bytes - limit_bytes
        super().__init__(
            f"The document's page body is {actual_bytes:,} bytes, which exceeds "
            f"Telegraph's {limit_bytes:,}-byte limit by {excess:,} bytes. "
            "Split the document and publish it as separate pages."
        )


class MissingTitleError(MarkdownError):
    """No title was supplied and none could be derived from the document."""

    def __init__(self) -> None:
        super().__init__(
            "A page needs a title. Pass the `title` argument, or start the "
            "Markdown document with a single level-1 heading (`# Title`)."
        )


class TitleTooLongError(MarkdownError):
    """The title exceeds Telegraph's limit."""

    def __init__(self, actual_chars: int, limit_chars: int) -> None:
        self.actual_chars = actual_chars
        self.limit_chars = limit_chars
        super().__init__(
            f"The page title is {actual_chars:,} characters, which exceeds "
            f"Telegraph's {limit_chars:,}-character limit."
        )


class InvalidPagePathError(TelegraphMCPError):
    """A page path handed to the update flow is unusable."""


def to_error_summary(response_text: str) -> str:
    """Condense a Telegraph error body for inclusion in a message.

    Telegraph reports failures as ``{"error": "..."}``. Anything else is
    truncated rather than passed through, so a surprising response cannot smuggle
    a large body into a caller-visible message.
    """

    text = response_text.strip()
    if not text:
        return "no response body"
    return text if len(text) <= 200 else f"{text[:200]} (truncated)"


__all__ = [
    "ACCOUNT_PATH",
    "ConfigurationError",
    "DocumentTooLargeError",
    "EDIT_PATH",
    "InvalidPagePathError",
    "MarkdownError",
    "MissingTitleError",
    "PAGE_PATH",
    "TELEGRAPH_API_BASE",
    "TELEGRAPH_CONTENT_LIMIT_BYTES",
    "TELEGRAPH_HOST",
    "TELEGRAPH_TITLE_LIMIT_CHARS",
    "TelegraphAPIError",
    "TelegraphMCPError",
    "TelegraphUnreachableError",
    "TitleTooLongError",
    "to_error_summary",
]