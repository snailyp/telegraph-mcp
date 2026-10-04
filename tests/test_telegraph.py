"""Tests for the Telegraph client: request shaping and the retry boundary.

The retry tests matter most. `createPage` is not idempotent, so a retry after a
timeout can mint a duplicate page that the API cannot delete. ADR 6 promises
automatic retry happens only where repetition is provably harmless, and these
tests pin that promise.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from telegraph_mcp.errors import (
    InvalidPagePathError,
    TelegraphAPIError,
    TelegraphUnreachableError,
)
from telegraph_mcp.markdown import serialize
from telegraph_mcp.telegraph import (
    DEFAULT_TIMEOUT_SECONDS,
    ReadOnlyClient,
    WritableClient,
    create_account,
    normalize_page_path,
)

API_BASE = "https://api.telegra.ph"
CREATE_PAGE = f"{API_BASE}/createPage"
EDIT_PAGE = f"{API_BASE}/editPage"
GET_PAGE = f"{API_BASE}/getPage"
CREATE_ACCOUNT = f"{API_BASE}/createAccount"

PAGE_RESULT = {
    "ok": True,
    "result": {
        "path": "My-Page-01-01",
        "url": "https://telegra.ph/My-Page-01-01",
        "title": "My Page",
        "description": "a blurb",
        "author_name": "Author",
    },
}


class TestPathNormalization:
    def test_bare_path_is_unchanged(self):
        assert normalize_page_path("My-Page-01-01") == "My-Page-01-01"

    def test_https_url_is_reduced_to_a_path(self):
        assert normalize_page_path("https://telegra.ph/My-Page-01-01") == "My-Page-01-01"

    def test_http_url_is_reduced_to_a_path(self):
        assert normalize_page_path("http://telegra.ph/My-Page-01-01") == "My-Page-01-01"

    def test_host_without_scheme_is_reduced_to_a_path(self):
        assert normalize_page_path("telegra.ph/My-Page-01-01") == "My-Page-01-01"

    def test_query_and_fragment_are_stripped(self):
        assert normalize_page_path("https://telegra.ph/Page-01-01?x=1#top") == "Page-01-01"

    def test_surrounding_whitespace_is_ignored(self):
        assert normalize_page_path("  Page-01-01  ") == "Page-01-01"

    def test_empty_input_is_rejected(self):
        with pytest.raises(InvalidPagePathError):
            normalize_page_path("   ")

    def test_input_with_spaces_is_rejected(self):
        with pytest.raises(InvalidPagePathError):
            normalize_page_path("not a path")


class TestCreatePageRequest:
    @respx.mock
    async def test_posts_to_create_page(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with WritableClient() as client:
            await client.create_page(
                access_token="tok", title="T", content="[]"
            )
        assert route.called

    @respx.mock
    async def test_sends_the_access_token_as_form_data(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with WritableClient() as client:
            await client.create_page(access_token="secret", title="T", content="[]")
        body = route.calls.last.request.content.decode()
        assert "access_token=secret" in body

    @respx.mock
    async def test_content_is_sent_as_json_text(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        payload = serialize([{"tag": "p", "children": ["hi"]}])
        async with WritableClient() as client:
            await client.create_page(access_token="t", title="T", content=payload)
        body = route.calls.last.request.content.decode()
        assert "tag" in body and "hi" in body

    @respx.mock
    async def test_author_fields_are_omitted_when_absent(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with WritableClient() as client:
            await client.create_page(access_token="t", title="T", content="[]")
        body = route.calls.last.request.content.decode()
        assert "author_name" not in body

    @respx.mock
    async def test_author_fields_are_sent_when_configured(self):
        route = respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with WritableClient() as client:
            await client.create_page(
                access_token="t",
                title="T",
                content="[]",
                author_name="A",
                author_url="https://e.com",
            )
        body = route.calls.last.request.content.decode()
        assert "author_name=A" in body

    @respx.mock
    async def test_response_is_parsed_into_a_page(self):
        respx.post(CREATE_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with WritableClient() as client:
            page = await client.create_page(access_token="t", title="T", content="[]")
        assert page.path == "My-Page-01-01"
        assert page.url == "https://telegra.ph/My-Page-01-01"
        assert page.title == "My Page"


class TestEditPageRequest:
    @respx.mock
    async def test_posts_to_edit_page_with_a_normalized_path(self):
        route = respx.post(EDIT_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with WritableClient() as client:
            await client.edit_page(
                access_token="t",
                path_or_url="https://telegra.ph/My-Page-01-01",
                title="T",
                content="[]",
            )
        body = route.calls.last.request.content.decode()
        assert "path=My-Page-01-01" in body

    @respx.mock
    async def test_rejects_an_unusable_path_before_sending(self):
        route = respx.post(EDIT_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with WritableClient() as client:
            with pytest.raises(InvalidPagePathError):
                await client.edit_page(
                    access_token="t", path_or_url="  ", title="T", content="[]"
                )
        assert not route.called

    @respx.mock
    async def test_page_url_is_preserved_across_an_edit(self):
        respx.post(EDIT_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with WritableClient() as client:
            page = await client.edit_page(
                access_token="t", path_or_url="My-Page-01-01", title="T2", content="[]"
            )
        # The URL is the caller's handle, so an update must not change it.
        assert page.url == "https://telegra.ph/My-Page-01-01"


class TestRetryBoundary:
    """ADR 6: retry only where repetition cannot duplicate a write."""

    @respx.mock
    async def test_create_page_is_not_retried_on_timeout(self):
        route = respx.post(CREATE_PAGE).mock(
            side_effect=httpx.ReadTimeout("timed out")
        )
        async with WritableClient() as client:
            with pytest.raises(TelegraphUnreachableError):
                await client.create_page(access_token="t", title="T", content="[]")
        # Retrying could have created a second page and orphaned the first.
        assert route.call_count == 1

    @respx.mock
    async def test_edit_page_is_not_retried_on_timeout(self):
        route = respx.post(EDIT_PAGE).mock(side_effect=httpx.ReadTimeout("timed out"))
        async with WritableClient() as client:
            with pytest.raises(TelegraphUnreachableError):
                await client.edit_page(
                    access_token="t", path_or_url="P-01-01", title="T", content="[]"
                )
        assert route.call_count == 1

    @respx.mock
    async def test_create_page_is_retried_when_the_connection_never_opened(self):
        # A connect error means no request reached Telegram, so repeating it
        # cannot produce a duplicate.
        route = respx.post(CREATE_PAGE).mock(
            side_effect=[
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.Response(200, json=PAGE_RESULT),
            ]
        )
        async with WritableClient() as client:
            page = await client.create_page(access_token="t", title="T", content="[]")
        assert page.path == "My-Page-01-01"
        assert route.call_count == 3

    @respx.mock
    async def test_get_page_is_retried_on_timeout(self):
        # Reads are idempotent, so a timeout is safe to repeat.
        route = respx.post(GET_PAGE).mock(
            side_effect=[
                httpx.ReadTimeout("timed out"),
                httpx.Response(200, json=PAGE_RESULT),
            ]
        )
        async with ReadOnlyClient() as client:
            await client.get_page("My-Page-01-01")
        assert route.call_count == 2

    @respx.mock
    async def test_writes_give_up_after_the_attempt_limit(self):
        route = respx.post(CREATE_PAGE).mock(side_effect=httpx.ConnectError("refused"))
        async with WritableClient() as client:
            with pytest.raises(TelegraphUnreachableError):
                await client.create_page(access_token="t", title="T", content="[]")
        assert route.call_count == 3

    @respx.mock
    async def test_timeout_message_warns_that_the_request_may_have_landed(self):
        respx.post(CREATE_PAGE).mock(side_effect=httpx.ReadTimeout("timed out"))
        async with WritableClient() as client:
            with pytest.raises(TelegraphUnreachableError) as caught:
                await client.create_page(access_token="t", title="T", content="[]")
        message = str(caught.value).lower()
        assert "may still have been processed" in message
        assert "check" in message


class TestErrorMapping:
    @respx.mock
    async def test_telegraph_error_body_becomes_an_exception(self):
        respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(
                200, json={"ok": False, "error": "CONTENT_TOO_BIG"}
            )
        )
        async with WritableClient() as client:
            with pytest.raises(TelegraphAPIError) as caught:
                await client.create_page(access_token="t", title="T", content="[]")
        assert "CONTENT_TOO_BIG" in str(caught.value)

    @respx.mock
    async def test_non_json_response_is_reported(self):
        respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(502, text="<html>bad gateway</html>")
        )
        async with WritableClient() as client:
            with pytest.raises(TelegraphAPIError):
                await client.create_page(access_token="t", title="T", content="[]")

    @respx.mock
    async def test_missing_result_object_is_reported(self):
        respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with WritableClient() as client:
            with pytest.raises(TelegraphAPIError):
                await client.create_page(access_token="t", title="T", content="[]")

    @respx.mock
    async def test_error_messages_never_leak_the_access_token(self):
        respx.post(CREATE_PAGE).mock(
            return_value=httpx.Response(
                200, json={"ok": False, "error": "ACCESS_TOKEN_INVALID"}
            )
        )
        async with WritableClient() as client:
            with pytest.raises(TelegraphAPIError) as caught:
                await client.create_page(
                    access_token="super-secret-token", title="T", content="[]"
                )
        assert "super-secret-token" not in str(caught.value)


class TestGetPage:
    @respx.mock
    async def test_requests_by_path(self):
        route = respx.post(GET_PAGE).mock(
            return_value=httpx.Response(200, json=PAGE_RESULT)
        )
        async with ReadOnlyClient() as client:
            page = await client.get_page("https://telegra.ph/My-Page-01-01")
        body = route.calls.last.request.content.decode()
        assert "path=My-Page-01-01" in body
        assert page.title == "My Page"

    @respx.mock
    async def test_accepts_a_full_url(self):
        respx.post(GET_PAGE).mock(return_value=httpx.Response(200, json=PAGE_RESULT))
        async with ReadOnlyClient() as client:
            assert (await client.get_page("https://telegra.ph/My-Page-01-01")).path == (
                "My-Page-01-01"
            )


class TestCreateAccount:
    @respx.mock
    async def test_returns_the_access_token(self):
        respx.post(CREATE_ACCOUNT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "short_name": "s",
                        "access_token": "new-token",
                        "auth_url": "https://telegra.ph/auth/x",
                    },
                },
            )
        )
        account = await create_account("s")
        assert account.access_token == "new-token"
        assert account.auth_url == "https://telegra.ph/auth/x"

    @respx.mock
    async def test_missing_token_is_reported(self):
        respx.post(CREATE_ACCOUNT).mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"short_name": "s"}})
        )
        with pytest.raises(TelegraphAPIError):
            await create_account("s")


class TestTimeoutConfiguration:
    def test_default_timeout_is_generous_enough_for_a_publish(self):
        # A publish sends up to 64 KB; too short a timeout would fail large pages.
        assert DEFAULT_TIMEOUT_SECONDS >= 30
