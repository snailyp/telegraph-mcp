"""The Telegraph API, as much of it as this server needs.

`WritableClient.create_page` and `WritableClient.edit_page` are deliberately
never retried. Neither operation is idempotent and Telegraph offers no
idempotency key, so a timed-out create may have succeeded; retrying it would
mint a duplicate page and orphan the first one, which the API cannot delete.
Only `ReadOnlyClient.get_page` and failures during connection establishment —
where no request reached the server — are retried. See ADR 6.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence, TypeVar

import httpx

from .errors import (
    ACCOUNT_PATH,
    EDIT_PATH,
    PAGE_PATH,
    TELEGRAPH_API_BASE,
    TELEGRAPH_HOST,
    InvalidPagePathError,
    TelegraphAPIError,
    TelegraphUnreachableError,
    to_error_summary,
)

DEFAULT_TIMEOUT_SECONDS: Final = 30.0
MAX_ATTEMPTS: Final = 3
_RETRY_BACKOFF_SECONDS: Final = 0.25

_PAGE_URL_PREFIXES: Final = (
    f"https://{TELEGRAPH_HOST}/",
    f"http://{TELEGRAPH_HOST}/",
    f"{TELEGRAPH_HOST}/",
)

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class Page:
    """A published Telegraph page."""

    path: str
    url: str
    title: str
    description: str = ""
    author_name: str | None = None
    author_url: str | None = None


@dataclass(frozen=True, slots=True)
class Account:
    """A Telegraph account."""

    short_name: str
    access_token: str
    author_name: str | None = None
    author_url: str | None = None
    auth_url: str | None = None
    page_count: int | None = None


def normalize_page_path(path_or_url: str) -> str:
    """Reduce a page path or URL to the bare path Telegraph uses.

    Callers hand back whatever the last publish returned, which may be a full
    URL, so accepting either shape removes a pointless failure mode.
    """

    candidate = path_or_url.strip()
    if not candidate:
        raise InvalidPagePathError(
            "A page path or URL is required to update a page."
        )

    for prefix in _PAGE_URL_PREFIXES:
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :]
            break

    candidate = candidate.split("?", 1)[0].split("#", 1)[0].strip("/")
    if not candidate or any(char.isspace() for char in candidate):
        raise InvalidPagePathError(
            f"{path_or_url!r} does not look like a Telegraph page path or URL."
        )
    return candidate


def _page_from_payload(payload: Mapping[str, Any]) -> Page:
    path = str(payload.get("path", ""))
    url = str(payload.get("url") or f"https://{TELEGRAPH_HOST}/{path}")
    return Page(
        path=path,
        url=url,
        title=str(payload.get("title", "")),
        description=str(payload.get("description", "")),
        author_name=payload.get("author_name"),
        author_url=payload.get("author_url"),
    )


class _BaseClient:
    """Shared transport: request shaping, error mapping, safe retries."""

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._client = httpx.AsyncClient(
            base_url=TELEGRAPH_API_BASE,
            timeout=timeout,
            headers={"User-Agent": "telegraph-mcp"},
        )

    async def __aenter__(self) -> "_BaseClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, path: str, data: Mapping[str, Any]) -> dict[str, Any]:
        """POST form data to a Telegraph method and return its result object."""

        response = await self._request(path, data)
        try:
            payload = response.json()
        except ValueError:
            raise TelegraphAPIError(
                f"Telegraph returned a non-JSON response for {path} "
                f"(HTTP {response.status_code}): {to_error_summary(response.text)}"
            ) from None

        if not isinstance(payload, dict):
            raise TelegraphAPIError(
                f"Telegraph returned an unexpected response shape for {path}."
            )
        if not payload.get("ok"):
            # Telegraph reports failures as {"ok": false, "error": "..."}.
            raise TelegraphAPIError(
                f"Telegraph rejected the {path.lstrip('/')} request: "
                f"{to_error_summary(str(payload.get('error', '')))}"
            )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegraphAPIError(
                f"Telegraph returned no result object for {path}."
            )
        return result

    async def _request(self, path: str, data: Mapping[str, Any]) -> httpx.Response:
        """Issue one request, plus the retries that are provably safe.

        Retry is scoped to `ConnectError` alone. That is the only failure which
        guarantees no request was processed, so it is the only one where
        repeating a non-idempotent call cannot produce a duplicate. A read
        timeout is retried only by `ReadOnlyClient`, which overrides this.
        """

        return await self._send(path, data, retry_on_connect=True)

    async def _send(
        self,
        path: str,
        data: Mapping[str, Any],
        *,
        retry_on_connect: bool,
        retry_on_timeout: bool = False,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await self._client.post(path, data=dict(data))
            except httpx.ConnectError as error:
                # Nothing reached the server, so repeating cannot duplicate.
                last_error = error
                if not retry_on_connect or attempt == MAX_ATTEMPTS:
                    break
                await self._backoff(attempt)
            except httpx.TimeoutException as error:
                # The request may have been received and acted on, so this is
                # repeated only where repetition is idempotent.
                last_error = error
                if not retry_on_timeout or attempt == MAX_ATTEMPTS:
                    raise TelegraphUnreachableError(
                        f"Telegraph did not answer the {path.lstrip('/')} request "
                        f"in time. The request may still have been processed — "
                        f"check https://{TELEGRAPH_HOST} before retrying a publish."
                    ) from error
                await self._backoff(attempt)
            except httpx.HTTPError as error:
                raise TelegraphUnreachableError(
                    f"Could not reach Telegraph for {path.lstrip('/')}: "
                    f"{type(error).__name__}"
                ) from error

        raise TelegraphUnreachableError(
            f"Could not connect to Telegraph for {path.lstrip('/')} after "
            f"{MAX_ATTEMPTS} attempts. Check network connectivity."
        ) from last_error

    @staticmethod
    async def _backoff(attempt: int) -> None:
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))


class ReadOnlyClient(_BaseClient):
    """Telegraph reads, which are safe to repeat."""

    async def get_page(self, path_or_url: str, *, return_content: bool = False) -> Page:
        path = normalize_page_path(path_or_url)
        result = await self._call(
            "/getPage",
            {"path": path, "return_content": str(return_content).lower()},
        )
        return _page_from_payload(result)

    async def _request(self, path: str, data: Mapping[str, Any]) -> httpx.Response:
        # Reads are idempotent, so a timeout is safe to repeat.
        return await self._send(path, data, retry_on_connect=True, retry_on_timeout=True)


class WritableClient(_BaseClient):
    """Telegraph writes, which are never automatically repeated."""

    async def create_page(
        self,
        *,
        access_token: str,
        title: str,
        content: str,
        author_name: str | None = None,
        author_url: str | None = None,
    ) -> Page:
        data: dict[str, Any] = {
            "access_token": access_token,
            "title": title,
            "content": content,
            "return_content": "false",
        }
        if author_name:
            data["author_name"] = author_name
        if author_url:
            data["author_url"] = author_url
        return _page_from_payload(await self._call(PAGE_PATH, data))

    async def edit_page(
        self,
        *,
        access_token: str,
        path_or_url: str,
        title: str,
        content: str,
        author_name: str | None = None,
        author_url: str | None = None,
    ) -> Page:
        data: dict[str, Any] = {
            "access_token": access_token,
            "path": normalize_page_path(path_or_url),
            "title": title,
            "content": content,
            "return_content": "false",
        }
        if author_name:
            data["author_name"] = author_name
        if author_url:
            data["author_url"] = author_url
        return _page_from_payload(await self._call(EDIT_PATH, data))


async def create_account(
    short_name: str,
    *,
    author_name: str | None = None,
    author_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Account:
    """Create a Telegraph account. Used only by the one-shot bootstrap command."""

    data: dict[str, Any] = {"short_name": short_name}
    if author_name:
        data["author_name"] = author_name
    if author_url:
        data["author_url"] = author_url

    async with _BaseClient(timeout=timeout) as client:
        result = await client._call(ACCOUNT_PATH, data)

    token = result.get("access_token")
    if not token:
        raise TelegraphAPIError(
            "Telegraph created an account but returned no access token."
        )
    return Account(
        short_name=str(result.get("short_name", short_name)),
        access_token=str(token),
        author_name=result.get("author_name"),
        author_url=result.get("author_url"),
        auth_url=result.get("auth_url"),
        page_count=result.get("page_count"),
    )


__all__ = [
    "Account",
    "DEFAULT_TIMEOUT_SECONDS",
    "Page",
    "ReadOnlyClient",
    "WritableClient",
    "create_account",
    "normalize_page_path",
]