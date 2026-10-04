"""Tool-level tests, run in-process with no listener.

FastMCP's client accepts the server object directly, so the tools and their
wiring are exercised without a socket. Admission control is the exception: the
in-process client bypasses the HTTP middleware that enforces the bearer
credential, so those tests drive the ASGI app instead. Telegraph itself is
stubbed — the suite never touches the network (ADR 7).
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import Client
from starlette.testclient import TestClient

from telegraph_mcp.config import Settings
from telegraph_mcp.server import build_server

API_BASE = "https://api.telegra.ph"
CREATE_PAGE = f"{API_BASE}/createPage"
EDIT_PAGE = f"{API_BASE}/editPage"
GET_PAGE = f"{API_BASE}/getPage"

MCP_SECRET = "mcp-secret"
TELEGRAPH_SECRET = "telegraph-secret"

PAGE_RESULT = {
    "ok": True,
    "result": {
        "path": "Published-01-01",
        "url": "https://telegra.ph/Published-01-01",
        "title": "Published",
        "description": "blurb",
    },
}


def settings(**overrides):
    defaults = {
        "telegraph_access_token": TELEGRAPH_SECRET,
        "mcp_auth_token": MCP_SECRET,
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def server(**overrides):
    return build_server(settings(**overrides))


def authed(**overrides):
    """An in-memory client over one server instance.

    The in-memory transport talks to the server object directly, so there is no
    HTTP layer to authenticate against — passing a credential here raises
    instead. These tests are about the tools; admission is covered separately by
    `TestAdmissionControl`, which goes over ASGI.
    """

    return Client(server(**overrides))


class TestPublishing:
    @respx.mock
    async def test_publish_returns_the_page_url(self):
        respx.post(CREATE_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with authed() as client:
            result = await client.call_tool(
                "publish_markdown", {"markdown": "# Published\n\nbody"}
            )
        assert result.data.url == "https://telegra.ph/Published-01-01"

    @respx.mock
    async def test_publish_returns_the_path_for_later_updates(self):
        respx.post(CREATE_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with authed() as client:
            result = await client.call_tool("publish_markdown", {"markdown": "# T\n\nb"})
        assert result.data.path == "Published-01-01"

    @respx.mock
    async def test_a_new_publish_is_not_marked_updated(self):
        respx.post(CREATE_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with authed() as client:
            result = await client.call_tool("publish_markdown", {"markdown": "# T\n\nb"})
        assert result.data.updated is False

    @respx.mock
    async def test_the_configured_access_token_is_used(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with authed() as client:
            await client.call_tool("publish_markdown", {"markdown": "# T\n\nb"})
        body = route.calls.last.request.content.decode()
        assert f"access_token={TELEGRAPH_SECRET}" in body

    @respx.mock
    async def test_explicit_title_overrides_the_heading(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with authed() as client:
            await client.call_tool(
                "publish_markdown", {"markdown": "# From Doc\n\nb", "title": "Given"}
            )
        assert "title=Given" in route.calls.last.request.content.decode()

    @respx.mock
    async def test_the_heading_is_used_when_no_title_is_given(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with authed() as client:
            await client.call_tool("publish_markdown", {"markdown": "# From Doc\n\nb"})
        assert "title=From+Doc" in route.calls.last.request.content.decode()

    @respx.mock
    async def test_configured_author_is_applied(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with authed(telegraph_author_name="Ada") as client:
            await client.call_tool("publish_markdown", {"markdown": "# T\n\nb"})
        assert "author_name=Ada" in route.calls.last.request.content.decode()


class TestUpdating:
    @respx.mock
    async def test_passing_a_path_updates_instead_of_creating(self):
        edit = respx.post(EDIT_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        create = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with authed() as client:
            await client.call_tool(
                "publish_markdown", {"markdown": "# T\n\nb", "path": "Published-01-01"}
            )
        assert edit.called
        assert not create.called

    @respx.mock
    async def test_an_update_is_marked_updated(self):
        respx.post(EDIT_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with authed() as client:
            result = await client.call_tool(
                "publish_markdown", {"markdown": "# T\n\nb", "path": "Published-01-01"}
            )
        assert result.data.updated is True

    @respx.mock
    async def test_an_update_accepts_a_full_url_as_the_path(self):
        route = respx.post(EDIT_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with authed() as client:
            await client.call_tool(
                "publish_markdown",
                {"markdown": "# T\n\nb", "path": "https://telegra.ph/Published-01-01"},
            )
        assert "path=Published-01-01" in route.calls.last.request.content.decode()

    @respx.mock
    async def test_an_update_keeps_the_url_stable(self):
        respx.post(EDIT_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with authed() as client:
            result = await client.call_tool(
                "publish_markdown", {"markdown": "# T\n\nb", "path": "Published-01-01"}
            )
        # The URL is the caller's handle; an update must not move the page.
        assert result.data.url == "https://telegra.ph/Published-01-01"


class TestGetPage:
    @respx.mock
    async def test_reads_a_page_by_path(self):
        respx.post(GET_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with authed() as client:
            result = await client.call_tool("get_page", {"path": "Published-01-01"})
        assert result.data.title == "Published"
        assert result.data.url == "https://telegra.ph/Published-01-01"


class TestAdmissionControl:
    """Auth is enforced by HTTP middleware, so these run against the ASGI app.

    An in-memory `Client` hands the server object straight to the transport and
    never touches the auth middleware, so a test written against it would pass
    whether or not admission worked. `TestClient` drives the real Starlette app
    from `http_app()` — and, crucially, runs its lifespan, which is where the
    streamable-HTTP session manager is created.

    The assertion is "not rejected" rather than "200": admission is what is
    under test here, and the MCP handshake's own status codes are not.
    """

    @staticmethod
    def app(**overrides):
        return server(**overrides).http_app(path="/mcp", stateless_http=True)

    @staticmethod
    def post(client: TestClient, *, headers: dict[str, str] | None = None):
        return client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )

    def test_a_request_without_a_credential_is_rejected(self):
        with TestClient(self.app()) as client:
            assert self.post(client).status_code == 401

    def test_a_request_with_a_wrong_credential_is_rejected(self):
        with TestClient(self.app()) as client:
            response = self.post(client, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_a_valid_credential_passes_admission(self):
        with TestClient(self.app()) as client:
            response = self.post(
                client, headers={"Authorization": f"Bearer {MCP_SECRET}"}
            )
        assert response.status_code not in (401, 403)

    def test_a_malformed_authorization_header_is_rejected(self):
        with TestClient(self.app()) as client:
            response = self.post(client, headers={"Authorization": MCP_SECRET})
        assert response.status_code == 401

    def test_the_rejection_does_not_echo_the_credential(self):
        with TestClient(self.app()) as client:
            response = self.post(
                client, headers={"Authorization": "Bearer wrong-secret-value"}
            )
        assert "wrong-secret-value" not in response.text


class TestTitleFailures:
    async def test_no_title_anywhere_fails(self):
        async with authed() as client:
            with pytest.raises(Exception) as caught:
                await client.call_tool("publish_markdown", {"markdown": "just prose"})
        assert "title" in str(caught.value).lower()

    async def test_an_overlong_title_fails(self):
        async with authed() as client:
            with pytest.raises(Exception) as caught:
                await client.call_tool(
                    "publish_markdown", {"markdown": "body", "title": "x" * 300}
                )
        assert "256" in str(caught.value)

    async def test_a_title_at_the_limit_is_accepted(self):
        with respx.mock:
            respx.post(CREATE_PAGE).mock(
                return_value=httpx.Response(200, json=PAGE_RESULT)
            )
            async with authed() as client:
                await client.call_tool(
                    "publish_markdown", {"markdown": "body", "title": "x" * 256}
                )


class TestSizeLimit:
    async def test_an_oversized_document_fails_rather_than_being_split(self):
        # ADR 4: the contract is one page URL, so exceeding the limit is an error.
        async with authed() as client:
            with pytest.raises(Exception) as caught:
                await client.call_tool(
                    "publish_markdown", {"markdown": "# T\n\n" + "filler " * 20000}
                )
        message = str(caught.value)
        assert "64" in message or "limit" in message.lower()

    async def test_the_error_reports_the_actual_size(self):
        async with authed() as client:
            with pytest.raises(Exception) as caught:
                await client.call_tool(
                    "publish_markdown", {"markdown": "# T\n\n" + "filler " * 20000}
                )
        assert "bytes" in str(caught.value)

    @respx.mock
    async def test_an_oversized_document_never_reaches_telegraph(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with authed() as client:
            with pytest.raises(Exception):
                await client.call_tool(
                    "publish_markdown", {"markdown": "# T\n\n" + "filler " * 20000}
                )
        assert not route.called


class TestToolSurface:
    async def test_both_tools_are_exposed(self):
        async with authed() as client:
            names = {tool.name for tool in await client.list_tools()}
        assert names == {"publish_markdown", "get_page"}

    async def test_publish_advertises_its_optional_arguments(self):
        async with authed() as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        schema = tools["publish_markdown"].input_schema
        assert set(schema["properties"]) == {"markdown", "title", "path"}
        assert schema["required"] == ["markdown"]

    async def test_tools_have_descriptions_an_agent_can_act_on(self):
        async with authed() as client:
            tools = await client.list_tools()
        for tool in tools:
            assert tool.description and len(tool.description) > 20


class TestCredentialHygiene:
    @respx.mock
    async def test_a_telegraph_error_does_not_leak_the_access_token(self):
        respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(
                200, json={"ok": False, "error": "ACCESS_TOKEN_INVALID"}
            )
        )
        async with authed() as client:
            with pytest.raises(Exception) as caught:
                await client.call_tool("publish_markdown", {"markdown": "# T\n\nb"})
        assert TELEGRAPH_SECRET not in str(caught.value)

    async def test_a_missing_title_error_does_not_leak_credentials(self):
        async with authed() as client:
            with pytest.raises(Exception) as caught:
                await client.call_tool("publish_markdown", {"markdown": "prose"})
        message = str(caught.value)
        assert TELEGRAPH_SECRET not in message
        assert MCP_SECRET not in message