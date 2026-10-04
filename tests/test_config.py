"""Configuration tests: the startup-failure rules are the point.

ADR 1 and ADR 2 both promise that a server missing a credential refuses to start
rather than failing later at request time. That only holds if it is tested.
"""

from __future__ import annotations

import pytest

from telegraph_mcp.config import DEFAULT_MCP_PATH, Settings
from telegraph_mcp.errors import ConfigurationError


def settings(**overrides: str | int) -> Settings:
    """Build settings without reading a developer's real .env file."""

    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class TestStartupValidation:
    def test_missing_telegraph_token_is_reported(self):
        config = settings(mcp_auth_token="mcp-secret")
        with pytest.raises(ConfigurationError) as caught:
            config.require_startup_ready()
        assert "TELEGRAPH_ACCESS_TOKEN" in str(caught.value)

    def test_missing_mcp_token_is_reported(self):
        config = settings(telegraph_access_token="telegraph-secret")
        with pytest.raises(ConfigurationError) as caught:
            config.require_startup_ready()
        assert "MCP_AUTH_TOKEN" in str(caught.value)

    def test_both_missing_are_reported_together(self):
        # One run should reveal every gap, not just the first one found.
        config = settings()
        problems = config.startup_problems()
        assert len(problems) == 2
        joined = " ".join(problems)
        assert "TELEGRAPH_ACCESS_TOKEN" in joined
        assert "MCP_AUTH_TOKEN" in joined

    def test_a_fully_configured_server_starts(self):
        config = settings(
            telegraph_access_token="telegraph-secret", mcp_auth_token="mcp-secret"
        )
        config.require_startup_ready()  # must not raise

    def test_whitespace_only_credentials_count_as_missing(self):
        config = settings(telegraph_access_token="   ", mcp_auth_token="\t")
        assert len(config.startup_problems()) == 2

    def test_the_error_explains_how_to_get_a_telegraph_token(self):
        config = settings(mcp_auth_token="x")
        with pytest.raises(ConfigurationError) as caught:
            config.require_startup_ready()
        assert "bootstrap" in str(caught.value)

    def test_the_error_explains_how_to_make_an_mcp_token(self):
        config = settings(telegraph_access_token="x")
        with pytest.raises(ConfigurationError) as caught:
            config.require_startup_ready()
        assert "secrets" in str(caught.value)


class TestErrorMessagesDoNotLeak:
    def test_startup_error_does_not_contain_a_configured_secret(self):
        config = settings(
            telegraph_access_token="", mcp_auth_token="super-secret-mcp-token"
        )
        with pytest.raises(ConfigurationError) as caught:
            config.require_startup_ready()
        # The present credential must not be echoed while reporting the missing one.
        assert "super-secret-mcp-token" not in str(caught.value)


class TestDefaults:
    def test_host_defaults_to_localhost(self):
        # ADR 8: exposing the server must be a deliberate act.
        assert settings().host == "127.0.0.1"

    def test_port_defaults_to_8000(self):
        assert settings().port == 8000

    def test_mcp_path_defaults_to_slash_mcp(self):
        assert settings().mcp_path == DEFAULT_MCP_PATH == "/mcp"

    def test_author_url_defaults_to_telegraph(self):
        assert "telegra.ph" in settings().telegraph_author_url

    def test_author_name_defaults_to_empty(self):
        assert settings().telegraph_author_name == ""


class TestMcpPathNormalization:
    def test_leading_slash_is_added_when_omitted(self):
        assert settings(mcp_path="mcp").mcp_path == "/mcp"

    def test_existing_leading_slash_is_kept(self):
        assert settings(mcp_path="/custom").mcp_path == "/custom"

    def test_empty_path_falls_back_to_the_default(self):
        assert settings(mcp_path="  ").mcp_path == DEFAULT_MCP_PATH


class TestPortValidation:
    @pytest.mark.parametrize("port", [0, 65536, -1])
    def test_out_of_range_ports_are_rejected(self, port):
        with pytest.raises(Exception):
            settings(port=port)