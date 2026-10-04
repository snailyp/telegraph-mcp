"""Admission control: who may call this server.

A single shared bearer credential, compared in constant time. The comparison is
the security-relevant line here — a plain `==` on a secret leaks its prefix
through timing, which is enough to recover one byte at a time over many
requests. See ADR 2.
"""

from __future__ import annotations

import hmac

from fastmcp.server.auth.auth import AccessToken, TokenVerifier

CLIENT_ID = "mcp-client"


class StaticBearerVerifier(TokenVerifier):
    """Accept exactly one shared bearer credential.

    Built rather than using FastMCP's `StaticTokenVerifier` because that class
    looks tokens up with an ordinary dict lookup (not constant time) and is
    documented as unsuitable for production.
    """

    def __init__(self, expected_token: str, *, client_id: str = CLIENT_ID) -> None:
        super().__init__()
        self._expected_token = expected_token
        self._client_id = client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return access info for the configured credential, or `None`.

        The token is never logged or echoed, including on rejection.
        """

        if not token:
            return None
        # compare_digest is constant-time for equal-length inputs; encoding first
        # keeps it to a bytes comparison so a non-ASCII token cannot raise.
        if not hmac.compare_digest(
            token.encode("utf-8"), self._expected_token.encode("utf-8")
        ):
            return None
        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=[],
            expires_at=None,
            claims={"sub": self._client_id},
        )


__all__ = ["CLIENT_ID", "StaticBearerVerifier"]