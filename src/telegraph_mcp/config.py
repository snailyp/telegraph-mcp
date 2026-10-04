"""Configuration and the fail-fast rules that guard startup.

The server holds two credentials that do different jobs: `TELEGRAPH_ACCESS_TOKEN`
decides whose account published pages belong to, and `MCP_AUTH_TOKEN` decides who
is allowed to call the server. They are deliberately separate settings with
separate failure messages; see ADR 1 and ADR 2.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Final

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigurationError

DEFAULT_MCP_PATH: Final = "/mcp"
DEFAULT_AUTHOR_URL: Final = "https://telegra.ph"

_BOOTSTRAP_HINT: Final = (
    "Run `telegraph-mcp bootstrap` to create a Telegraph account and print a "
    "token, then set TELEGRAPH_ACCESS_TOKEN."
)
_MCP_TOKEN_HINT: Final = (
    "Set MCP_AUTH_TOKEN to a secret of your choosing; clients present it as a "
    "bearer credential. For example: "
    'python -c "import secrets; print(secrets.token_urlsafe(32))"'
)


class Settings(BaseSettings):
    """Server settings, read from the environment or a local `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegraph_access_token: str = Field(
        default="",
        description="Telegraph account access token; determines page ownership.",
    )
    mcp_auth_token: str = Field(
        default="",
        description="Shared secret MCP clients present to call this server.",
    )
    telegraph_author_name: str = Field(
        default="",
        description="Optional author byline applied to published pages.",
    )
    telegraph_author_url: str = Field(
        default=DEFAULT_AUTHOR_URL,
        description="Optional author link applied to published pages.",
    )
    host: str = Field(default="127.0.0.1", description="Bind address.")
    port: int = Field(default=8000, ge=1, le=65535, description="Bind port.")
    mcp_path: str = Field(default=DEFAULT_MCP_PATH, description="MCP endpoint path.")

    @field_validator("mcp_path")
    @classmethod
    def _normalize_mcp_path(cls, value: str) -> str:
        path = value.strip()
        if not path:
            return DEFAULT_MCP_PATH
        return path if path.startswith("/") else f"/{path}"

    def startup_problems(self) -> list[str]:
        """Report every missing credential, so one run reveals all of them.

        Both are required. Reporting them together means an operator fixes one
        round of configuration rather than discovering the second gap only after
        the first is resolved.
        """

        problems: list[str] = []
        if not self.telegraph_access_token.strip():
            problems.append(
                f"TELEGRAPH_ACCESS_TOKEN is not set. {_BOOTSTRAP_HINT}"
            )
        if not self.mcp_auth_token.strip():
            problems.append(f"MCP_AUTH_TOKEN is not set. {_MCP_TOKEN_HINT}")
        return problems

    def require_startup_ready(self) -> None:
        """Raise if the server cannot serve requests safely."""

        problems = self.startup_problems()
        if problems:
            raise ConfigurationError(
                "Refusing to start. "
                + " ".join(problems)
                + " See .env.example for the full set of settings."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings. Cached so the environment is read once."""

    return Settings()


__all__ = ["DEFAULT_AUTHOR_URL", "DEFAULT_MCP_PATH", "Settings", "get_settings"]